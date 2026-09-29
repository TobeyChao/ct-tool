//! Schema 候选/净差异/YAML-only 保存（对应 Python `app/schema_workspace/`）。
//!
//! - schemaRevision：config/global.yaml + schemas/types 目录成员的原始字节摘要；
//! - candidateHash：候选资源的规范持久化表示摘要（乐观并发守卫）；
//! - 保存仅写真实变化的 YAML：不动 Excel、翻译、产物或成功账本；
//!   无净差异时不触碰任何文件（含 journal）。
//!
//! 不识别/迁移旧 Apply 事务材料（2026-09-17 决策：不保留旧工具链兼容）。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use ct_domain::candidate::{candidate_hash, compute_candidate, merge_indexes, CandidateIssue};
use ct_domain::commands::{Command, DraftLog, DraftState};
use ct_domain::config::GlobalConfig;
use ct_domain::hashing::{python_json_dumps, resource_to_data, sha256_hex};
use ct_domain::netdiff::{compute_net_diff, NetDiff};
use ct_domain::repository::{Resource, YamlResourceRepository};
use ct_domain::schema::{EnumResource, RecordResource, TableResource};
use ct_storage::publication::{FilePublisher, PublicationError};
use ct_storage::workspace::{TransactionError, WorkspaceTransaction};

pub const SCHEMA_REVISION_FORMAT: &str = "schema-revision/1";
pub const YAML_SUFFIX: &str = ".yaml";

// ---------------------------------------------------------------------------
// Schema baseline（schemaRevision）
// ---------------------------------------------------------------------------

/// Schema 基线 revision + 各成员摘要。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchemaRevision {
    pub revision: String,
    pub config_digest: String,
    /// "schemas/<file>" / "types/<file>" → 内容 sha256
    pub members: BTreeMap<String, String>,
}

impl SchemaRevision {
    pub fn matches(&self, other: &SchemaRevision) -> bool {
        self.revision == other.revision
    }

    /// 摘要不同的成员（新增、删除、编辑都算）。
    pub fn changed_members(&self, other: &SchemaRevision) -> Vec<String> {
        let keys: std::collections::BTreeSet<&String> =
            self.members.keys().chain(other.members.keys()).collect();
        keys.into_iter()
            .filter(|key| self.members.get(*key) != other.members.get(*key))
            .cloned()
            .collect()
    }

    pub fn to_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "revision": self.revision,
            "members": self.members,
        })
    }
}

/// 一次捕获的基线字节与对应 revision（加载与摘要用同一批字节）。
pub struct SchemaSources {
    pub revision: SchemaRevision,
    pub contents: BTreeMap<PathBuf, Vec<u8>>,
}

pub fn config_file_path(root: &Path) -> PathBuf {
    root.join("config").join("global.yaml")
}

/// schemas/types 目录下全部 *.yaml 成员。
pub fn schema_yaml_paths(config: &GlobalConfig) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    for dir in [config.resolve("schemas_dir"), config.resolve("types_dir")] {
        if dir.exists() {
            let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
                .map(|entries| {
                    entries
                        .filter_map(|e| e.ok().map(|e| e.path()))
                        .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
                        .collect()
                })
                .unwrap_or_default();
            files.sort();
            paths.extend(files);
        }
    }
    paths
}

/// 读取 global.yaml 与全部 schema/type YAML（恰好一次）。
pub fn capture_schema_contents(config: &GlobalConfig) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut contents = BTreeMap::new();
    let config_file = config_file_path(&config.project_root);
    if config_file.exists() {
        if let Ok(bytes) = std::fs::read(&config_file) {
            contents.insert(config_file, bytes);
        }
    }
    for path in schema_yaml_paths(config) {
        if let Ok(bytes) = std::fs::read(&path) {
            contents.insert(path, bytes);
        }
    }
    contents
}

