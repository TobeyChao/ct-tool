//! 导出用例：解析校验 → JSON → Accessor/manifest → FBS → Bundle → 发布
//! （对应 Python `app/exporting/build.py` 的 run_pipeline）。
//!
//! 本模块不抢锁、不做发布恢复、不部署、不写成功账本 —— 那些是
//! `run_export`（完成服务）的职责。取消令牌只在准备/构建阶段检查，
//! 进入发布事务后被延后（晚取消不中断发布）。

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::Instant;

use ct_domain::hashing::sha256_hex;
use ct_domain::repository::{Resource, YamlResourceRepository};
use ct_domain::schema::{EnumResource, RecordResource, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::manifest::LayoutManifest;
use ct_export::binary::{
    build_canonical_bundle, build_canonical_table_bytes, count_vtables, plan_object_layout,
    written_slot_ratio, BinaryBuilder,
};
use ct_export::fbs::{table_fbs_text, types_fbs_text, validate_canonical_fbs};
use ct_export::json::serialize_table_json;

use ct_cache::artifacts::ArtifactCache;
use ct_export::CODEGEN_VERSION;

use crate::export_inputs::{
    capture_export_inputs, capture_manifest_contents, capture_sources,
    capture_translation_contents, read_excel_bytes, verify_inputs_unchanged, InputChangedError,
};
use crate::validate::prepare_tables;

type Row = serde_json::Map<String, serde_json::Value>;

/// 一次导出请求的全部输入。
#[derive(Debug, Clone)]
pub struct ExportRequest {
    pub root: PathBuf,
    pub table_filter: Option<String>,
    pub lang_filter: Option<String>,
    pub forced: bool,
}

/// 取消令牌（CLI/worker 共享的最小契约）。
pub trait CancelToken: Send + Sync {
    fn cancelled(&self) -> bool;
}

/// 阶段总数（解析校验 / JSON+bytes / Accessor+manifest / FBS / Bundle）。
pub const STAGE_COUNT: usize = 5;

/// 进度输出（CLI 文本与 worker 事件共用；err=true 走 stderr）。
pub trait Reporter: Send + Sync {
    fn log(&self, line: &str, err: bool);

    /// 阶段边界：`index` 从 0 开始，`total` 为阶段总数。默认无操作。
    fn stage(&self, _name: &str, _index: usize, _total: usize) {}

    /// 校验闸门产出的结构化问题（与文本同时送出，避免上层重复解析校验）。
    fn issues(&self, _issues: &[ct_domain::diagnostics::ValidationIssue]) {}
}

/// 阶段 profile + 诊断承载：把闸门已算出的结构化问题与阶段耗时带出来，
/// 使上层不再二次解析/校验（任务 5.5）。对外行为与文本输出不变。
struct Probe {
    inner: Option<std::sync::Arc<dyn Reporter>>,
    marks: std::sync::Mutex<Vec<(String, std::time::Instant)>>,
    issues: std::sync::Mutex<Vec<ct_domain::diagnostics::ValidationIssue>>,
}

impl Probe {
    fn new(inner: Option<std::sync::Arc<dyn Reporter>>) -> Probe {
        let started = std::time::Instant::now();
        Probe {
            inner,
            marks: std::sync::Mutex::new(vec![("lock".to_string(), started)]),
            issues: std::sync::Mutex::new(Vec::new()),
        }
    }

    fn mark(&self, name: &str) {
        self.marks
            .lock()
            .expect("profile 中毒")
            .push((name.to_string(), std::time::Instant::now()));
    }

    /// 相邻阶段边界之差即该阶段耗时（毫秒）。
    fn stages(&self) -> Vec<(String, u64)> {
        let marks = self.marks.lock().expect("profile 中毒");
        marks
            .windows(2)
            .map(|pair| {
                (
                    pair[0].0.clone(),
                    (pair[1].1 - pair[0].1).as_millis() as u64,
                )
            })
            .collect()
    }

    fn take_issues(&self) -> Vec<ct_domain::diagnostics::ValidationIssue> {
        std::mem::take(&mut *self.issues.lock().expect("profile 中毒"))
    }
}

impl Reporter for Probe {
    fn log(&self, line: &str, err: bool) {
        if let Some(inner) = &self.inner {
            inner.log(line, err);
        }
    }

    fn stage(&self, name: &str, index: usize, total: usize) {
        if let Some(inner) = &self.inner {
            inner.stage(name, index, total);
        }
        self.mark(name);
    }

    fn issues(&self, issues: &[ct_domain::diagnostics::ValidationIssue]) {
        *self.issues.lock().expect("profile 中毒") = issues.to_vec();
        if let Some(inner) = &self.inner {
            inner.issues(issues);
        }
    }
}

/// 千分位分组（对齐 Python `{:,}` 文本）。
fn thousands(value: usize) -> String {
    let digits = value.to_string();
    let mut out = String::new();
    for (index, ch) in digits.chars().enumerate() {
        if index > 0 && (digits.len() - index) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    out
}

/// Pipeline failure. Cancellation is typed so transports do not inspect text.
#[derive(Debug)]
pub enum ExportError {
    Other(String),
    Cancelled(String),
}

impl std::fmt::Display for ExportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Other(message) | Self::Cancelled(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for ExportError {}

impl From<InputChangedError> for ExportError {
    fn from(e: InputChangedError) -> Self {
        ExportError::Other(e.0)
    }
}

/// 导出结果。
#[derive(Debug, Default)]
pub struct ExportResult {
    pub tables: usize,
    pub languages: Vec<String>,
    pub written: Vec<String>,
    pub reused: Vec<String>,
    pub cache_hits: usize,
    pub cache_misses: usize,
    /// 阶段 profile（阶段名 + 毫秒）：证明复用生效与减少重复构建（任务 5.5）。
    pub stages: Vec<(String, u64)>,
    pub bundle_hashes: BTreeMap<String, String>,
    pub excel_hashes: BTreeMap<String, String>,
    pub forced: bool,
    pub elapsed: f64,
    /// 桌面历史写入失败的一次性警告：业务提交已成功，不得当成导出失败。
    pub history_warning: Option<String>,
}

/// 单表构建结果（各语言字节与布局常量）。
#[derive(Default)]
struct TableBuild {
    uniform: bool,
    fill_rate: f64,
    bytes_normal: usize,
    bytes_uniform: Option<usize>,
    slot_offsets: Vec<(u32, u32)>,
    i18n_slot_offsets: Vec<(u32, u32)>,
    primary_bytes: BTreeMap<String, Vec<u8>>,
    i18n_bytes: BTreeMap<String, Vec<u8>>,
}

/// 限制生成器输入为该表的传递具名依赖。
fn table_types<'a>(
    table: &TableResource,
    records: &'a HashMap<String, RecordResource>,
    enums: &'a HashMap<String, EnumResource>,
) -> (
    HashMap<String, RecordResource>,
    HashMap<String, EnumResource>,
) {
    fn named_ref(field: &ct_domain::schema::FieldDef) -> Option<&str> {
        match &field.type_expr {
            TypeExpr::Named(n) => Some(n.name()),
            TypeExpr::Vector(e) => match e.as_ref() {
                TypeExpr::Named(n) => Some(n.name()),
                _ => None,
            },
            _ => None,
        }
    }
    let mut used_records: HashMap<String, RecordResource> = HashMap::new();
    let mut used_enums: HashMap<String, EnumResource> = HashMap::new();
    fn visit<'a>(
        fields: &[ct_domain::schema::FieldDef],
        records: &'a HashMap<String, RecordResource>,
        enums: &'a HashMap<String, EnumResource>,
        used_records: &mut HashMap<String, RecordResource>,
        used_enums: &mut HashMap<String, EnumResource>,
    ) {
        for field in fields {
            let Some(name) = named_ref(field) else {
                continue;
            };
            if let Some(record) = records.get(name) {
                if !used_records.contains_key(name) {
                    used_records.insert(name.to_string(), record.clone());
                    visit(&record.fields, records, enums, used_records, used_enums);
                }
            } else if let Some(enum_) = enums.get(name) {
                used_enums
                    .entry(name.to_string())
                    .or_insert_with(|| enum_.clone());
            }
        }
    }
    visit(
        &table.fields,
        records,
        enums,
        &mut used_records,
        &mut used_enums,
    );
    (used_records, used_enums)
}

/// 稀疏 i18n 表：主键 + i18n 字段（保持主表声明顺序）。
fn i18n_table(table: &TableResource) -> Option<TableResource> {
    let i18n_fields: Vec<_> = table
        .fields
        .iter()
        .filter(|f| f.i18n && !f.server_only)
        .cloned()
        .collect();
    if i18n_fields.is_empty() {
        return None;
    }
    let primary = table.fields.iter().find(|f| f.name == table.primary)?;
    Some(TableResource {
        table: format!("{}_i18n", table.table),
        primary: table.primary.clone(),
        fields: [vec![primary.clone()], i18n_fields].concat(),
        json_key: None,
        excel_file: None,
        indexes: vec![],
        uniform: table.uniform,
    })
}

/// 主表行 → i18n 表行（主键 + i18n 字段，保持主表行序）。
fn i18n_rows(table: &TableResource, sparse: &TableResource, merged: &[Row]) -> Vec<Row> {
    let names: Vec<&str> = sparse
        .fields
        .iter()
        .filter(|f| f.name != table.primary)
        .map(|f| f.name.as_str())
        .collect();
    merged
        .iter()
        .map(|row| {
            let mut out = Row::new();
            out.insert(
                table.primary.clone(),
                row.get(&table.primary)
                    .cloned()
                    .unwrap_or(serde_json::Value::Null),
            );
            for name in &names {
                out.insert(
                    name.to_string(),
                    row.get(*name).cloned().unwrap_or(serde_json::Value::Null),
                );
            }
            out
        })
        .collect()
}

/// 用确认译文替换 i18n 顶层字段。
fn merge_i18n(
    rows: &[Row],
    table: &TableResource,
    translations: &BTreeMap<String, (String, bool)>,
) -> Vec<Row> {
    let i18n_fields: Vec<_> = table.fields.iter().filter(|f| f.i18n).collect();
    if i18n_fields.is_empty() {
        return rows.to_vec();
    }
    rows.iter()
        .map(|row| {
            let mut new_row = row.clone();
            let row_id = row
                .get(&table.primary)
                .map(|v| match v {
                    serde_json::Value::Number(n) => n.to_string(),
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                })
                .unwrap_or_default();
            for field in &i18n_fields {
                let key = format!("{row_id}.{}", field.name);
                if let Some((text, confirmed)) = translations.get(&key) {
                    if !text.is_empty() && *confirmed {
                        new_row.insert(field.name.clone(), text.clone().into());
                    }
                }
            }
            new_row
        })
        .collect()
}

/// 从捕获字节读译文表：key → (text, confirmed)。
fn load_translation(
    contents: &BTreeMap<PathBuf, Vec<u8>>,
    path: &Path,
) -> BTreeMap<String, (String, bool)> {
    let mut out = BTreeMap::new();
    let Some(bytes) = contents.get(path) else {
        return out;
    };
    let Ok(text) = std::str::from_utf8(bytes) else {
        return out;
    };
    let Ok(data) = serde_json::from_str::<BTreeMap<String, serde_json::Value>>(text) else {
        return out;
    };
    for (key, entry) in data {
        let text = entry
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let confirmed = entry
            .get("confirmed")
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        out.insert(key, (text, confirmed));
    }
    out
}

/// 定宽硬断言：uniform 表恰好 1 种 vtable（空表空真成立）。
fn assert_single_vtable(
    name: &str,
    lang: &str,
    data: &[u8],
    row_count: usize,
) -> Result<(), ExportError> {
    let n = count_vtables(data);
    if n != 1 && !(n == 0 && row_count == 0) {
        return Err(ExportError::Other(format!(
            "{name}[{lang}]：uniform 布局下出现 {n} 种 vtable（要求恰好 1 种）\
             ——二进制布局未遵守 Schema 布局计划，请检查生成器或缓存产物"
        )));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 五阶段 pipeline
// ---------------------------------------------------------------------------

/// 路径身份键：Windows 下大小写不敏感（对齐 Python normcase 语义，
/// 避免大小写差异把同一文件同时当成「新增」和「陈旧」）。
fn pkey(path: &Path) -> String {
    crate::export_inputs::normalize(path)
}

struct Publication {
    forced: bool,
    /// 暂存批次与改名由同一个发布器负责（同一卷，rename 原子）。
    publisher: ct_storage::publication::FilePublisher,
    operation_id: String,
    /// 规范化键集合（stage 登记）
    expected: std::collections::BTreeSet<String>,
    /// 已写穿到私有暂存区的批次：内存不再持有产物字节。
    payloads: BTreeMap<PathBuf, ct_storage::publication::StagedPayload>,
    /// 暂存期间的 I/O 失败：留到发布前统一拒绝，绝不发布半成品。
    staged_error: Option<String>,
    committed: bool,
    uncounted: std::collections::BTreeSet<String>,
    written: Vec<String>,
    reused: Vec<String>,
}

impl Publication {
    fn new(root: &Path, forced: bool) -> Self {
        Publication {
            forced,
            publisher: ct_storage::publication::FilePublisher::new(root),
            operation_id: format!("{:x}-{:x}", pid_tag(), std::process::id()),
            expected: Default::default(),
            payloads: Default::default(),
            staged_error: None,
            committed: false,
            uncounted: Default::default(),
            written: Vec::new(),
            reused: Vec::new(),
        }
    }

    /// 发布前必须看到的暂存失败（磁盘满/权限等）。
    fn staged_failure(&self) -> Option<&String> {
        self.staged_error.as_ref()
    }

    /// 标记已提交：之后 Drop 不再清理暂存（发布器自己收尾）。
    fn mark_committed(&mut self) {
        self.committed = true;
    }

    /// 登记待发布目标。count=false：进入发布集合但不计入 written/reused
    ///（layout manifest 属于发布范围，但 written 只报 output/ 产物）。
    /// 复用判定对「尚未改写」的正式文件做；大小写差异按平台语义归一。
    fn stage(&mut self, path: PathBuf, payload: &[u8], count: bool) {
        let key = pkey(&path);
        self.expected.insert(key.clone());
        // 与正式文件逐字节相同 ⇒ 复用，连暂存都不必写
        let identical =
            !self.forced && path.is_file() && std::fs::read(&path).is_ok_and(|old| old == payload);
        if identical {
            if count {
                self.reused.push(path.to_string_lossy().to_string());
            }
            return;
        }
        // 同键只留一份（后写覆盖）：哈希相同即内容相同，直接丢弃新的暂存。
        if let Some((existing_path, existing)) = self.payloads.iter().find(|(p, _)| pkey(p) == key)
        {
            let existing_hash = existing.new_hash.clone();
            let existing_staged = existing.staged.clone();
            let new_hash = ct_storage::publication::sha256_hex(payload);
            if existing_hash == new_hash {
                return;
            }
            self.payloads.remove(&existing_path.clone());
            self.publisher.drop_staged(&[existing_staged]);
        }
        match self
            .publisher
            .stage_private(&self.operation_id, &path, payload)
        {
            Ok(staged) => {
                self.payloads.insert(path, staged);
                if !count {
                    self.uncounted.insert(key);
                }
            }
            Err(error) => {
                // 记下第一份失败：发布前统一拒绝，不产出半成品事务
                if self.staged_error.is_none() {
                    self.staged_error = Some(error.0);
                }
            }
        }
    }

    #[cfg_attr(not(debug_assertions), allow(dead_code))]
    fn payload_bytes(&self) -> usize {
        self.payloads.values().map(|v| v.bytes as usize).sum()
    }

    /// 给定目录下、不在 expected 中的文件 = 陈旧产物（排除自身暂存）。
    fn stale_in(&self, roots: &[PathBuf]) -> Vec<PathBuf> {
        let mut stale = Vec::new();
        for root in roots {
            if !root.exists() {
                continue;
            }
            let mut stack = vec![root.clone()];
            while let Some(dir) = stack.pop() {
                let Ok(entries) = std::fs::read_dir(&dir) else {
                    continue;
                };
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        stack.push(path);
                        continue;
                    }
                    if !path.is_file() || self.expected.contains(&pkey(&path)) {
                        continue;
                    }
                    let name = entry.file_name().to_string_lossy().to_string();
                    if name.starts_with(".ct-stage-") {
                        continue;
                    }
                    stale.push(path);
                }
            }
        }
        stale.sort();
        stale
    }
}

/// Drop 兜底：未提交就销毁时清掉已写穿的暂存文件，
/// 失败路径与 panic 都不该在私有目录里留下垃圾。
impl Drop for Publication {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        let paths: Vec<PathBuf> = self.payloads.values().map(|v| v.staged.clone()).collect();
        self.publisher.drop_staged(&paths);
        let _ = std::fs::remove_dir_all(self.publisher.staging_dir(&self.operation_id));
    }
}

