//! 真实形状清单（bench-real-shape 任务 1.1–1.3）：把真实工作区留档冻结成
//! `native/fixtures/bench/shape-r.json`，并做只读自检。
//!
//! 形状口径：
//! - 行数来自 `ref_table_shapes.json`（运行时 dump）；
//! - 字段语法、i18n 标记与跨表引用来自 `ExcelRecord.json`（导表期类清单）；
//! - Enum 类在真实工作区是**独立表**（各带 id/codeName/designName 三列并被逐表导出），
//!   因此这里也建成表，而不是内核的 `kind: enum` 类型。
//!
//! 冻结之后夹具生成只读本清单，不再需要任何真实工作区 checkout。

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const SHAPE_SCHEMA: &str = "ct-bench-shape/1";
pub const SEED: u64 = 20260918;
pub const PRIMARY_LANG: &str = "zh";
pub const SECONDARY_LANGS: &[&str] = &["en", "ko", "tw", "th", "ja", "es", "pt", "de", "fr"];
/// 强制纳入的巨型 Config 表数量（按槽位排序）。
pub const FORCED_HUBS: usize = 12;
/// 分层抽样目标表数（按层分配后可能略有出入）。
pub const SAMPLE_TARGET: usize = 150;

/// 已建模的形状维度（自检会断言它与 `unmodelled` 不相交）。
pub const MODELLED: &[&str] = &[
    "row-count-distribution",
    "field-count-distribution",
    "enum-tables",
    "header-depth-from-nesting",
    "vector-column-expansion",
    "cross-table-refs-with-hub-preference",
    "i18n-field-placement",
];