/// 从（已捕获的）字节计算基线 revision。
pub fn build_schema_revision(
    config: &GlobalConfig,
    contents: &BTreeMap<PathBuf, Vec<u8>>,
) -> SchemaRevision {
    let config_file = config_file_path(&config.project_root);
    let schemas_dir = config.resolve("schemas_dir");
    let types_dir = config.resolve("types_dir");
    let mut members = BTreeMap::new();
    for (path, data) in contents {
        if *path == config_file {
            continue;
        }
        let label = if path.parent() == Some(schemas_dir.as_path()) {
            "schemas"
        } else if path.parent() == Some(types_dir.as_path()) {
            "types"
        } else {
            continue;
        };
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("?");
        members.insert(format!("{label}/{name}"), sha256_hex(data));
    }
    let config_digest = contents
        .get(&config_file)
        .map(|b| sha256_hex(b))
        .unwrap_or_default();
    let payload = serde_json::json!({
        "format": SCHEMA_REVISION_FORMAT,
        "config": config_digest,
        "members": members,
    });
    let revision = sha256_hex(python_json_dumps(&payload).as_bytes());
    SchemaRevision {
        revision,
        config_digest,
        members,
    }
}

pub fn capture_schema_sources(config: &GlobalConfig) -> SchemaSources {
    let contents = capture_schema_contents(config);
    let revision = build_schema_revision(config, &contents);
    SchemaSources { revision, contents }
}

// ---------------------------------------------------------------------------
// YAML 序列化（PyYAML _IndentedDumper 风格：块序列在父键下缩进一级）
// ---------------------------------------------------------------------------

/// 确定性、便于人读 diff 的 YAML。序列项缩进到父键之下，键保持模型顺序。
pub fn dump_yaml(data: &serde_json::Value) -> String {
    let raw = serde_yaml_ng::to_string(data).expect("YAML 序列化不应失败");
    reindent_block_sequences(&raw)
}

/// serde_yaml 输出的是无缩进序列（`- ` 与父键同列）；PyYAML 的
/// `_IndentedDumper` 把序列项缩进一级。逐行重写为后者，保持仓库 YAML 风格一致。
fn reindent_block_sequences(input: &str) -> String {
    let lines: Vec<&str> = input.lines().collect();
    let indents: Vec<usize> = lines
        .iter()
        .map(|line| line.len() - line.trim_start().len())
        .collect();
    let is_dash: Vec<bool> = lines
        .iter()
        .map(|line| {
            let trimmed = line.trim_start();
            trimmed == "-" || trimmed.starts_with("- ")
        })
        .collect();
    let mut triggers: Vec<usize> = Vec::new();
    let mut out = Vec::with_capacity(lines.len());
    for (index, line) in lines.iter().enumerate() {
        let indent = indents[index];
        // 区域结束：行缩进小于触发点，或同缩进但不是序列项（即父键的下一个兄弟键）
        while triggers
            .last()
            .is_some_and(|&t| indent < t || (indent == t && !is_dash[index]))
        {
            triggers.pop();
        }
        // 序列开始：当前行是 `- ` 且上一行同缩进但不是 `- `（即父键行）
        if is_dash[index] && index > 0 && indents[index - 1] == indent && !is_dash[index - 1] {
            triggers.push(indent);
        }
        let shift = 2 * triggers.len();
        if line.trim().is_empty() || shift == 0 {
            out.push(line.to_string());
        } else {
            out.push(format!("{}{}", " ".repeat(shift), line));
        }
    }
    let mut result = out.join("\n");
    if input.ends_with('\n') {
        result.push('\n');
    }
    result
}

// ---------------------------------------------------------------------------
// YAML-only 保存计划
// ---------------------------------------------------------------------------