fn pid_tag() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// 阶段边界钩子（测试故障注入用；生产传 None）。
pub type StageHook<'a> = Option<&'a dyn Fn(&str) -> Result<(), ExportError>>;

/// 五阶段导出内核（见模块文档）。
pub fn run_pipeline(
    request: &ExportRequest,
    cancel: Option<&dyn CancelToken>,
    stage_hook: StageHook<'_>,
) -> Result<ExportResult, ExportError> {
    run_pipeline_with_reporter(request, cancel, stage_hook, None)
}

/// 带进度回调的导出内核。
pub fn run_pipeline_with_reporter(
    request: &ExportRequest,
    cancel: Option<&dyn CancelToken>,
    stage_hook: StageHook<'_>,
    reporter: Option<&dyn Reporter>,
) -> Result<ExportResult, ExportError> {
    let started = Instant::now();
    let hook = |stage: &str| -> Result<(), ExportError> {
        if let Some(h) = stage_hook {
            h(stage)?;
        }
        Ok(())
    };
    let check_cancel = |stage: &str| -> Result<(), ExportError> {
        if cancel.is_some_and(|t| t.cancelled()) {
            return Err(ExportError::Cancelled(format!(
                "导出已取消（阶段 {stage}）"
            )));
        }
        Ok(())
    };

    // 配置与 schema/types 从捕获内容解析（不 glob、不重读盘）
    let (config, source_contents) = capture_sources(&request.root).map_err(ExportError::Other)?;
    let contents_map: HashMap<PathBuf, Vec<u8>> = source_contents
        .iter()
        .map(|(p, b)| (p.clone(), b.clone()))
        .collect();
    let repo =
        YamlResourceRepository::new(config.resolve("schemas_dir"), config.resolve("types_dir"));
    let workspace_resources = repo
        .load_captured(&contents_map)
        .map_err(|e| ExportError::Other(e.0))?;
    let workspace = crate::workspace::Workspace {
        root: request.root.clone(),
        config: config.clone(),
        resources: workspace_resources,
    };

    let records = workspace.resources.records_map();
    let enums = workspace.resources.enums_map();
    let output_dir = config.resolve("output_dir");
    let excel_dir = config.resolve("excel_dir");
    let languages: Vec<String> = config
        .all_langs()
        .into_iter()
        .filter(|lang| {
            request.lang_filter.is_none() || request.lang_filter.as_deref() == Some(lang)
        })
        .collect();
    if request.lang_filter.is_some() && languages.is_empty() {
        return Err(ExportError::Other(format!(
            "语言 '{}' 不在可导出语言中（可用: {}）",
            request.lang_filter.clone().unwrap_or_default(),
            config.all_langs().join(", ")
        )));
    }

    // ---- 输入捕获：源 Excel 只读一次，reader 与账本共用同一批字节 ----
    let selected = crate::validate::select_tables(&workspace, request.table_filter.as_deref());
    if request.table_filter.is_some() && selected.is_empty() {
        return Err(ExportError::Other(format!(
            "表 '{}' 不存在",
            request.table_filter.clone().unwrap_or_default()
        )));
    }
    let selected_refs: Vec<&TableResource> = selected.iter().collect();
    let excel_bytes = read_excel_bytes(&config, &selected_refs);
    let i18n_contents = capture_translation_contents(&config, &selected_refs, &languages);
    let manifest_contents = capture_manifest_contents(&config, &selected_refs);
    let before_inputs = capture_export_inputs(&config, &selected_refs, &languages, false);
    verify_inputs_unchanged(
        &before_inputs,
        &capture_export_inputs(&config, &selected_refs, &languages, false),
        "捕获期间",
    )?;
    crate::memdiag::report(
        "capture",
        &[
            crate::memdiag::sample_bytes(
                "sources",
                source_contents.iter().map(|(p, b)| (p.clone(), b.clone())),
            ),
            crate::memdiag::sample_bytes(
                "excel",
                excel_bytes.iter().map(|(p, b)| (p.clone(), b.clone())),
            ),
            crate::memdiag::sample_bytes(
                "i18n",
                i18n_contents.iter().map(|(p, b)| (p.clone(), b.clone())),
            ),
            crate::memdiag::sample_bytes(
                "manifests",
                manifest_contents
                    .iter()
                    .map(|(p, b)| (p.clone(), b.clone())),
            ),
        ],
    );
    hook("capture")?;

    // ---- 阶段 1：解析校验（含 ref 依赖表；只产出显式选中表） ----
    if let Some(reporter) = reporter {
        reporter.stage("prepare", 0, STAGE_COUNT);
    }
    check_cancel("prepare")?;
    let result = prepare_tables(
        &workspace,
        request.table_filter.as_deref(),
        true,
        Some(&excel_bytes),
    );
    if let Some(unknown) = &result.unknown_table {
        return Err(ExportError::Other(format!("表 '{unknown}' 不存在")));
    }
    if let Some(missing) = result.missing_excel.first() {
        return Err(ExportError::Other(format!(
            "Excel 文件不存在: {}",
            missing.display()
        )));
    }
    if !result.issues.is_empty() {
        // 结构化问题随文本一并带出：上层不必再跑一遍解析校验（任务 5.5）
        if let Some(reporter) = reporter {
            reporter.issues(&result.issues);
        }
        // 与 Python report_errors 同文本（CLI 直接转写 stderr）
        let mut text = format!("\n验证发现 {} 个错误：\n", result.issues.len());
        for issue in &result.issues {
            text.push_str(&format!("  ✗ {}\n", issue.render()));
        }
        return Err(ExportError::Other(format!("校验失败：{text}")));
    }
    if let Some(reporter) = reporter {
        for item in &result.prepared {
            reporter.log(
                &format!("解析 {}（{} 行）", item.table.table, item.parsed.rows.len()),
                false,
            );
        }
    }
    let prepared: Vec<_> = result.prepared.into_iter().filter(|p| p.explicit).collect();
    if crate::memdiag::enabled() {
        let total: usize = prepared.iter().map(|p| p.parsed.rows.len()).sum();
        let bytes: usize = prepared
            .iter()
            .map(|p| crate::memdiag::sample_rows("rows", &p.parsed.rows).bytes)
            .sum();
        crate::memdiag::report(
            "prepare",
            &[crate::memdiag::Sample {
                name: "parsed_rows",
                count: total,
                bytes,
            }],
        );
    }

    // 账本哈希直接用已捕获的字节；算完立刻交还工作簿内存，
    // 不再与后面的产物字节同时驻留。
    let excel_hashes: BTreeMap<String, String> = prepared
        .iter()
        .filter_map(|item| {
            excel_bytes
                .get(&item.excel_path)
                .map(|bytes| (item.table.table.clone(), sha256_hex(bytes)))
        })
        .collect();
    drop(excel_bytes);
    check_cancel("prepare")?;

    let mut publication = Publication::new(&request.root, request.forced);
    let mut cache = ArtifactCache::new(
        &config.resolve("cache_dir"),
        CODEGEN_VERSION,
        request.forced,
    );
    if let Some(reporter) = reporter {
        reporter.stage("json", 1, STAGE_COUNT);
    }
    check_cancel("json")?;
    // ---- 阶段 2+3：按表有界并行计算（JSON/bytes/Accessor/manifest/FBS），
    //      串行合并：缓存写入、发布登记与诊断都按表序进行，与串行语义一致 ----
    let workers = max_workers();
    let budget = wave_budget_bytes();
    // 输入侧的字节量是已知的（工作簿 + 译文 + manifest）：用它给首波的表均驻留定价。
    let total_tables = prepared.len().max(1);
    let input_estimate: usize = prepared
        .iter()
        .map(|item| {
            let excel = std::fs::metadata(&item.excel_path)
                .map(|m| m.len())
                .unwrap_or(0);
            excel as usize * INPUT_TO_PAYLOAD_FACTOR
        })
        .sum();
    let mut builds: BTreeMap<String, TableBuild> = BTreeMap::new();
    let mut fbs_texts: Vec<(String, String)> = Vec::new();
    // 按内存预算分波：一波算完就写穿暂存并丢弃该波解析行集，峰值不再随表数
    // 线性增长；合并顺序仍是表序，诊断文本与串行语义逐字一致。
    let mut queue: std::collections::VecDeque<crate::validate::PreparedTable> =
        prepared.into_iter().collect();
    let mut done_tables = 0usize;
    let mut seen_payload = 0usize;
    let mut wave = 0usize;
    while !queue.is_empty() {
        check_cancel("table_build")?;
        wave += 1;
        // 已有实测均值时用实测值；首波用输入字节（工作簿 + 该表译文）给保守估计，
        // 避免「第一波只能算一张表」把并行的好处先吃掉一截。
        let avg = seen_payload
            .checked_div(done_tables)
            .unwrap_or_else(|| input_estimate.checked_div(total_tables).unwrap_or(0));
        let size = pick_wave(queue.len(), workers, budget, avg);
        let chunk: Vec<crate::validate::PreparedTable> = queue.drain(..size).collect();
        let outcomes = {
            let context = TableBuildContext {
                config: &config,
                languages: &languages,
                i18n_contents: &i18n_contents,
                manifest_contents: &manifest_contents,
                records: &records,
                enums: &enums,
                cache: &cache,
                forced: request.forced,
                output_dir: &output_dir,
                excel_dir: &excel_dir,
            };
            parallel_map(&chunk, size.min(workers).max(1), |item| {
                compute_table(item, &context)
            })
        };
        check_cancel("table_build")?;
        for (item, outcome) in chunk.iter().zip(outcomes) {
            let work = outcome?;
            seen_payload += work
                .stages
                .iter()
                .map(|(_, bytes, _)| bytes.len())
                .sum::<usize>();
            done_tables += 1;
            merge_work(
                &mut cache,
                &mut publication,
                work.hits,
                work.misses,
                work.used,
                work.writes,
                work.stages,
            );
            if let Some(reporter) = reporter {
                for line in &work.logs {
                    reporter.log(line, false);
                }
            }
            fbs_texts.push((item.table.table.clone(), work.fbs_text));
            builds.insert(item.table.table.clone(), work.build);
        }
        // chunk 在此离开作用域：本波解析行集立即归还
        if crate::memdiag::enabled() {
            crate::memdiag::report(
                &format!("wave-{wave}"),
                &[crate::memdiag::Sample {
                    name: "payload",
                    count: publication.payloads.len(),
                    bytes: publication.payload_bytes(),
                }],
            );
        }
    }
    drop(i18n_contents);
    drop(manifest_contents);
    if let Some(reporter) = reporter {
        reporter.stage("accessor", 2, STAGE_COUNT);
    }
    check_cancel("accessor")?;
    if crate::memdiag::enabled() {
        let primary: usize = builds
            .values()
            .map(|b| b.primary_bytes.values().map(|v| v.len()).sum::<usize>())
            .sum();
        let i18n: usize = builds
            .values()
            .map(|b| b.i18n_bytes.values().map(|v| v.len()).sum::<usize>())
            .sum();
        crate::memdiag::report(
            "after-tables",
            &[
                crate::memdiag::Sample {
                    name: "build_bytes",
                    count: builds.len(),
                    bytes: primary + i18n,
                },
                crate::memdiag::Sample {
                    name: "payload",
                    count: publication.payloads.len(),
                    bytes: publication.payload_bytes(),
                },
            ],
        );
    }

    // 枚举类型声明（全部表共享一份）
    if !enums.is_empty() {
        let enums_sorted: BTreeMap<String, EnumResource> =
            enums.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
        let enums_key = serde_json::json!(enums_sorted
            .iter()
            .map(|(k, v)| (
                k,
                ct_domain::hashing::resource_to_data(&Resource::Enum(v.clone()))
            ))
            .collect::<BTreeMap<_, _>>());
        let enum_cs = cache
            .call_text("generate_csharp_enums", &enums_key, || {
                Ok(ct_export::accessor_csharp::generate_csharp_enums(
                    &enums_sorted,
                ))
            })
            .map_err(ExportError::Other)?;
        let enum_lua = cache
            .call_text("generate_lua_enums", &enums_key, || {
                Ok(ct_export::accessor_lua::generate_lua_enums(&enums_sorted))
            })
            .map_err(ExportError::Other)?;
        publication.stage(
            output_dir.join("generated").join("csharp").join("Enums.cs"),
            enum_cs.as_bytes(),
            true,
        );
        publication.stage(
            output_dir.join("generated").join("lua").join("Enums.lua"),
            enum_lua.as_bytes(),
            true,
        );
        if let Some(reporter) = reporter {
            reporter.log(
                &format!("枚举声明 {} 个 → Enums.cs / Enums.lua", enums.len()),
                false,
            );
        }
    }

    if let Some(reporter) = reporter {
        reporter.stage("fbs", 3, STAGE_COUNT);
    }
    check_cancel("fbs")?;
    // ---- 阶段 4：共享 types.fbs + 各表 FBS + container ----
    let all_resources: Vec<Resource> = workspace
        .resources
        .tables
        .iter()
        .cloned()
        .map(Resource::Table)
        .chain(
            workspace
                .resources
                .records
                .iter()
                .cloned()
                .map(Resource::Record),
        )
        .chain(
            workspace
                .resources
                .enums
                .iter()
                .cloned()
                .map(Resource::Enum),
        )
        .collect();
    let mut order: Vec<String> = all_resources.iter().map(|r| r.resource_id()).collect();
    order.sort();
    let resources_map: BTreeMap<String, Resource> = all_resources
        .iter()
        .map(|r| (r.resource_id(), r.clone()))
        .collect();
    let types_key = serde_json::json!([
        order,
        resources_map
            .iter()
            .map(|(k, v)| (k, ct_domain::hashing::resource_to_data(v)))
            .collect::<BTreeMap<_, _>>()
    ]);
    let types_text = cache
        .call_text("types_fbs_text", &types_key, || {
            Ok(types_fbs_text(&order, &resources_map))
        })
        .map_err(ExportError::Other)?;
    publication.stage(
        output_dir.join("fbs").join("types.fbs"),
        types_text.as_bytes(),
        true,
    );
    let mut table_fbs: HashMap<String, String> = HashMap::new();
    for (name, text) in fbs_texts {
        table_fbs.insert(name, text);
    }
    validate_canonical_fbs(&types_text, &table_fbs, &all_resources)
        .map_err(|e| ExportError::Other(format!("FBS 结构检查失败: {e}")))?;
    for (name, text) in &table_fbs {
        publication.stage(
            output_dir.join("fbs").join(format!("{name}.fbs")),
            text.as_bytes(),
            true,
        );
    }
    publication.stage(
        output_dir.join("fbs").join("container.fbs"),
        b"table BundledTable {\n  name: string;\n  data: [ubyte];\n}\ntable DataBundle {\n  tables: [BundledTable];\n}\n\nroot_type DataBundle;\n",
        true,
    );

    if let Some(reporter) = reporter {
        reporter.stage("bundle", 4, STAGE_COUNT);
    }
    check_cancel("bundle")?;
    // ---- 阶段 5：Binary Bundle ----
    // bundle 需要「该语言全部表」的字节。只有预算容得下「所有语言同时在算」时才并行，
    // 否则逐语言算、并入后立刻释放该语言的表级字节：峰值从「语言数 × 全部表字节」降到
    // 「一个 bundle」。两条路径产物字节完全相同，只是驻留与耗时互换。
    let build_bytes: usize = builds
        .values()
        .map(|b| {
            b.primary_bytes.values().map(|v| v.len()).sum::<usize>()
                + b.i18n_bytes.values().map(|v| v.len()).sum::<usize>()
        })
        .sum();
    let bundle_workers = match build_bytes.checked_mul(languages.len()) {
        Some(worst) if worst <= budget => workers.min(languages.len().max(1)),
        _ => 1,
    };
    if crate::memdiag::enabled() {
        eprintln!(
            "[memdiag] bundle-plan bytes={} languages={} bundle_workers={}",
            build_bytes,
            languages.len(),
            bundle_workers
        );
    }
    let mut bundle_hashes: BTreeMap<String, String> = BTreeMap::new();
    let mut serial_langs: Vec<String> = Vec::new();
    if bundle_workers > 1 {
        let bundle_outcomes = parallel_map(&languages, bundle_workers, |lang| {
            compute_bundle(lang, &config, &builds, &cache, request.forced, &output_dir)
        });
        check_cancel("bundle")?;
        for (lang, outcome) in languages.iter().zip(bundle_outcomes) {
            let work = outcome?;
            merge_work(
                &mut cache,
                &mut publication,
                work.hits,
                work.misses,
                work.used,
                work.writes,
                vec![(work.path, work.bytes, true)],
            );
            bundle_hashes.insert(lang.clone(), work.fingerprint);
        }
    } else {
        serial_langs = languages.clone();
    }
    for lang in &serial_langs {
        check_cancel("bundle")?;
        let work = compute_bundle(lang, &config, &builds, &cache, request.forced, &output_dir)?;
        merge_work(
            &mut cache,
            &mut publication,
            work.hits,
            work.misses,
            work.used,
            work.writes,
            vec![(work.path, work.bytes, true)],
        );
        bundle_hashes.insert(lang.clone(), work.fingerprint);
        for build in builds.values_mut() {
            build.primary_bytes.remove(lang);
            build.i18n_bytes.remove(lang);
        }
    }
    if crate::memdiag::enabled() {
        let primary: usize = builds
            .values()
            .map(|b| b.primary_bytes.values().map(|v| v.len()).sum::<usize>())
            .sum();
        let i18n: usize = builds
            .values()
            .map(|b| b.i18n_bytes.values().map(|v| v.len()).sum::<usize>())
            .sum();
        crate::memdiag::report(
            "after-bundle",
            &[
                crate::memdiag::Sample {
                    name: "build_bytes",
                    count: builds.len(),
                    bytes: primary + i18n,
                },
                crate::memdiag::Sample {
                    name: "payload",
                    count: publication.payloads.len(),
                    bytes: publication.payload_bytes(),
                },
            ],
        );
    }
    // 发布前复核：全部生成完成、清理与记账之前，再确认这期间输入未变
    hook("pre_publish")?;
    verify_inputs_unchanged(
        &before_inputs,
        &capture_export_inputs(&config, &selected_refs, &languages, false),
        "生成期间",
    )?;
    // Last reversible checkpoint. A request received after this point must not
    // change the outcome of a publication that has already committed.
    check_cancel("pre_publish")?;

    // ---- 发布：一个事务完成替换与删除；全部生成与结构检查成功后才开始 ----
    if let Some(reporter) = reporter {
        reporter.stage("publish", STAGE_COUNT, STAGE_COUNT);
    }
    let full_export = request.table_filter.is_none() && request.lang_filter.is_none();
    let deletions = if full_export {
        publication.stale_in(&[
            output_dir.join("fbs"),
            output_dir.join("generated"),
            output_dir.join("json"),
            output_dir.join("binary"),
        ])
    } else {
        Vec::new()
    };
    if let Some(reason) = publication.staged_failure() {
        // 生成期间写穿失败（磁盘满/权限）：不发布半成品，交给 Drop 清理暂存。
        return Err(ExportError::Other(format!("发布失败，已回滚：{reason}")));
    }
    let writes: Vec<(PathBuf, ct_storage::publication::StagedPayload)> = publication
        .payloads
        .iter()
        .map(|(path, payload)| (path.clone(), payload.clone()))
        .collect();
    let publish_result = publication
        .publisher
        .publish_staged(&publication.operation_id, &writes, &deletions)
        .map_err(|e| ExportError::Other(format!("发布失败，已回滚：{e}")));
    if publish_result.is_ok() {
        publication.mark_committed();
    }
    publish_result?;

    // written 必须在汇总日志之前定型（对应 Python `Publication.commit` 先填充再打印）。
    for path in publication.payloads.keys() {
        if !publication.uncounted.contains(&pkey(path)) {
            publication.written.push(path.to_string_lossy().to_string());
        }
    }
    if full_export {
        for path in &deletions {
            if let Some(reporter) = reporter {
                reporter.log(
                    &format!(
                        "清理陈旧产物 {}",
                        path.strip_prefix(&output_dir)
                            .unwrap_or(path.as_path())
                            .display()
                    ),
                    false,
                );
            }
        }
        cache.prune();
    }
    if let Some(reporter) = reporter {
        reporter.log(
            &format!(
                "{}：写入 {}，复用 {}；生成缓存命中 {}",
                if request.forced {
                    "强制重建"
                } else {
                    "增量导出"
                },
                publication.written.len(),
                publication.reused.len(),
                cache.hits
            ),
            false,
        );
    }

    Ok(ExportResult {
        stages: Vec::new(),
        tables: selected.len(),
        languages,
        written: std::mem::take(&mut publication.written),
        reused: std::mem::take(&mut publication.reused),
        cache_hits: cache.hits,
        cache_misses: cache.misses,
        bundle_hashes,
        excel_hashes,
        forced: request.forced,
        elapsed: started.elapsed().as_secs_f64(),
        history_warning: None,
    })
}