/// 未建模 / 刻意偏离的维度（必须逐条登记在 README，且不得被自检声称覆盖）。
pub const UNMODELLED: &[&str] = &[
    "multi-area-columns",
    "multi-table-workbooks",
    "animevent-curves",
    "track-binaries",
    "translation-fill-rate",
    "i18n-per-language-aggregation",
    "vector-expansion-widths",
    "long-table-names",
    "regression-tier-tail-bias",
];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShapeManifest {
    pub schema: String,
    pub provenance: Provenance,
    pub langs: Langs,
    pub modelled: Vec<String>,
    pub unmodelled: Vec<String>,
    pub tiers: BTreeMap<String, Tier>,
    pub records: BTreeMap<String, RecordShape>,
    pub tables: BTreeMap<String, TableShape>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Provenance {
    pub shape_dump: String,
    pub record_dump: String,
    pub frozen_at: String,
    /// 两份留档各自的原始计数（用于交叉核对，不是清单的权威计数）。
    pub source_counts: BTreeMap<String, u64>,
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Langs {
    pub primary: String,
    pub secondary: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tier {
    pub seed: u64,
    pub tables: Vec<String>,
    pub totals: Totals,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct Totals {
    pub tables: u64,
    pub config_tables: u64,
    pub enum_tables: u64,
    pub rows: u64,
    pub slots: u64,
    pub i18n_fields: u64,
    /// 口径 A 的每语言条目数 = Σ(行数 × i18n 字段数)。
    pub i18n_slots: u64,
    pub vector_fields: u64,
    pub ref_edges: u64,
    pub nested_records: u64,
    pub max_header_rows: u64,
    /// 薄表（≤10 行）的 Config 表数量，用于分层抽样自检。
    pub thin_config_tables: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TableShape {
    pub class: String,
    /// 真实工作区里的原始类名（仅在改名时记录，供追溯）。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_class: Option<String>,
    pub kind: String,
    pub rows: u64,
    pub primary: String,
    pub nesting: u32,
    pub header_rows: u32,
    pub fields: Vec<FieldShape>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldShape {
    pub name: String,
    #[serde(rename = "type")]
    pub ct_type: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub i18n: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_target: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excel_columns: Option<u32>,
}

fn is_false(value: &bool) -> bool {
    !*value
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecordShape {
    pub name: String,
    pub fields: Vec<FieldShape>,
}

// ---------------------------------------------------------------- freeze

#[derive(Debug, Deserialize)]
struct DumpRow {
    table: String,
    rows: u64,
    fields: u64,
    i18n: u64,
    #[serde(default)]
    int_arr: u64,
    #[serde(default)]
    str_arr: u64,
}

/// 冻结形状清单：读两份留档，写出 `shape-r.json`。
pub fn freeze(shapes: &Path, records: &Path, out: &Path) -> Result<()> {
    let dump_text = std::fs::read_to_string(shapes)
        .with_context(|| format!("形状留档不可读：{}", shapes.display()))?;
    let dump: Vec<DumpRow> = serde_json::from_str(&dump_text).context("形状留档不是 JSON 数组")?;
    let record_text = std::fs::read_to_string(records)
        .with_context(|| format!("类清单留档不可读：{}", records.display()))?;
    let record_json: BTreeMap<String, Value> =
        serde_json::from_str(&record_text).context("类清单留档不是 JSON 对象")?;

    let mut dump_by_name: BTreeMap<String, DumpRow> = BTreeMap::new();
    let mut dump_i18n = 0u64;
    let mut dump_vector = 0u64;
    let mut dump_rows = 0u64;
    let mut dump_fields = 0u64;
    for row in dump {
        dump_rows += row.rows;
        dump_fields += row.fields;
        dump_i18n += row.i18n;
        dump_vector += row.int_arr + row.str_arr;
        dump_by_name.insert(row.table.clone(), row);
    }

    // ---- 类清单 → (类别, 字段语法)
    let mut configs: BTreeMap<String, BTreeMap<String, Value>> = BTreeMap::new();
    let mut enums: BTreeMap<String, BTreeMap<String, Value>> = BTreeMap::new();
    for (key, value) in &record_json {
        let Some(name) = value.get("KlassName").and_then(Value::as_str) else {
            continue;
        };
        let klass_type = value
            .get("KlassType")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let row: BTreeMap<String, Value> = value
            .get("Row")
            .and_then(Value::as_object)
            .map(|map| map.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
            .unwrap_or_default();
        let _ = key;
        if klass_type.starts_with("Enum") {
            enums.insert(name.to_string(), row);
        } else {
            configs.insert(name.to_string(), row);
        }
    }

    let config_names: BTreeSet<String> = configs.keys().cloned().collect();
    let enum_names: BTreeSet<String> = enums.keys().cloned().collect();

    // 内核要求 WYSIWYG PascalCase 标识符，真实工作区用 camelCase：
    // 先定表名（含去重），字段名与 ref 目标随后按同一张映射改写。
    let mut table_rename: BTreeMap<String, String> = BTreeMap::new();
    let mut used_tables: BTreeSet<String> = BTreeSet::new();
    for name in config_names.iter().chain(enum_names.iter()) {
        let mut renamed = normalize_ident(name, &mut used_tables);
        // Excel 工作表名上限 31 字符；真实工作区有 16 张更长的表名，这里截断加短哈希。
        if renamed.chars().count() > 31 {
            let hash = splitmix64(fnv1a(&renamed)) % 1_000_000;
            let prefix: String = renamed.chars().take(24).collect();
            let candidate = format!("{prefix}_{hash:06}");
            used_tables.remove(&renamed);
            renamed = if used_tables.contains(&candidate) {
                let mut index = 2;
                loop {
                    let attempt = format!("{candidate}_{index}");
                    if !used_tables.contains(&attempt) {
                        break attempt;
                    }
                    index += 1;
                }
            } else {
                candidate
            };
            used_tables.insert(renamed.clone());
        }
        table_rename.insert(name.clone(), renamed);
    }

    let mut mapper = Mapper {
        config: &config_names,
        enum_: &enum_names,
        table_rename: &table_rename,
        records: BTreeMap::new(),
        unknown_tokens: BTreeSet::new(),
    };

    let mut tables: BTreeMap<String, TableShape> = BTreeMap::new();
    for (name, grammar) in &configs {
        let rows = dump_by_name.get(name).map(|d| d.rows).unwrap_or(0);
        let mut used_fields: BTreeSet<String> = BTreeSet::new();
        let mut fields = Vec::new();
        for (field, value) in grammar {
            let mut shape = mapper.field(name, field, value);
            shape.name = normalize_ident(&shape.name, &mut used_fields);
            fields.push(shape);
        }
        let nesting = nesting_of(&fields, &mapper.records);
        let class = table_rename[name].clone();
        tables.insert(
            class.clone(),
            TableShape {
                class: class.clone(),
                source_class: (class != *name).then(|| name.clone()),
                kind: "config".to_string(),
                rows,
                primary: primary_name(&fields),
                nesting,
                header_rows: nesting * 2,
                fields,
            },
        );
    }
    for name in &enum_names {
        let rows = dump_by_name.get(name).map(|d| d.rows).unwrap_or(0);
        let mut used_fields: BTreeSet<String> = BTreeSet::new();
        let mut fields = Vec::new();
        for field in ["id", "codeName", "designName"] {
            let mut shape = FieldShape {
                name: field.to_string(),
                ct_type: if field == "id" { "int32" } else { "string" }.to_string(),
                i18n: false,
                ref_target: None,
                excel_columns: None,
            };
            shape.name = normalize_ident(&shape.name, &mut used_fields);
            fields.push(shape);
        }
        let class = table_rename[name].clone();
        tables.insert(
            class.clone(),
            TableShape {
                class: class.clone(),
                source_class: (class != *name).then(|| name.clone()),
                kind: "enum".to_string(),
                rows,
                primary: primary_name(&fields),
                nesting: 1,
                header_rows: 2,
                fields,
            },
        );
    }

    let mut record_defs = mapper.records.clone();
    dedupe_generated_names(&mut tables, &mut record_defs);
    let (tier_r, tier_full) = sample_tiers(&tables, &record_defs)?;

    let mut source_counts = BTreeMap::new();
    source_counts.insert("shape_dump_tables".into(), dump_by_name.len() as u64);
    source_counts.insert("shape_dump_rows".into(), dump_rows);
    source_counts.insert("shape_dump_fields".into(), dump_fields);
    source_counts.insert("shape_dump_i18n_fields".into(), dump_i18n);
    source_counts.insert("shape_dump_vector_fields".into(), dump_vector);
    source_counts.insert(
        "record_dump_config_classes".into(),
        config_names.len() as u64,
    );
    source_counts.insert("record_dump_enum_classes".into(), enum_names.len() as u64);

    let missing_rows = tables.values().filter(|t| t.rows == 0).count() as u64;
    let manifest = ShapeManifest {
        schema: SHAPE_SCHEMA.to_string(),
        provenance: Provenance {
            shape_dump: shape_label(shapes),
            record_dump: shape_label(records),
            frozen_at: frozen_at(),
            source_counts,
            notes: vec![
                format!(
                    "类清单口径：{} 个 Config + {} 个 Enum；形状留档只有 {} 张表的运行行数，缺行数的类按 0 行处理（{} 张）",
                    config_names.len(),
                    enum_names.len(),
                    dump_by_name.len(),
                    missing_rows
                ),
                "形状留档的 i18n 计数与类清单的 [I18N] 标记不成 1:1（同表常为 2 倍），清单以类清单的 [I18N] 为准，留档计数仅作交叉核对".to_string(),
                "Enum 类在真实工作区是独立表（各自被逐表导出），故建成表；其行数取形状留档的取值个数".to_string(),
                "向量字段的展开列宽按 {2,3,4} 确定性取值（真实逐字段宽度未进入留档）".to_string(),
            ],
        },
        langs: Langs {
            primary: PRIMARY_LANG.to_string(),
            secondary: SECONDARY_LANGS.iter().map(|s| s.to_string()).collect(),
        },
        modelled: MODELLED.iter().map(|s| s.to_string()).collect(),
        unmodelled: UNMODELLED.iter().map(|s| s.to_string()).collect(),
        tiers: BTreeMap::from([("r".to_string(), tier_r), ("r-full".to_string(), tier_full)]),
        records: record_defs,
        tables,
    };

    if !mapper.unknown_tokens.is_empty() {
        println!(
            "[shape] 未知类型标记按 string 处理（{} 种）：{}",
            mapper.unknown_tokens.len(),
            mapper
                .unknown_tokens
                .iter()
                .take(12)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        );
    }
    if let Some(parent) = out.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(out, serde_json::to_string_pretty(&manifest)? + "\n")?;
    println!(
        "[shape] 清单已写入 {}（{} 张表 / {} 个记录类型）",
        out.display(),
        manifest.tables.len(),
        manifest.records.len()
    );
    check_manifest(&manifest)?;
    Ok(())
}

fn shape_label(path: &Path) -> String {
    path.file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| path.display().to_string())
}

fn frozen_at() -> String {
    // 冻结日期来自系统时钟；清单内容的可比性不依赖它（其余字段全部确定性）。
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("unix:{secs}")
}

/// 字段语法 → 内核字段（含内联 struct 合成 Record）。
struct Mapper<'a> {
    config: &'a BTreeSet<String>,
    enum_: &'a BTreeSet<String>,
    table_rename: &'a BTreeMap<String, String>,
    records: BTreeMap<String, RecordShape>,
    unknown_tokens: BTreeSet<String>,
}

/// 内核命名：WYSIWYG PascalCase，且不能以 `_` 开头/结尾。真实工作区的类名与字段名是
/// camelCase，因此只把首字符大写；撞名时追加序号后缀。
fn normalize_ident(raw: &str, used: &mut BTreeSet<String>) -> String {
    let mut candidate: String = match raw.chars().next() {
        None => "Unnamed".to_string(),
        Some(first) => first.to_uppercase().collect::<String>() + &raw[first.len_utf8()..],
    };
    if candidate.starts_with('_') {
        candidate = format!("X{candidate}");
    }
    if candidate.ends_with('_') {
        candidate.push('X');
    }
    if !candidate
        .chars()
        .next()
        .is_some_and(|first| first.is_uppercase())
    {
        candidate = format!("X{candidate}");
    }
    let mut attempt = candidate.clone();
    let mut index = 2;
    while used.contains(&attempt) {
        attempt = format!("{candidate}{index}");
        index += 1;
    }
    used.insert(attempt.clone());
    attempt
}

/// 主键字段名：真实字段名固定是 `id`，改名后取规范化结果。
fn primary_name(fields: &[FieldShape]) -> String {
    fields
        .iter()
        .find(|f| f.name.eq_ignore_ascii_case("id"))
        .map(|f| f.name.clone())
        .unwrap_or_else(|| "Id".to_string())
}

impl Mapper<'_> {
    fn field(&mut self, table: &str, name: &str, value: &Value) -> FieldShape {
        match value {
            Value::Object(map) => {
                // 留档把「重复结构数组」写成 TYPE[N]：N 就是内核的 excel_columns 组数
                let raw_type = map
                    .get("TYPE")
                    .and_then(Value::as_str)
                    .unwrap_or(name)
                    .to_string();
                let (base, groups) = split_groups(&raw_type);
                let record = self.record_for(table, name, map, &base);
                match groups {
                    Some(groups) => FieldShape {
                        name: name.to_string(),
                        ct_type: format!("vector<{record}>"),
                        i18n: false,
                        ref_target: None,
                        excel_columns: Some(groups),
                    },
                    None => FieldShape {
                        name: name.to_string(),
                        ct_type: record,
                        i18n: false,
                        ref_target: None,
                        excel_columns: None,
                    },
                }
            }
            Value::String(raw) => self.scalar_field(table, name, raw),
            _ => FieldShape {
                name: name.to_string(),
                ct_type: "string".to_string(),
                i18n: false,
                ref_target: None,
                excel_columns: None,
            },
        }
    }

    fn scalar_field(&mut self, table: &str, name: &str, raw: &str) -> FieldShape {
        let attributes = bracket_attributes(raw);
        let i18n = attributes
            .iter()
            .any(|a| a.to_ascii_uppercase().contains("I18N"));
        let token = strip_attributes(raw);

        // 固定长向量 / 变长向量 / 列表：向量上不声明 ref（ref 只用于标量外键），
        // 元素指向表/枚举时降级为裸 int32。
        if let Some(inner) = inner_type(&token) {
            let (element, _ref_target, ref_is_record) = self.element_type(table, name, &inner);
            let width = expansion_width(table, name, &element, ref_is_record);
            let ct_type = format!("vector<{element}>");
            return FieldShape {
                name: name.to_string(),
                ct_type,
                i18n: false,
                ref_target: None,
                excel_columns: width,
            };
        }

        let (ct_type, ref_target) = self.plain_type(table, name, &token);
        FieldShape {
            name: name.to_string(),
            ct_type,
            i18n,
            ref_target,
            excel_columns: None,
        }
    }

    /// 返回 (元素类型文本, ref 目标, 元素是否是记录类型)。
    fn element_type(
        &mut self,
        _table: &str,
        _name: &str,
        token: &str,
    ) -> (String, Option<String>, bool) {
        let token = token.trim();
        if self.config.contains(token) || self.enum_.contains(token) {
            return ("int32".to_string(), Some(self.renamed(token)), false);
        }
        if self.records.contains_key(token) {
            return (token.to_string(), None, true);
        }
        (primitive_type(token, &mut self.unknown_tokens), None, false)
    }

    fn plain_type(&mut self, table: &str, name: &str, token: &str) -> (String, Option<String>) {
        let token = token.trim();
        if self.config.contains(token) || self.enum_.contains(token) {
            return ("int32".to_string(), Some(self.renamed(token)));
        }
        if self.records.contains_key(token) {
            return (token.to_string(), None);
        }
        let _ = (table, name);
        (primitive_type(token, &mut self.unknown_tokens), None)
    }

    fn renamed(&self, table: &str) -> String {
        self.table_rename
            .get(table)
            .cloned()
            .unwrap_or_else(|| table.to_string())
    }

    /// 内联 struct → 合成 Record（名称带表名前缀，保证全局唯一）。
    fn record_for(
        &mut self,
        table: &str,
        name: &str,
        map: &serde_json::Map<String, Value>,
        base_type: &str,
    ) -> String {
        let prefix = self.renamed(table);
        let type_name = if base_type.trim().is_empty() {
            name
        } else {
            base_type
        };
        let mut used_names = BTreeSet::new();
        let type_name = normalize_ident(type_name, &mut used_names);
        let mut record_name = format!("{prefix}_{type_name}");
        let mut suffix = 2;
        while self.records.contains_key(&record_name) {
            record_name = format!("{prefix}_{type_name}{suffix}");
            suffix += 1;
        }
        // 先占位，保证自引用/递归时名称稳定
        self.records.insert(
            record_name.clone(),
            RecordShape {
                name: record_name.clone(),
                fields: Vec::new(),
            },
        );
        let mut fields = Vec::new();
        let mut used_fields: BTreeSet<String> = BTreeSet::new();
        for (sub_name, sub_value) in map {
            if sub_name == "TYPE" {
                continue;
            }
            let mut shape = self.field(table, sub_name, sub_value);
            shape.name = normalize_ident(&shape.name, &mut used_fields);
            fields.push(shape);
        }
        self.records.insert(
            record_name.clone(),
            RecordShape {
                name: record_name.clone(),
                fields,
            },
        );
        record_name
    }
}

fn nesting_of(fields: &[FieldShape], records: &BTreeMap<String, RecordShape>) -> u32 {
    fn field_depth(field: &FieldShape, records: &BTreeMap<String, RecordShape>) -> u32 {
        let is_vector = field.ct_type.starts_with("vector<");
        let element = element_of(&field.ct_type);
        let element_depth = if let Some(record) = records.get(element) {
            1 + nesting_of(&record.fields, records)
        } else {
            1
        };
        match (is_vector, field.excel_columns) {
            (false, _) => element_depth,
            (true, Some(_)) => element_depth + 1,
            (true, None) => element_depth,
        }
    }
    fields
        .iter()
        .map(|f| field_depth(f, records))
        .max()
        .unwrap_or(1)
        .max(1)
}

fn element_of(ct_type: &str) -> &str {
    ct_type
        .strip_prefix("vector<")
        .and_then(|rest| rest.strip_suffix('>'))
        .unwrap_or(ct_type)
}

/// 向量展开列宽：确定性取值（真实逐字段宽度未进入留档）。
fn expansion_width(table: &str, field: &str, element: &str, is_record: bool) -> Option<u32> {
    let key = splitmix64(SEED ^ fnv1a(&format!("{table}.{field}")));
    if is_record {
        // 记录向量的真实展开是「每组一列」，按 2–3 组取值
        return Some(2 + (key % 2) as u32);
    }
    if element == "bool" {
        // 布尔向量在真实工作区是单格变长文法
        return None;
    }
    if key % 10 < 4 {
        None // 40% 保持单格变长
    } else {
        Some(2 + ((key >> 8) % 3) as u32)
    }
}

/// 拆出留档 TYPE 里的重复组数：`ItemRef[3]` → (`ItemRef`, Some(3))。
fn split_groups(raw: &str) -> (String, Option<u32>) {
    let trimmed = raw.trim();
    if let Some(open) = trimmed.rfind('[') {
        if let Some(close) = trimmed[open..].find(']') {
            let digits = &trimmed[open + 1..open + close];
            if let Ok(count) = digits.trim().parse::<u32>() {
                let base = format!("{}{}", &trimmed[..open], &trimmed[open + close + 1..]);
                if count > 0 {
                    return (base.trim().to_string(), Some(count));
                }
            }
        }
    }
    (trimmed.to_string(), None)
}

fn bracket_attributes(raw: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut rest = raw;
    while let Some(open) = rest.find('[') {
        let Some(close) = rest[open..].find(']') else {
            break;
        };
        out.push(rest[open + 1..open + close].trim().to_string());
        rest = &rest[open + close + 1..];
    }
    out
}

fn strip_attributes(raw: &str) -> String {
    let mut out = String::new();
    let mut depth = 0usize;
    for ch in raw.chars() {
        match ch {
            '[' => depth += 1,
            ']' => depth = depth.saturating_sub(1),
            _ if depth == 0 => out.push(ch),
            _ => {}
        }
    }
    out.trim().to_string()
}

fn inner_type(token: &str) -> Option<String> {
    let token = token.trim();
    for prefix in ["Array2D<", "Array1D<", "Array<", "List<"] {
        if let Some(rest) = token.strip_prefix(prefix) {
            if let Some(inner) = rest.strip_suffix('>') {
                return Some(inner.trim().to_string());
            }
        }
    }
    if let Some(inner) = token.strip_suffix("[][]") {
        return Some(inner.trim().to_string());
    }
    if let Some(inner) = token.strip_suffix("[]") {
        return Some(inner.trim().to_string());
    }
    None
}

fn primitive_type(token: &str, unknown: &mut BTreeSet<String>) -> String {
    let lowered = token.trim().to_ascii_lowercase();
    let mapped = match lowered.as_str() {
        "int" | "int32" => "int32",
        "uint" | "uint32" => "uint32",
        "long" | "int64" => "int64",
        "ulong" | "uint64" => "uint64",
        "short" | "int16" => "int16",
        "ushort" | "uint16" => "uint16",
        "sbyte" | "int8" => "int8",
        "byte" | "uint8" => "uint8",
        "string" | "str" => "string",
        "bool" | "boolean" => "bool",
        "float" | "single" => "float",
        "double" | "decimal" => "double",
        _ => {
            unknown.insert(token.trim().to_string());
            "string"
        }
    };
    mapped.to_string()
}

/// 内核要求「字段名不得与任何生成的 FlatBuffers 类型名同名」（否则 C#/FBS 生成有歧义）。
/// 真实工作区大量违反（例如 `Item` 表里有 `Item` 字段），因此这里做一次确定性改名：
/// 撞名或同表重名的字段改为 `<原名>Value[序号]`，主键指针同步跟随。
fn dedupe_generated_names(
    tables: &mut BTreeMap<String, TableShape>,
    records: &mut BTreeMap<String, RecordShape>,
) {
    let mut type_names: BTreeSet<String> = tables.keys().cloned().collect();
    type_names.extend(records.keys().cloned());

    for record in records.values_mut() {
        let mut used: BTreeSet<String> = BTreeSet::new();
        for field in &mut record.fields {
            if type_names.contains(&field.name) || used.contains(&field.name) {
                field.name = fresh_field_name(&field.name, &type_names, &used);
            }
            used.insert(field.name.clone());
        }
    }

    for table in tables.values_mut() {
        let mut used: BTreeSet<String> = BTreeSet::new();
        let primary_index = table.fields.iter().position(|f| f.name == table.primary);
        for field in &mut table.fields {
            if type_names.contains(&field.name) || used.contains(&field.name) {
                field.name = fresh_field_name(&field.name, &type_names, &used);
            }
            used.insert(field.name.clone());
        }
        if let Some(index) = primary_index {
            table.primary = table.fields[index].name.clone();
        }
    }
}

fn fresh_field_name(
    original: &str,
    type_names: &BTreeSet<String>,
    used: &BTreeSet<String>,
) -> String {
    let base = format!("{original}Value");
    let taken = |candidate: &String| type_names.contains(candidate) || used.contains(candidate);
    if !taken(&base) {
        return base;
    }
    let mut index = 2;
    loop {
        let candidate = format!("{base}{index}");
        if !taken(&candidate) {
            return candidate;
        }
        index += 1;
    }
}

// ---------------------------------------------------------------- 抽样

fn sample_tiers(
    tables: &BTreeMap<String, TableShape>,
    records: &BTreeMap<String, RecordShape>,
) -> Result<(Tier, Tier)> {
    let configs: Vec<&TableShape> = tables.values().filter(|t| t.kind == "config").collect();
    let enums: Vec<&TableShape> = tables.values().filter(|t| t.kind == "enum").collect();
    if configs.is_empty() || enums.is_empty() {
        bail!("清单里没有 Config 或 Enum 表");
    }

    let slots = |t: &TableShape| t.rows * t.fields.len() as u64;
    let mut forced: Vec<&TableShape> = configs.clone();
    forced.sort_by(|a, b| slots(b).cmp(&slots(a)).then_with(|| a.class.cmp(&b.class)));
    let forced: Vec<String> = forced
        .iter()
        .take(FORCED_HUBS)
        .map(|t| t.class.clone())
        .collect();
    let forced_set: BTreeSet<String> = forced.iter().cloned().collect();

    // 引用画像：优先选引用到强制 hub 的表，保证 hub 的入边存在
    let references_hub = |t: &TableShape| {
        t.fields.iter().any(|f| {
            f.ref_target
                .as_ref()
                .is_some_and(|target| forced_set.contains(target))
        })
    };

    let mut strata: BTreeMap<(String, String), Vec<&TableShape>> = BTreeMap::new();
    for table in &configs {
        if forced_set.contains(&table.class) {
            continue;
        }
        strata
            .entry((
                row_bucket(table.rows).to_string(),
                field_bucket(table.fields.len() as u64).to_string(),
            ))
            .or_default()
            .push(table);
    }
    let rest_total: usize = strata.values().map(Vec::len).sum();

    let mut sampled: Vec<String> = Vec::new();
    for group in strata.values_mut() {
        group.sort_by(|a, b| {
            references_hub(b)
                .cmp(&references_hub(a))
                .then_with(|| key_of(&a.class).cmp(&key_of(&b.class)))
                .then_with(|| a.class.cmp(&b.class))
        });
        let want =
            ((SAMPLE_TARGET as f64) * (group.len() as f64) / (rest_total as f64)).round() as usize;
        let want = want.clamp(1, group.len());
        sampled.extend(group.iter().take(want).map(|t| t.class.clone()));
    }

    let mut r_tables: Vec<String> = forced.clone();
    r_tables.extend(sampled);
    r_tables.extend(enums.iter().map(|t| t.class.clone()));
    r_tables.sort();
    r_tables.dedup();

    let full_tables: Vec<String> = tables.keys().cloned().collect();
    let r = Tier {
        seed: SEED,
        totals: totals_for(tables, records, &r_tables),
        tables: r_tables,
    };
    let full = Tier {
        seed: SEED,
        totals: totals_for(tables, records, &full_tables),
        tables: full_tables,
    };
    Ok((r, full))
}

fn totals_for(
    tables: &BTreeMap<String, TableShape>,
    records: &BTreeMap<String, RecordShape>,
    names: &[String],
) -> Totals {
    let mut totals = Totals::default();
    let mut used_records: BTreeSet<String> = BTreeSet::new();
    for name in names {
        let Some(table) = tables.get(name) else {
            continue;
        };
        totals.tables += 1;
        if table.kind == "enum" {
            totals.enum_tables += 1;
        } else {
            totals.config_tables += 1;
        }
        totals.rows += table.rows;
        totals.slots += table.rows * table.fields.len() as u64;
        let i18n_fields = table.fields.iter().filter(|f| f.i18n).count() as u64;
        totals.i18n_slots += table.rows * i18n_fields;
        if table.kind == "config" && table.rows <= 10 {
            totals.thin_config_tables += 1;
        }
        totals.max_header_rows = totals.max_header_rows.max(table.header_rows as u64);
        for field in &table.fields {
            if field.i18n {
                totals.i18n_fields += 1;
            }
            if field.ct_type.starts_with("vector<") {
                totals.vector_fields += 1;
            }
            if field.ref_target.is_some() {
                totals.ref_edges += 1;
            }
            let element = element_of(&field.ct_type);
            if records.contains_key(element) {
                collect_records(element, records, &mut used_records);
            }
        }
    }
    totals.nested_records = used_records.len() as u64;
    totals
}

fn collect_records(
    name: &str,
    records: &BTreeMap<String, RecordShape>,
    used: &mut BTreeSet<String>,
) {
    if !used.insert(name.to_string()) {
        return;
    }
    if let Some(record) = records.get(name) {
        for field in &record.fields {
            let element = element_of(&field.ct_type);
            if records.contains_key(element) {
                collect_records(element, records, used);
            }
        }
    }
}

fn row_bucket(rows: u64) -> &'static str {
    match rows {
        0 => "0",
        1 => "1",
        2..=10 => "2-10",
        11..=50 => "11-50",
        51..=200 => "51-200",
        201..=1000 => "201-1k",
        _ => ">1k",
    }
}

fn field_bucket(fields: u64) -> &'static str {
    match fields {
        0 => "0",
        1..=3 => "1-3",
        4..=8 => "4-8",
        9..=20 => "9-20",
        _ => "21+",
    }
}

fn key_of(name: &str) -> u64 {
    splitmix64(SEED ^ fnv1a(name))
}

fn fnv1a(text: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in text.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn splitmix64(mut state: u64) -> u64 {
    state = state.wrapping_add(0x9E3779B97F4A7C15);
    let mut z = state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

// ---------------------------------------------------------------- 自检

pub fn check(manifest_path: &Path) -> Result<()> {
    let text = std::fs::read_to_string(manifest_path)
        .with_context(|| format!("形状清单不可读：{}", manifest_path.display()))?;
    let manifest: ShapeManifest = serde_json::from_str(&text).context("形状清单不是合法 JSON")?;
    check_manifest(&manifest)
}

pub fn check_manifest(manifest: &ShapeManifest) -> Result<()> {
    if manifest.schema != SHAPE_SCHEMA {
        bail!("形状清单 schema 不匹配：{}", manifest.schema);
    }
    let modelled: BTreeSet<&String> = manifest.modelled.iter().collect();
    let unmodelled: BTreeSet<&String> = manifest.unmodelled.iter().collect();
    if !modelled.is_disjoint(&unmodelled) {
        bail!("同一维度同时被声明为已建模与未建模");
    }
    let expected_modelled: BTreeSet<String> = MODELLED.iter().map(|s| s.to_string()).collect();
    let expected_unmodelled: BTreeSet<String> = UNMODELLED.iter().map(|s| s.to_string()).collect();
    if manifest.modelled.iter().cloned().collect::<BTreeSet<_>>() != expected_modelled {
        bail!("已建模维度列表与常量不一致（不得静默增删）");
    }
    if manifest.unmodelled.iter().cloned().collect::<BTreeSet<_>>() != expected_unmodelled {
        bail!("未建模维度列表与常量不一致（不得静默增删）");
    }

    let configs = manifest
        .tables
        .values()
        .filter(|t| t.kind == "config")
        .count();
    let enums = manifest
        .tables
        .values()
        .filter(|t| t.kind == "enum")
        .count();
    let rows: u64 = manifest.tables.values().map(|t| t.rows).sum();
    for table in manifest.tables.values() {
        if !table.fields.iter().any(|f| f.name == table.primary) {
            bail!(
                "表 {} 声明的主键 {} 不在字段列表里（内核会拒绝）",
                table.class,
                table.primary
            );
        }
    }
    // 字段名不得与任何生成的类型名同名（内核硬约束）
    let mut type_names: BTreeSet<&String> = manifest.tables.keys().collect();
    type_names.extend(manifest.records.keys());
    let mut collisions = 0usize;
    for table in manifest.tables.values() {
        for field in &table.fields {
            if type_names.contains(&field.name) {
                collisions += 1;
            }
        }
    }
    for record in manifest.records.values() {
        for field in &record.fields {
            if type_names.contains(&field.name) {
                collisions += 1;
            }
        }
    }
    if collisions > 0 {
        bail!("有 {collisions} 个字段名与生成类型名同名（内核会拒绝）");
    }
    println!(
        "[shape] 清单自检：{} 张表（{configs} Config + {enums} Enum）/ {rows} 行 / {} 个记录类型",
        manifest.tables.len(),
        manifest.records.len()
    );

    // 表头深度必须来自嵌套且不止一个取值
    let mut depths: BTreeMap<u32, usize> = BTreeMap::new();
    for table in manifest.tables.values() {
        *depths.entry(table.nesting).or_default() += 1;
    }
    let dominant = depths.values().copied().max().unwrap_or(0);
    if depths.len() < 2 {
        bail!("表头深度只有一个取值（嵌套深度未被建模）");
    }
    if dominant * 100 / manifest.tables.len().max(1) > 90 {
        bail!("单一嵌套深度覆盖了 90% 以上的表，形状不成立");
    }
    println!("[shape] 嵌套深度分布（深度 → 表数）：{depths:?}");

    for (name, tier) in &manifest.tiers {
        if tier.tables.is_empty() {
            bail!("档位 {name} 为空");
        }
        let missing: Vec<&String> = tier
            .tables
            .iter()
            .filter(|t| !manifest.tables.contains_key(*t))
            .collect();
        if !missing.is_empty() {
            bail!("档位 {name} 引用了清单外的表：{missing:?}");
        }
        println!(
            "[shape] 档位 {name}：{} 表（{} Config + {} Enum）/ {} 行 / {} 槽位 / {} i18n 字段（每语言 {} 条，口径 A）/ {} 向量字段 / {} 引用边 / 薄表 {} / 最大表头 {} 行",
            tier.totals.tables,
            tier.totals.config_tables,
            tier.totals.enum_tables,
            tier.totals.rows,
            tier.totals.slots,
            tier.totals.i18n_fields,
            tier.totals.i18n_slots,
            tier.totals.vector_fields,
            tier.totals.ref_edges,
            tier.totals.thin_config_tables,
            tier.totals.max_header_rows
        );
    }

    // 分层抽样自检：薄表占比不得低于全量的 80%，且全量的每个非空分层都要被覆盖
    if let (Some(r), Some(full)) = (manifest.tiers.get("r"), manifest.tiers.get("r-full")) {
        let thin_ratio = |t: &Totals| {
            t.thin_config_tables
                .saturating_mul(1000)
                .checked_div(t.config_tables)
                .unwrap_or(0)
        };
        let (r_ratio, full_ratio) = (thin_ratio(&r.totals), thin_ratio(&full.totals));
        if r_ratio * 100 < full_ratio * 80 {
            bail!("回归档薄表占比 {r_ratio}‰ 低于全量 {full_ratio}‰ 的 80%：分层抽样走形");
        }
        println!("[shape] 薄表占比：回归档 {r_ratio}‰ vs 全量 {full_ratio}‰（阈值 80%）");

        let strata = |names: &[String]| -> BTreeSet<(String, String)> {
            names
                .iter()
                .filter_map(|name| manifest.tables.get(name))
                .filter(|table| table.kind == "config")
                .map(|table| {
                    (
                        row_bucket(table.rows).to_string(),
                        field_bucket(table.fields.len() as u64).to_string(),
                    )
                })
                .collect()
        };
        let covered = strata(&r.tables);
        let required = strata(&full.tables);
        let missing: Vec<&(String, String)> = required.difference(&covered).collect();
        if !missing.is_empty() {
            bail!("回归档未覆盖全量的非空分层：{missing:?}");
        }
        println!(
            "[shape] 分层覆盖：回归档覆盖全量 {} 个非空分层（Config 表分层）",
            required.len()
        );
    }
    println!(
        "[shape] 未建模维度（自检不对其作覆盖断言）：{}",
        manifest.unmodelled.join(", ")
    );
    Ok(())
}