/// 规范化路径（文本级）：去 `.`/`..`、统一分隔符；大小写比较另行 casefold。
pub fn normalize_path(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn casefold(path: &Path) -> String {
    path.to_string_lossy().to_lowercase()
}

/// 一次保存执行的精确文件操作集。
#[derive(Debug, Clone, Default)]
pub struct YamlSavePlan {
    pub writes: BTreeMap<PathBuf, Vec<u8>>,
    pub deletes: Vec<PathBuf>,
    pub unchanged: Vec<PathBuf>,
    pub conflicts: Vec<String>,
    pub targets: BTreeMap<String, PathBuf>,
    /// 需要用户知悉但不阻断保存的事实（例如新表的目标工作簿已存在）
    pub notes: Vec<String>,
}

impl YamlSavePlan {
    pub fn is_empty(&self) -> bool {
        self.writes.is_empty() && self.deletes.is_empty()
    }

    pub fn blocked(&self) -> bool {
        !self.conflicts.is_empty()
    }

    pub fn to_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "files": self.writes.keys().map(|p| p.to_string_lossy()).collect::<Vec<_>>(),
            "deletes": self.deletes.iter().map(|p| p.to_string_lossy()).collect::<Vec<_>>(),
            "unchanged": self.unchanged.iter().map(|p| p.to_string_lossy()).collect::<Vec<_>>(),
            "conflicts": self.conflicts,
            "notes": self.notes,
        })
    }
}

#[derive(Debug, Clone, Default)]
pub struct YamlSaveResult {
    pub written: Vec<PathBuf>,
    pub deleted: Vec<PathBuf>,
    pub unchanged: Vec<PathBuf>,
}

impl YamlSaveResult {
    pub fn changed(&self) -> bool {
        !self.written.is_empty() || !self.deleted.is_empty()
    }
}

/// 资源在磁盘上的（应有）位置。
pub fn resource_target_path(
    config: &GlobalConfig,
    resource: &Resource,
    known_sources: &BTreeMap<String, PathBuf>,
) -> PathBuf {
    if let Some(known) = known_sources.get(&resource.resource_id()) {
        return known.clone();
    }
    let directory = match resource {
        Resource::Table(_) => config.resolve("schemas_dir"),
        _ => config.resolve("types_dir"),
    };
    directory.join(format!("{}{YAML_SUFFIX}", resource.name()))
}

fn excel_target(config: &GlobalConfig, table: &TableResource) -> PathBuf {
    config
        .resolve("excel_dir")
        .join(table.resolved_excel_file())
}

/// 宽松读回一个 YAML 资源（仅用于内容比较；读不出即视为不相等）。
fn load_resource_lenient(path: &Path) -> Option<Resource> {
    let text = std::fs::read_to_string(path).ok()?;
    let data: serde_json::Value = serde_yaml_ng::from_str(&text).ok()?;
    let map = data.as_object()?;
    if map.contains_key("table") {
        let table: TableResource = serde_json::from_value(data.clone()).ok()?;
        table.validate().ok()?;
        return Some(Resource::Table(table));
    }
    match map.get("kind").and_then(|k| k.as_str()) {
        Some("record") => {
            let record: RecordResource = serde_json::from_value(data.clone()).ok()?;
            record.validate().ok()?;
            Some(Resource::Record(record))
        }
        Some("enum") => {
            let enum_: EnumResource = serde_json::from_value(data.clone()).ok()?;
            enum_.validate().ok()?;
            Some(Resource::Enum(enum_))
        }
        _ => None,
    }
}

/// 文件业务内容与资源完全一致（引号/键序/显式默认值差异视为未变化）。
fn business_content_matches(path: &Path, resource: &Resource) -> bool {
    let Some(existing) = load_resource_lenient(path) else {
        return false;
    };
    resource_to_data(&existing) == resource_to_data(resource)
}