// ---------------------------------------------------------------------------
// 完成服务（对应 Python `app/exporting/service.py`）
// ---------------------------------------------------------------------------

/// 入口策略：桌面只导出；CLI 导出后可部署。
#[derive(Debug, Clone, Copy, Default)]
pub struct CompletionPolicy {
    pub deploy: bool,
    pub for_build: bool,
}

impl CompletionPolicy {
    pub fn export_only() -> Self {
        Self::default()
    }

    pub fn export_then_deploy(for_build: bool) -> Self {
        CompletionPolicy {
            deploy: true,
            for_build,
        }
    }
}

/// 提交成功账本（cache/state.json）。只在导出整体成功（含部署）后调用：
/// 失败的运行不碰缓存，status 继续报告 last-good。
pub fn persist_export_state(
    root: &Path,
    excel_hashes: &BTreeMap<String, String>,
    bundle_hashes: &BTreeMap<String, String>,
) -> Result<PathBuf, ExportError> {
    let config = ct_domain::config::GlobalConfig::load(root).map_err(ExportError::Other)?;
    let cache_dir = config.resolve("cache_dir");
    let state = ct_cache::state::load_state(&cache_dir).unwrap_or_default();
    let state = ct_cache::state::record_excel_hashes(state, excel_hashes);
    let state = ct_cache::state::upsert_bundles(state, bundle_hashes);
    ct_cache::state::save_state(&cache_dir, &state).map_err(ExportError::Other)
}