/// 构建把 `resources` 发布为新 schema 集合的文件计划。
pub fn plan_yaml_save(
    config: &GlobalConfig,
    resources: &[Resource],
    known_sources: &BTreeMap<String, PathBuf>,
) -> YamlSavePlan {
    let mut plan = YamlSavePlan::default();
    let candidate_ids: std::collections::BTreeSet<String> =
        resources.iter().map(|r| r.resource_id()).collect();
    // 目标路径 → 拥有它的基线资源（自定义来源文件名时两者可能不一致）
    let source_owner: BTreeMap<PathBuf, String> = known_sources
        .iter()
        .map(|(id, path)| (normalize_path(path), id.clone()))
        .collect();

    let mut path_owner: BTreeMap<PathBuf, String> = BTreeMap::new();
    let mut folded: BTreeMap<String, PathBuf> = BTreeMap::new();
    let mut workbook_owners: BTreeMap<String, String> = BTreeMap::new();

    for resource in resources {
        let Resource::Table(table) = resource else {
            continue;
        };
        let workbook = normalize_path(&excel_target(config, table));
        let key = casefold(&workbook);
        if let Some(previous) = workbook_owners.get(&key) {
            if *previous != resource.resource_id() {
                plan.conflicts.push(format!(
                    "多个 Table 映射到同一 Excel 路径 {}：{} / {}",
                    workbook.display(),
                    previous,
                    resource.resource_id()
                ));
            }
        }
        workbook_owners.insert(key, resource.resource_id());
    }

    let known_set: std::collections::BTreeSet<PathBuf> =
        known_sources.values().map(|p| normalize_path(p)).collect();

    for resource in resources {
        let target = normalize_path(&resource_target_path(config, resource, known_sources));
        if let Some(owner) = plan.targets.get(&resource.resource_id()) {
            if *owner != target {
                plan.conflicts.push(format!(
                    "资源 {} 有多个目标路径：{} / {}",
                    resource.resource_id(),
                    owner.display(),
                    target.display()
                ));
            }
            continue;
        }
        plan.targets.insert(resource.resource_id(), target.clone());

        let key = casefold(&target);
        if let Some(previous) = folded.get(&key) {
            if *previous != target {
                plan.conflicts.push(format!(
                    "目标路径仅大小写不同，跨平台行为不可确定：{} / {}",
                    previous.display(),
                    target.display()
                ));
            }
            continue;
        }
        folded.insert(key, target.clone());

        if let Some(claimed_by) = path_owner.get(&target) {
            if *claimed_by != resource.resource_id() {
                plan.conflicts.push(format!(
                    "多个资源映射到同一目标路径 {}：{} / {}",
                    target.display(),
                    claimed_by,
                    resource.resource_id()
                ));
            }
            continue;
        }
        path_owner.insert(target.clone(), resource.resource_id());

        if let Some(owner) = source_owner.get(&target) {
            if *owner != resource.resource_id() && candidate_ids.contains(owner) {
                // 该路径是另一个仍然存在的资源的源文件：直接写入会静默吞掉它
                plan.conflicts.push(format!(
                    "目标路径 {} 已是资源 {} 的源文件，不能再用于 {}",
                    target.display(),
                    owner,
                    resource.resource_id()
                ));
                continue;
            }
        }

        let payload = dump_yaml(&resource_to_data(resource)).into_bytes();
        let is_known_source = known_set.contains(&target);
        if let Resource::Table(table) = resource {
            if !is_known_source {
                let workbook = excel_target(config, table);
                if workbook.exists() {
                    // 保存不碰工作簿；这里只提醒，覆盖与否留给显式模板更新的无损预检
                    plan.notes.push(format!(
                        "新 Table {} 的目标工作簿已存在：{}（保存不改动它；显式更新模板时按无损预检处理）",
                        table.table,
                        workbook.display()
                    ));
                }
            }
        }
        if business_content_matches(&target, resource) {
            plan.unchanged.push(target);
            continue;
        }
        if target.exists() && !is_known_source {
            plan.conflicts.push(format!(
                "目标文件已存在且不在本次变更范围内，拒绝覆盖：{}",
                target.display()
            ));
            continue;
        }
        plan.writes.insert(target, payload);
    }

    let claimed: std::collections::BTreeSet<PathBuf> = plan.targets.values().cloned().collect();
    let mut deletes: Vec<PathBuf> = known_set
        .into_iter()
        .filter(|path| !claimed.contains(path))
        .collect();
    deletes.sort();
    plan.deletes = deletes;
    plan.unchanged.sort();
    plan
}

/// 通过共享可恢复发布器发布计划；空计划不触碰任何文件（含 journal）。
pub fn publish_yaml_save(
    root: &Path,
    plan: &YamlSavePlan,
) -> Result<YamlSaveResult, PublicationError> {
    if plan.blocked() {
        return Err(PublicationError(format!(
            "保存计划存在冲突，拒绝发布：{}",
            plan.conflicts.join("；")
        )));
    }
    if plan.is_empty() {
        return Ok(YamlSaveResult {
            unchanged: plan.unchanged.clone(),
            ..Default::default()
        });
    }
    FilePublisher::new(root).publish(&plan.writes, &plan.deletes)?;
    Ok(YamlSaveResult {
        written: plan.writes.keys().cloned().collect(),
        deleted: plan.deletes.clone(),
        unchanged: plan.unchanged.clone(),
    })
}

// ---------------------------------------------------------------------------
// 会话与保存编排
// ---------------------------------------------------------------------------

/// 保存/候选拒绝（结构化，供 worker 映射为协议错误）。
#[derive(Debug)]
pub struct SaveRejection {
    /// command / schema-revision / candidate-hash / issues / target / publication / load
    pub kind: String,
    pub message: String,
    pub details: Box<RejectionDetails>,
}

/// 拒绝的结构化详情（盒装以保持 Result 小巧）。
#[derive(Debug, Default)]
pub struct RejectionDetails {
    pub issues: Vec<CandidateIssue>,
    pub changed_members: Vec<String>,
    pub revision: Option<SchemaRevision>,
}

impl SaveRejection {
    fn new(kind: &str, message: impl Into<String>) -> Self {
        SaveRejection {
            kind: kind.to_string(),
            message: message.into(),
            details: Box::new(RejectionDetails::default()),
        }
    }

    fn with_revision(mut self, revision: SchemaRevision) -> Self {
        self.details.revision = Some(revision);
        self
    }
}

impl std::fmt::Display for SaveRejection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SaveRejection {}

/// 保存结果。
#[derive(Debug)]
pub struct SaveOutcome {
    pub is_no_op: bool,
    pub notes: Vec<String>,
    pub written: Vec<PathBuf>,
    pub deleted: Vec<PathBuf>,
    pub unchanged: Vec<PathBuf>,
    pub changed_resources: usize,
    pub net_diff: NetDiff,
    /// 保存后的新基线（客户端用它替换草稿基线）
    pub revision: SchemaRevision,
}

/// 候选响应（schema.candidate 的领域视图）。
#[derive(Debug)]
pub struct CandidateResponse {
    pub hash: String,
    pub issues: Vec<CandidateIssue>,
    pub net_diff: NetDiff,
    pub resources: Vec<Resource>,
    pub revision: SchemaRevision,
}

/// Schema 编辑会话：配置 + 捕获的基线字节 + 从同批字节加载的资源。
pub struct SchemaSession {
    pub root: PathBuf,
    pub config: GlobalConfig,
    pub revision: SchemaRevision,
    pub resources: Vec<Resource>,
    pub base_indexes: BTreeMap<String, Vec<ct_domain::schema::QueryIndex>>,
    pub known_sources: BTreeMap<String, PathBuf>,
}

impl SchemaSession {
    /// 打开工作区：revision 与实际加载的资源来自同一次字节捕获。
    pub fn open(root: &Path) -> Result<Self, SaveRejection> {
        let config = GlobalConfig::load(root).map_err(|e| SaveRejection::new("load", e))?;
        let sources = capture_schema_sources(&config);
        let contents: std::collections::HashMap<PathBuf, Vec<u8>> = sources
            .contents
            .iter()
            .map(|(p, b)| (p.clone(), b.clone()))
            .collect();
        let repo =
            YamlResourceRepository::new(config.resolve("schemas_dir"), config.resolve("types_dir"));
        let workspace = repo
            .load_captured(&contents)
            .map_err(|e| SaveRejection::new("load", e.0))?;
        let mut resources: Vec<Resource> = Vec::new();
        resources.extend(workspace.tables.iter().cloned().map(Resource::Table));
        resources.extend(workspace.records.iter().cloned().map(Resource::Record));
        resources.extend(workspace.enums.iter().cloned().map(Resource::Enum));
        let base_indexes = workspace
            .tables
            .iter()
            .map(|t| (t.resource_id(), t.indexes.clone()))
            .collect();
        let known_sources = workspace.sources.into_iter().collect();
        Ok(SchemaSession {
            root: root.to_path_buf(),
            config,
            revision: sources.revision,
            resources,
            base_indexes,
            known_sources,
        })
    }