/// 完成用例的失败分类（CLI 据此选择错误前缀与退出方式）。
#[derive(Debug)]
pub enum RunError {
    /// 校验问题清单（已渲染文本 + 闸门算出的结构化问题，避免上层重复解析校验）
    Validation(String, Vec<ct_domain::diagnostics::ValidationIssue>),
    /// 工作区被占用
    Busy(String),
    /// Cooperative cancellation accepted before publication begins.
    Cancelled(String),
    /// 发布/回滚失败
    Publish(String),
    /// 部署失败（本地产物保留、账本未推进）
    Deploy(String),
    /// 其他（配置/IO/参数）
    Other(String),
}

impl std::fmt::Display for RunError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RunError::Validation(text, _)
            | RunError::Busy(text)
            | RunError::Cancelled(text)
            | RunError::Publish(text)
            | RunError::Deploy(text)
            | RunError::Other(text) => f.write_str(text),
        }
    }
}

/// 完整导出用例：锁 → 恢复 → pipeline →（按策略）部署 → 提交账本。
/// 返回（结果, 部署日志, 恢复描述）。
pub fn run_export(
    request: &ExportRequest,
    policy: CompletionPolicy,
    cancel: Option<&dyn CancelToken>,
    reporter: Option<std::sync::Arc<dyn Reporter>>,
    record_history: bool,
) -> Result<(ExportResult, Vec<String>, Option<String>), RunError> {
    let probe = std::sync::Arc::new(Probe::new(reporter));
    let transaction =
        ct_storage::workspace::WorkspaceTransaction::begin(&request.root).map_err(|e| match e {
            ct_storage::workspace::TransactionError::Busy(busy) => RunError::Busy(busy.0),
            ct_storage::workspace::TransactionError::Recovery(message) => {
                RunError::Publish(message)
            }
        })?;
    let recovery = transaction.recovery.clone();
    if let Some(note) = recovery.as_ref() {
        probe.log(&format!("[发布恢复] {note}"), false);
    }

    let mut result =
        run_pipeline_with_reporter(request, cancel, None, Some(&*probe)).map_err(|e| {
            let text = match e {
                ExportError::Cancelled(message) => return RunError::Cancelled(message),
                ExportError::Other(message) => message,
            };
            if let Some(rest) = text.strip_prefix("校验失败：") {
                // 闸门算出的结构化问题直接带出，上层不必再解析校验一次（任务 5.5）
                RunError::Validation(rest.to_string(), probe.take_issues())
            } else if text.contains("请稍后重试") {
                RunError::Busy(text)
            } else if text.contains("发布失败") {
                RunError::Publish(text)
            } else {
                RunError::Other(text)
            }
        })?;

    let mut deploy_logs = Vec::new();
    if policy.deploy {
        // 部署失败即整体失败：本地产物保留、账本不推进
        let config =
            ct_domain::config::GlobalConfig::load(&request.root).map_err(RunError::Other)?;
        let (_changed, logs) = ct_export::deploy::deploy(&config, policy.for_build)
            .map_err(|e| RunError::Deploy(e.0))?;
        deploy_logs = logs;
    }

    probe.mark("end");
    result.stages = probe.stages();
    persist_export_state(&request.root, &result.excel_hashes, &result.bundle_hashes)
        .map_err(|e| RunError::Other(e.to_string()))?;
    if record_history {
        // 桌面导出成功后记最近五条历史；历史写失败单独报告，不推翻已成功的提交
        let scope = match (&request.table_filter, &request.lang_filter) {
            (None, None) => "all".to_string(),
            (Some(table), None) => format!("table:{table}"),
            (None, Some(lang)) => format!("lang:{lang}"),
            (Some(table), Some(lang)) => format!("table:{table},lang:{lang}"),
        };
        let entry = serde_json::json!({
            "time": rfc3339_now(),
            "scope": scope,
            "result": "success",
            "tables": result.tables,
            "elapsed": result.elapsed,
            "forced": result.forced,
            "error": "",
        });
        if let Err(error) = crate::history::append_history(&request.root, entry) {
            let warning = format!("[历史] 导出已成功，但桌面历史接续或写入需要检查：{error}");
            probe.log(&warning, true);
            result.history_warning = Some(warning);
        }
    }
    Ok((result, deploy_logs, recovery))
}

// ---------------------------------------------------------------------------
// 有界并行（任务 5.4）：按表/按语言并行计算生成器，串行合并缓存写入、
// 发布登记与诊断，保证任意并发度下产物字节与诊断顺序一致。
// ---------------------------------------------------------------------------

/// 并行 worker 上限（有界；表数少时自动降为串行）。
///
/// `CT_MAX_WORKERS` 可调（并发度对照测试与现场调优用），取值 1..=8。
/// 单波允许的产物字节上限（默认 96 MiB）：写穿之前这是内存大头。
const DEFAULT_WAVE_BUDGET_MB: usize = 96;

/// 首波定价用的经验系数：产物字节 ≈ 压缩工作簿字节 × 该系数（M 夹具实测约 10 倍，
/// 取 8 作为保守值）。它只影响「一波放几张表」，不影响任何产物字节。
const INPUT_TO_PAYLOAD_FACTOR: usize = 8;

/// `CT_EXPORT_MEMORY_BUDGET_MB` 显式覆盖；0 或非法值回落到默认。
fn wave_budget_bytes() -> usize {
    let mb = std::env::var("CT_EXPORT_MEMORY_BUDGET_MB")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(DEFAULT_WAVE_BUDGET_MB);
    let mb = if mb == 0 { DEFAULT_WAVE_BUDGET_MB } else { mb };
    mb * 1024 * 1024
}