    fn base_state(&self) -> DraftState {
        DraftState {
            resources: self.resources.clone(),
            indexes: self.base_indexes.clone(),
        }
    }

    /// 重放命令到 cursor；失败命令带序号报告。
    pub fn replay(
        &self,
        commands: &[Command],
        cursor: usize,
    ) -> Result<(DraftLog, DraftState), SaveRejection> {
        let mut log = DraftLog::new(self.base_state());
        let cursor = cursor.min(commands.len());
        for (index, command) in commands.iter().take(cursor).enumerate() {
            if let Some(payload_error) = ct_domain::commands::command_payload_error(command) {
                let mut error = SaveRejection::new("command", &payload_error.message);
                error.details.issues.push(CandidateIssue::blocker(
                    payload_error.message,
                    format!("commands[{index}].{}", payload_error.location),
                ));
                return Err(error);
            }
            log.execute(command.clone()).map_err(|e| {
                let mut error = SaveRejection::new(
                    "command",
                    format!("命令 #{index}（{}）：{e}", command.kind),
                );
                error
                    .details
                    .issues
                    .push(CandidateIssue::blocker(e, format!("commands[{index}]")));
                error
            })?;
        }
        // Keep redo history without applying/validating the inactive suffix.
        // The requested candidate is defined by the prefix at cursor.
        log.commands.extend(commands[cursor..].iter().cloned());
        log.cursor = cursor;
        let state = log
            .current()
            .map_err(|e| SaveRejection::new("command", e))?;
        Ok((log, state))
    }

    /// 计算候选（schema.candidate）：净差异不回推基线。
    pub fn candidate(
        &self,
        commands: &[Command],
        cursor: usize,
    ) -> Result<CandidateResponse, SaveRejection> {
        let (log, state) = self.replay(commands, cursor)?;
        let view = compute_candidate(&state);
        // set_indexes 只改 state.indexes；netDiff 必须比较与候选 hash 相同的合并视图，
        // 否则“只切索引”会误报 0 个资源变化并锁死保存。
        let net_diff = compute_net_diff(
            &self.base_state(),
            &DraftState {
                resources: view.resources.clone(),
                indexes: state.indexes.clone(),
            },
            &log.commands,
            Some(log.cursor),
        );
        Ok(CandidateResponse {
            hash: view.hash,
            issues: view.issues,
            net_diff,
            resources: view.resources,
            revision: self.revision.clone(),
        })
    }