/// 一波放几张表：首波 1 张（没有实测均值，宁可小），之后用「已完成表的平均
/// 产物字节」推算，使一波的估算驻留不超过预算，且永不超过 workers。
fn pick_wave(remaining: usize, workers: usize, budget: usize, avg_table_bytes: usize) -> usize {
    if remaining == 0 || workers == 0 {
        return 0;
    }
    if avg_table_bytes == 0 {
        return 1;
    }
    let fit = (budget / avg_table_bytes).max(1);
    remaining.min(workers).min(fit)
}

fn max_workers() -> usize {
    let limit = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(1)
        .min(8);
    // macOS M 档实测：默认 8 个 worker 超出 RSS 比值门槛；3 个同时满足时间与内存。
    // 显式 CT_MAX_WORKERS 仍可在 1..=limit 内调优，不改变其它平台默认值。
    let default = if cfg!(target_os = "macos") {
        limit.min(3)
    } else {
        limit
    };
    match std::env::var("CT_MAX_WORKERS")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
    {
        Some(forced) => forced.clamp(1, limit.max(1)),
        None => default,
    }
}

/// 有界并行 map：分块 + scoped 线程，结果按输入顺序返回（不做工作窃取，
/// 保证汇总顺序确定；worker panic 视为缺陷直接冒泡）。
fn parallel_map<T, R, F>(items: &[T], workers: usize, f: F) -> Vec<R>
where
    T: Sync,
    R: Send,
    F: Fn(&T) -> R + Send + Sync,
{
    if workers <= 1 || items.len() <= 1 {
        return items.iter().map(&f).collect();
    }
    let chunk = items.len().div_ceil(workers);
    let f = &f;
    std::thread::scope(|scope| {
        let handles: Vec<_> = items
            .chunks(chunk)
            .map(|part| {
                scope.spawn(move || {
                    let mut out = Vec::with_capacity(part.len());
                    for item in part {
                        out.push(f(item));
                    }
                    out
                })
            })
            .collect();
        let mut results = Vec::with_capacity(items.len());
        for handle in handles {
            results.extend(handle.join().expect("并行 worker panic"));
        }
        results
    })
}

/// 缓存写入意图（并行阶段只读缓存，写回在合并阶段串行执行）。
enum CacheWrite {
    Text(String),
    Bytes(Vec<u8>),
}

/// 并行阶段的只读缓存视图：命中计数、未命中记录待写 payload。
struct CacheFront<'a> {
    cache: &'a ArtifactCache,
    forced: bool,
    hits: usize,
    misses: usize,
    used: Vec<PathBuf>,
    writes: Vec<(String, serde_json::Value, CacheWrite)>,
}

impl<'a> CacheFront<'a> {
    fn new(cache: &'a ArtifactCache, forced: bool) -> Self {
        CacheFront {
            cache,
            forced,
            hits: 0,
            misses: 0,
            used: Vec::new(),
            writes: Vec::new(),
        }
    }