    /// YAML-only 事务保存（schema.save）：双守卫 + 发布前复核。
    pub fn save(
        &self,
        expected_revision: &str,
        expected_candidate: &str,
        commands: &[Command],
        cursor: usize,
    ) -> Result<SaveOutcome, SaveRejection> {
        if expected_revision.is_empty() || expected_candidate.is_empty() {
            return Err(SaveRejection::new(
                "command",
                "保存必须提供 schemaRevision 和 candidateHash",
            ));
        }
        // 基线守卫：重新捕获（磁盘为权威），旧基线拒绝
        let current = capture_schema_sources(&self.config);
        if current.revision.revision != expected_revision {
            return Err(SaveRejection::new(
                "schema-revision",
                "Schema 基线已变化，未覆盖外部修改；草稿保留，请核对后重新加载。",
            )
            .with_revision(current.revision));
        }

        let (log, state) = self.replay(commands, cursor)?;
        let merged = merge_indexes(&state.resources, &state.indexes);
        if candidate_hash(&state.resources, &state.indexes) != expected_candidate {
            return Err(SaveRejection::new(
                "candidate-hash",
                "候选内容与服务器重建结果不一致，保存被拒绝，未写入任何文件。",
            ));
        }

        let issues = ct_domain::candidate::validate_candidate(&merged, &state.indexes);
        if !issues.is_empty() {
            let message = issues
                .iter()
                .map(|i| i.render())
                .collect::<Vec<_>>()
                .join("；");
            let mut rejection = SaveRejection::new("issues", message);
            rejection.details.issues = issues;
            return Err(rejection);
        }

        let net_diff = compute_net_diff(
            &self.base_state(),
            &DraftState {
                resources: merged.clone(),
                indexes: state.indexes.clone(),
            },
            &log.commands,
            Some(log.cursor),
        );
        let plan = plan_yaml_save(&self.config, &merged, &self.known_sources);
        if plan.blocked() {
            return Err(SaveRejection::new("target", plan.conflicts.join("；")));
        }

        // 发布前复核：加载到发布的窗口内源文件不得变化
        let recheck = capture_schema_sources(&self.config);
        if recheck.revision.revision != current.revision.revision {
            let mut rejection = SaveRejection::new(
                "schema-revision",
                "保存期间 Schema 源文件被其他进程修改，未写入任何文件。",
            );
            rejection.details.changed_members = recheck.revision.changed_members(&current.revision);
            rejection.details.revision = Some(recheck.revision);
            return Err(rejection);
        }

        // 发布前目标存在性复核：计划生成后目标不得被外部创建
        let baseline_sources: std::collections::BTreeSet<PathBuf> = self
            .known_sources
            .values()
            .map(|p| normalize_path(p))
            .collect();
        let unexpected: Vec<PathBuf> = plan
            .writes
            .keys()
            .filter(|path| !baseline_sources.contains(*path) && path.exists())
            .cloned()
            .collect();
        if !unexpected.is_empty() {
            return Err(SaveRejection::new(
                "target",
                format!(
                    "发布前发现目标文件已被其他进程创建，拒绝覆盖：{}",
                    unexpected
                        .iter()
                        .map(|p| p.display().to_string())
                        .collect::<Vec<_>>()
                        .join("、")
                ),
            ));
        }

        let result = if net_diff.is_empty() {
            // 无净差异：不触碰任何文件（含 journal）
            YamlSaveResult {
                unchanged: plan.unchanged.clone(),
                ..Default::default()
            }
        } else {
            publish_yaml_save(&self.root, &plan).map_err(|e| {
                SaveRejection::new(
                    "publication",
                    format!("保存发布失败，已恢复到保存前状态：{e}"),
                )
            })?
        };

        let fresh = capture_schema_sources(&self.config);
        Ok(SaveOutcome {
            is_no_op: !result.changed(),
            notes: plan.notes.clone(),
            written: result.written,
            deleted: result.deleted,
            unchanged: result.unchanged,
            changed_resources: net_diff.changed_resources(),
            net_diff,
            revision: fresh.revision,
        })
    }
}

/// 带工作区事务的保存入口：锁 + 中断恢复 → 加载 → 双守卫 → 发布。
/// 恢复在任何配置/资源加载之前完成；busy 与恢复失败都是结构化拒绝。
pub fn save_workspace(
    root: &Path,
    expected_revision: &str,
    expected_candidate: &str,
    commands: &[Command],
    cursor: usize,
) -> Result<(SaveOutcome, Option<String>), SaveRejection> {
    let transaction = WorkspaceTransaction::begin(root).map_err(|e| match e {
        TransactionError::Busy(busy) => SaveRejection::new("busy", busy.0),
        TransactionError::Recovery(message) => SaveRejection::new("recovery", message),
    })?;
    let session = SchemaSession::open(root)?;
    let outcome = session.save(expected_revision, expected_candidate, commands, cursor)?;
    Ok((outcome, transaction.recovery.clone()))
}