    fn text(
        &mut self,
        name: &str,
        inputs: &serde_json::Value,
        generate: impl FnOnce() -> String,
    ) -> String {
        if !self.forced {
            if let Some((value, path)) = self.cache.read_text(name, inputs) {
                self.hits += 1;
                self.used.push(path);
                return value;
            }
        }
        let value = generate();
        self.misses += 1;
        self.writes.push((
            name.to_string(),
            inputs.clone(),
            CacheWrite::Text(value.clone()),
        ));
        value
    }

    fn bytes(
        &mut self,
        name: &str,
        inputs: &serde_json::Value,
        generate: impl FnOnce() -> Result<Vec<u8>, String>,
    ) -> Result<Vec<u8>, ExportError> {
        if !self.forced {
            if let Some((value, path)) = self.cache.read_bytes(name, inputs) {
                self.hits += 1;
                self.used.push(path);
                return Ok(value);
            }
        }
        let value = generate().map_err(ExportError::Other)?;
        self.misses += 1;
        self.writes.push((
            name.to_string(),
            inputs.clone(),
            CacheWrite::Bytes(value.clone()),
        ));
        Ok(value)
    }
}

/// 单表并行计算结果（阶段 2+3 的全部产物）。
struct TableWork {
    build: TableBuild,
    fbs_text: String,
    stages: Vec<(PathBuf, Vec<u8>, bool)>,
    logs: Vec<String>,
    hits: usize,
    misses: usize,
    used: Vec<PathBuf>,
    writes: Vec<(String, serde_json::Value, CacheWrite)>,
}

/// 单语言 Bundle 并行计算结果。
struct BundleWork {
    path: PathBuf,
    bytes: Vec<u8>,
    fingerprint: String,
    hits: usize,
    misses: usize,
    used: Vec<PathBuf>,
    writes: Vec<(String, serde_json::Value, CacheWrite)>,
}

/// 把并行计算结果合并进缓存与发布集合（按表/语言顺序调用，保证确定性）。
fn merge_work(
    cache: &mut ArtifactCache,
    publication: &mut Publication,
    hits: usize,
    misses: usize,
    used: Vec<PathBuf>,
    writes: Vec<(String, serde_json::Value, CacheWrite)>,
    stages: Vec<(PathBuf, Vec<u8>, bool)>,
) {
    cache.hits += hits;
    cache.misses += misses;
    for path in used {
        cache.mark_used(path);
    }
    for (name, inputs, value) in writes {
        match value {
            CacheWrite::Text(text) => cache.store_text(&name, &inputs, &text),
            CacheWrite::Bytes(bytes) => cache.store_bytes(&name, &inputs, &bytes),
        }
    }
    for (path, bytes, count) in stages {
        publication.stage(path, &bytes, count);
    }
}

/// 单表构建所需的只读输入。
///
/// 把表构建的固定依赖集中在一个对象里，避免调用点和函数签名同时承载一长串
/// 容易错位的参数；并行阶段仍然只借用这些输入，不改变缓存写回与发布时序。
struct TableBuildContext<'a> {
    config: &'a ct_domain::config::GlobalConfig,
    languages: &'a [String],
    i18n_contents: &'a BTreeMap<PathBuf, Vec<u8>>,
    manifest_contents: &'a BTreeMap<PathBuf, Vec<u8>>,
    records: &'a HashMap<String, RecordResource>,
    enums: &'a HashMap<String, EnumResource>,
    cache: &'a ArtifactCache,
    forced: bool,
    output_dir: &'a Path,
    excel_dir: &'a Path,
}

/// 单表计算（阶段 2+3）：JSON/主表 bytes/稀疏 i18n bytes/Accessor/manifest/表 FBS。
/// 只读缓存 + 记录待写；发布与缓存写回由合并阶段串行完成。
fn compute_table(
    item: &crate::validate::PreparedTable,
    context: &TableBuildContext<'_>,
) -> Result<TableWork, ExportError> {
    let config = context.config;
    let languages = context.languages;
    let i18n_contents = context.i18n_contents;
    let manifest_contents = context.manifest_contents;
    let records = context.records;
    let enums = context.enums;
    let cache = context.cache;
    let forced = context.forced;
    let output_dir = context.output_dir;
    let excel_dir = context.excel_dir;
    let mut front = CacheFront::new(cache, forced);
    let mut stages: Vec<(PathBuf, Vec<u8>, bool)> = Vec::new();
    let mut logs: Vec<String> = Vec::new();
    let table = &item.table;
    let table_data = ct_domain::hashing::resource_to_data(&Resource::Table(table.clone()));
    let (table_records, table_enums) = table_types(table, records, enums);
    let base_rows = &item.parsed.rows;
    let mut build = TableBuild {
        uniform: table.uniform,
        ..Default::default()
    };

    let client_count = table.client_fields().count();
    let probe_state = BinaryBuilder {
        records: &table_records,
        enums: &table_enums,
        uniform: false,
    };
    let probe_inputs = serde_json::json!([base_rows, table_data, false]);
    let probe = front.bytes("build_canonical_table_bytes", &probe_inputs, || {
        build_canonical_table_bytes(table, base_rows, &probe_state)
            .map_err(|e| format!("{}: {e}", table.table))
    })?;
    build.bytes_normal = probe.len();
    build.fill_rate = written_slot_ratio(&probe, client_count);
    if build.uniform {
        let client_fields: Vec<_> = table.client_fields().collect();
        let layout = plan_object_layout(&client_fields, &table_records)
            .map_err(|e| ExportError::Other(format!("{}: {e}", table.table)))?;
        build.slot_offsets = (0..client_fields.len())
            .map(|i| (4 + 2 * i) as u32)
            .zip(layout.offsets.iter().copied())
            .collect();
    }

    // 主语言：全量行（含原文）
    let primary_translations = load_translation(
        i18n_contents,
        &config
            .resolve("i18n_dir")
            .join(&config.primary_lang)
            .join(format!("{}.json", table.table)),
    );
    let primary_rows = merge_i18n(base_rows, table, &primary_translations);
    let primary_json = output_dir
        .join("json")
        .join(format!("{}_{}.json", table.table, config.primary_lang));
    let primary_json_text = front.text(
        "json",
        &serde_json::json!([primary_rows, table_data]),
        || serialize_table_json(&primary_rows, table),
    );
    stages.push((primary_json, primary_json_text.into_bytes(), true));

    if languages.contains(&config.primary_lang) {
        let state = BinaryBuilder {
            records: &table_records,
            enums: &table_enums,
            uniform: build.uniform,
        };
        let data = if !build.uniform && primary_rows == *base_rows {
            probe.clone()
        } else {
            front.bytes(
                "build_canonical_table_bytes",
                &serde_json::json!([primary_rows, table_data, build.uniform]),
                || {
                    build_canonical_table_bytes(table, &primary_rows, &state)
                        .map_err(|e| format!("{}: {e}", table.table))
                },
            )?
        };
        if build.uniform {
            assert_single_vtable(
                &table.table,
                &config.primary_lang,
                &data,
                primary_rows.len(),
            )?;
            build.bytes_uniform = Some(data.len());
        }
        build
            .primary_bytes
            .insert(config.primary_lang.clone(), data);
    }

    // 次级语言：JSON 全量可评审；bin 走稀疏 i18n 表
    let sparse = i18n_table(table);
    if let (Some(sparse_table), true) = (&sparse, build.uniform) {
        let client_fields: Vec<_> = sparse_table.client_fields().collect();
        let layout = plan_object_layout(&client_fields, &table_records)
            .map_err(|e| ExportError::Other(format!("{}: {e}", sparse_table.table)))?;
        build.i18n_slot_offsets = (0..client_fields.len())
            .map(|i| (4 + 2 * i) as u32)
            .zip(layout.offsets.iter().copied())
            .collect();
    }
    for lang in languages {
        if lang == &config.primary_lang {
            continue;
        }
        let translations = load_translation(
            i18n_contents,
            &config
                .resolve("i18n_dir")
                .join(lang)
                .join(format!("{}.json", table.table)),
        );
        let merged = merge_i18n(base_rows, table, &translations);
        let lang_json = output_dir
            .join("json")
            .join(format!("{}_{}.json", table.table, lang));
        let lang_json_text = front.text("json", &serde_json::json!([merged, table_data]), || {
            serialize_table_json(&merged, table)
        });
        stages.push((lang_json, lang_json_text.into_bytes(), true));
        let Some(sparse_table) = &sparse else {
            continue;
        };
        let sparse_rows = i18n_rows(table, sparse_table, &merged);
        if sparse_rows.len() != primary_rows.len() {
            return Err(ExportError::Other(format!(
                "{}_i18n[{lang}]：{} 行 ≠ 主表 {} 行 —— i18n 表与主表必须同序等长",
                table.table,
                sparse_rows.len(),
                primary_rows.len()
            )));
        }
        let state = BinaryBuilder {
            records: &table_records,
            enums: &table_enums,
            uniform: build.uniform,
        };
        let sparse_data =
            ct_domain::hashing::resource_to_data(&Resource::Table(sparse_table.clone()));
        let data = front.bytes(
            "build_canonical_table_bytes",
            &serde_json::json!([sparse_rows, sparse_data, build.uniform]),
            || {
                build_canonical_table_bytes(sparse_table, &sparse_rows, &state)
                    .map_err(|e| format!("{}: {e}", sparse_table.table))
            },
        )?;
        if build.uniform {
            assert_single_vtable(&sparse_table.table, lang, &data, sparse_rows.len())?;
        }
        build.i18n_bytes.insert(lang.clone(), data);
    }

    // ---- 阶段 3（本表）：Accessor + manifest ----
    let model = ct_export::accessor_model::build_accessor_model(
        table,
        &table.indexes,
        Some(&table_records),
        if build.uniform && !build.slot_offsets.is_empty() {
            Some(build.slot_offsets.iter().copied().collect())
        } else {
            None
        },
        sparse.as_ref().map(|t| t.table.clone()),
        if build.uniform && !build.i18n_slot_offsets.is_empty() {
            Some(build.i18n_slot_offsets.iter().copied().collect())
        } else {
            None
        },
    );
    let model_key = serde_json::json!([table_data, build.slot_offsets, build.i18n_slot_offsets]);
    let csharp = front.text("generate_csharp_accessor", &model_key, || {
        ct_export::accessor_csharp::generate_csharp_accessor(&model, &table_records)
    });
    let lua = front.text("generate_lua_accessor", &model_key, || {
        ct_export::accessor_lua::generate_lua_accessor(&model, &table_records)
    });
    stages.push((
        output_dir
            .join("generated")
            .join("csharp")
            .join(format!("{}Accessor.cs", table.table)),
        csharp.into_bytes(),
        true,
    ));
    stages.push((
        output_dir
            .join("generated")
            .join("lua")
            .join(format!("{}Accessor.lua", table.table)),
        lua.into_bytes(),
        true,
    ));

    let manifest = LayoutManifest::from_layout(&item.layout, &build.slot_offsets);
    let payload = ct_domain::hashing::python_json_pretty(&manifest.payload()) + "\n";
    let manifest_path = excel_dir
        .join("layout_manifests")
        .join(format!("{}.json", table.table));
    let current = manifest_contents
        .get(&manifest_path)
        .map(|b| String::from_utf8_lossy(b).to_string());
    if forced || current.as_deref() != Some(payload.as_str()) {
        stages.push((manifest_path, payload.into_bytes(), false));
    }

    // ---- 阶段 4（本表）：表 FBS 文本 ----
    let fbs_text = front.text("table_fbs_text", &table_data, || table_fbs_text(table));

    // 布局形态在前、填充率在后：填充率只是诊断数字（决策取自 schema 声明）
    let mut detail = format!(
        "{}：{}（schema 声明）｜填充率 {:.1}%",
        table.table,
        if build.uniform { "定宽" } else { "变长" },
        build.fill_rate * 100.0
    );
    if build.uniform {
        detail.push_str(&format!("（{} B", thousands(build.bytes_normal)));
        if let Some(uniform_bytes) = build.bytes_uniform {
            let ratio = uniform_bytes as f64 / build.bytes_normal.max(1) as f64;
            detail.push_str(&format!(" → {} B，{:.3}x", thousands(uniform_bytes), ratio));
            if ratio > 1.25 {
                detail.push_str(&format!(
                    " ⚠ 定宽比变长大 {ratio:.2}x，该表可在 schema 声明 uniform: false 退回变长布局"
                ));
            }
        }
        detail.push('）');
    }
    logs.push(detail);

    Ok(TableWork {
        build,
        fbs_text,
        stages,
        logs,
        hits: front.hits,
        misses: front.misses,
        used: front.used,
        writes: front.writes,
    })
}

/// 单语言 Bundle 计算（阶段 5）。
fn compute_bundle(
    lang: &String,
    config: &ct_domain::config::GlobalConfig,
    builds: &BTreeMap<String, TableBuild>,
    cache: &ArtifactCache,
    forced: bool,
    output_dir: &Path,
) -> Result<BundleWork, ExportError> {
    let mut front = CacheFront::new(cache, forced);
    // 借用表级字节而不是克隆：克隆一份就等于把整个 bundle 再复制一遍。
    let name_to_bytes: HashMap<String, &[u8]> = if *lang == config.primary_lang {
        builds
            .iter()
            .filter_map(|(name, build)| {
                build
                    .primary_bytes
                    .get(lang)
                    .map(|data| (name.clone(), data.as_slice()))
            })
            .collect()
    } else {
        builds
            .iter()
            .filter_map(|(name, build)| {
                build
                    .i18n_bytes
                    .get(lang)
                    .map(|data| (format!("{name}_i18n"), data.as_slice()))
            })
            .collect()
    };
    let bundle_key = serde_json::json!(name_to_bytes
        .iter()
        .map(|(k, v)| (k, sha256_hex(v)))
        .collect::<BTreeMap<_, _>>());
    let bundle = front.bytes("build_canonical_bundle", &bundle_key, || {
        Ok(build_canonical_bundle(&name_to_bytes))
    })?;
    let mut table_hashes: Vec<(String, String)> = name_to_bytes
        .iter()
        .map(|(name, data)| ((*name).clone(), sha256_hex(data)))
        .collect();
    table_hashes.sort();
    let fingerprint = ct_cache::fingerprint::bundle_fingerprint(lang, &table_hashes);
    Ok(BundleWork {
        path: output_dir.join("binary").join(format!("data_{lang}.bin")),
        bytes: bundle,
        fingerprint,
        hits: front.hits,
        misses: front.misses,
        used: front.used,
        writes: front.writes,
    })
}

/// RFC 3339（UTC 秒精度）当前时间戳。
fn rfc3339_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let (y, m, d) = civil_from_days(days);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// 线性日数→公历（Howard Hinnant 算法，与 ct-excel 读取端同源）。
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let mut y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    if m <= 2 {
        y += 1;
    }
    (y, m, d)
}

#[cfg(test)]
mod wave_budget_tests {
    use super::{pick_wave, DEFAULT_WAVE_BUDGET_MB};

    const MB: usize = 1024 * 1024;

    #[test]
    fn wave_never_exceeds_workers_or_remaining() {
        let budget = DEFAULT_WAVE_BUDGET_MB * MB;
        assert_eq!(pick_wave(50, 8, budget, MB), 8);
        assert_eq!(pick_wave(3, 8, budget, MB), 3, "只剩 3 张就不该报 8");
    }

    #[test]
    fn wave_shrinks_to_fit_budget() {
        // 每表约 20 MiB、预算 96 MiB → 一波 4 张
        assert_eq!(pick_wave(50, 8, 96 * MB, 20 * MB), 4);
        // 预算再紧也必须推进一张，否则死循环
        assert_eq!(pick_wave(50, 8, MB, 40 * MB), 1);
    }

    #[test]
    fn unknown_average_falls_back_to_one_table() {
        // 均值为 0 只可能出现在「输入也测不到」的退化情形：先算一张，绝不空转。
        // 正常首波由调用方用输入字节定价（见 input_estimate），不会走到这里。
        assert_eq!(pick_wave(50, 8, 96 * MB, 0), 1);
    }
}
