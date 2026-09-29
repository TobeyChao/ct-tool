//! 共享数据准备与校验内核（`ct/app/data_preparation.py`）：
//! 选中表 → 布局 → 读取兼容闸门 → Excel 读取 → issues + 主键集。
//!
//! 本模块不写任何文件、不合并译文、不产出产物。

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::PathBuf;

use ct_domain::diagnostics::{IssueCode, ValidationIssue};
use ct_domain::hashing::compute_schema_hash;
use ct_domain::repository::Resource;
use ct_domain::schema::{EnumResource, RecordResource, TableResource, CODENAME_FIELD};
use ct_domain::types::{NamedKind, TypeExpr};
use ct_excel::canonical::{read_canonical_rows, rows_from_probe, CanonicalParsedRows, RawValue};
use ct_excel::compat::check_reading_compatibility;
use ct_excel::layout::{build_layout, Layout};
use ct_excel::manifest::LayoutManifest;
use ct_excel::reader::probe_xlsx;

use crate::workspace::Workspace;

/// 成功读取的一张表。
pub struct PreparedTable {
    pub table: TableResource,
    pub layout: Layout,
    pub excel_path: PathBuf,
    pub parsed: CanonicalParsedRows,
    /// 仅因被引用而读取的表为 false。
    pub explicit: bool,
}

/// 内核输出。issues 顺序与逐表发现顺序一致。
#[derive(Default)]
pub struct PreparationResult {
    pub selected: Vec<TableResource>,
    pub prepared: Vec<PreparedTable>,
    pub missing_excel: Vec<PathBuf>,
    pub id_sets: HashMap<String, HashSet<i64>>,
    pub issues: Vec<ValidationIssue>,
    pub unknown_table: Option<String>,
}

/// 选中表：精确匹配（不接受逗号列表/大小写模糊）。
pub fn select_tables(workspace: &Workspace, table_filter: Option<&str>) -> Vec<TableResource> {
    workspace
        .resources
        .tables
        .iter()
        .filter(|t| table_filter.is_none_or(|f| t.table == f))
        .cloned()
        .collect()
}

/// ref 依赖闭包（不含输入表本身），按表名排序确定。
pub fn ref_dependency_tables(
    workspace: &Workspace,
    tables: &[TableResource],
) -> Vec<TableResource> {
    let by_name: HashMap<&str, &TableResource> = workspace
        .resources
        .tables
        .iter()
        .map(|t| (t.table.as_str(), t))
        .collect();
    let mut seen: HashSet<String> = tables.iter().map(|t| t.table.clone()).collect();
    let mut pending: Vec<TableResource> = tables.to_vec();
    let mut closure = Vec::new();
    while let Some(table) = pending.pop() {
        for field in &table.fields {
            let target = field
                .ref_
                .as_deref()
                .map(|r| r.split('.').next().unwrap_or(""))
                .unwrap_or("");
            if target.is_empty() || seen.contains(target) || !by_name.contains_key(target) {
                continue;
            }
            seen.insert(target.to_string());
            let dependency = by_name[target];
            closure.push(dependency.clone());
            pending.push(dependency.clone());
        }
    }
    closure.sort_by(|a, b| a.table.cmp(&b.table));
    closure
}

fn primary_issues(
    table: &TableResource,
    parsed: &CanonicalParsedRows,
    seen: &mut HashSet<i64>,
) -> Vec<ValidationIssue> {
    let mut issues = Vec::new();
    for (index, row) in parsed.rows.iter().enumerate() {
        let index = index as u32 + 1;
        let pk = row.get(&table.primary).and_then(|v| v.as_i64());
        let excel_row = parsed.excel_rows.get(index as usize - 1).copied();
        match pk {
            None => issues.push(ValidationIssue {
                table: table.table.clone(),
                code: IssueCode::Type,
                message: "主键为空".into(),
                row_index: Some(index),
                excel_row,
                column: None,
                field: table.primary.clone(),
                value: None,
            }),
            Some(pk) if seen.contains(&pk) => issues.push(ValidationIssue {
                table: table.table.clone(),
                code: IssueCode::DuplicatePk,
                message: format!("主键重复: {pk}"),
                row_index: Some(index),
                excel_row,
                column: None,
                field: table.primary.clone(),
                value: Some(serde_json::json!(pk)),
            }),
            Some(pk) => {
                seen.insert(pk);
            }
        }
    }
    issues
}

/// CodeName 索引闸门：声明了 codename 索引的表每行必须非空且唯一。
fn codename_issues(table: &TableResource, parsed: &CanonicalParsedRows) -> Vec<ValidationIssue> {
    if !table.has_codename_index() {
        return Vec::new();
    }
    let mut issues = Vec::new();
    let mut seen: HashMap<String, u32> = HashMap::new();
    for (index, row) in parsed.rows.iter().enumerate() {
        let index = index as u32 + 1;
        let excel_row = parsed.excel_rows.get(index as usize - 1).copied();
        let value = row.get(CODENAME_FIELD);
        let text = value.and_then(|v| v.as_str()).unwrap_or("");
        if text.is_empty() {
            issues.push(ValidationIssue {
                table: table.table.clone(),
                code: IssueCode::Type,
                message: format!(
                    "{CODENAME_FIELD} 为空（该表声明了 codename 索引，空值这一行永远查不到）"
                ),
                row_index: Some(index),
                excel_row,
                column: None,
                field: CODENAME_FIELD.into(),
                value: value.cloned(),
            });
        } else if let Some(first) = seen.get(text) {
            issues.push(ValidationIssue {
                table: table.table.clone(),
                code: IssueCode::DuplicateCodename,
                message: format!("{CODENAME_FIELD} 重复: {text:?}（首次出现在第 {first} 行）"),
                row_index: Some(index),
                excel_row,
                column: None,
                field: CODENAME_FIELD.into(),
                value: value.cloned(),
            });
        } else {
            seen.insert(text.to_string(), index);
        }
    }
    issues
}

/// 枚举 token 域闸门：数据 token 必须属于 Enum 当前声明值集合。
fn enum_issues(
    table: &TableResource,
    parsed: &CanonicalParsedRows,
    enums: &HashMap<String, EnumResource>,
    records: &HashMap<String, RecordResource>,
) -> Vec<ValidationIssue> {
    let slots: Vec<(&String, &TypeExpr)> = table
        .fields
        .iter()
        .filter(|f| matches!(f.type_expr, TypeExpr::Named(_) | TypeExpr::Vector(_)))
        .map(|f| (&f.name, &f.type_expr))
        .collect();
    if slots.is_empty() {
        return Vec::new();
    }
    let mut issues = Vec::new();
    for (row_index, row) in parsed.rows.iter().enumerate() {
        let row_index = row_index as u32 + 1;
        let excel_row = parsed.excel_rows.get(row_index as usize - 1).copied();
        for (field_name, type_expr) in &slots {
            for (path, enum_name, tokens) in
                enum_value_slots(type_expr, row.get(*field_name), records, vec![field_name])
            {
                let Some(enum_) = enums.get(&enum_name) else {
                    continue;
                };
                let allowed: Vec<&str> = enum_.value_names();
                for token in tokens {
                    let Some(token_text) = token.as_str() else {
                        continue;
                    };
                    if token_text.is_empty() || allowed.contains(&token_text) {
                        continue;
                    }
                    issues.push(ValidationIssue {
                        table: table.table.clone(),
                        code: IssueCode::Type,
                        message: format!(
                            "值 {token_text:?} 不在 Enum {enum_name} 的声明值中（可选：{}）",
                            allowed.join(", ")
                        ),
                        row_index: Some(row_index),
                        excel_row,
                        column: None,
                        field: path.join("."),
                        value: Some(token.clone()),
                    });
                }
            }
        }
    }
    issues
}

/// 产出值中所有 Enum 槽位： (路径, enum 名, tokens)。
fn enum_value_slots(
    type_expr: &TypeExpr,
    value: Option<&serde_json::Value>,
    records: &HashMap<String, RecordResource>,
    path: Vec<&str>,
) -> Vec<(Vec<String>, String, Vec<serde_json::Value>)> {
    let mut out = Vec::new();
    let Some(value) = value else {
        return out;
    };
    match type_expr {
        TypeExpr::Named(named) => match named.expected_kind() {
            Some(NamedKind::Enum) => {
                let tokens = match value {
                    serde_json::Value::Array(items) => items.clone(),
                    other => vec![other.clone()],
                };
                out.push((
                    path.iter().map(|s| s.to_string()).collect(),
                    named.name().to_string(),
                    tokens,
                ));
            }
            _ => {
                if let (Some(record), serde_json::Value::Object(map)) =
                    (records.get(named.name()), value)
                {
                    for field in &record.fields {
                        let mut sub_path = path.clone();
                        sub_path.push(&field.name);
                        out.extend(enum_value_slots(
                            &field.type_expr,
                            map.get(&field.name),
                            records,
                            sub_path,
                        ));
                    }
                }
            }
        },
        TypeExpr::Vector(element) => match element.as_ref() {
            TypeExpr::Named(named) if named.expected_kind() == Some(NamedKind::Enum) => {
                let tokens = match value {
                    serde_json::Value::Array(items) => items.clone(),
                    other => vec![other.clone()],
                };
                out.push((
                    path.iter().map(|s| s.to_string()).collect(),
                    named.name().to_string(),
                    tokens,
                ));
            }
            TypeExpr::Named(_named) => {
                if let serde_json::Value::Array(items) = value {
                    for (index, item) in items.iter().enumerate() {
                        let mut sub_path: Vec<&str> = path.clone();
                        // 泄漏一点生命周期换简洁：索引段只在本次调用内使用
                        let segment: &str = Box::leak(format!("[{}]", index + 1).into_boxed_str());
                        sub_path.push(segment);
                        out.extend(enum_value_slots(element, Some(item), records, sub_path));
                    }
                }
            }
            _ => {}
        },
        TypeExpr::Scalar(_) => {}
    }
    out
}

/// 跨表 ref 外键值校验。
fn ref_issues(
    table: &TableResource,
    parsed: &CanonicalParsedRows,
    id_sets: &HashMap<String, HashSet<i64>>,
) -> Vec<ValidationIssue> {
    let ref_fields: Vec<_> = table.fields.iter().filter(|f| f.ref_.is_some()).collect();
    if ref_fields.is_empty() {
        return Vec::new();
    }
    let mut issues = Vec::new();
    for (row_index, row) in parsed.rows.iter().enumerate() {
        let row_index = row_index as u32 + 1;
        let excel_row = parsed.excel_rows.get(row_index as usize - 1).copied();
        for field in &ref_fields {
            let ref_text = field.ref_.as_deref().unwrap();
            let target_table = ref_text.split('.').next().unwrap_or("");
            let target_field = ref_text.split('.').nth(1).unwrap_or("id");
            let Some(value) = row.get(&field.name) else {
                continue;
            };
            let values: Vec<&serde_json::Value> = match value {
                serde_json::Value::Array(items) => items.iter().collect(),
                other => vec![other],
            };
            let Some(target_ids) = id_sets.get(target_table) else {
                issues.push(ValidationIssue {
                    table: table.table.clone(),
                    code: IssueCode::Ref,
                    message: format!("引用表 {target_table} 的数据未加载，无法校验"),
                    row_index: Some(row_index),
                    excel_row,
                    column: None,
                    field: field.name.clone(),
                    value: Some(value.clone()),
                });
                continue;
            };
            for v in values {
                let Some(n) = v.as_i64() else {
                    continue;
                };
                if !target_ids.contains(&n) {
                    issues.push(ValidationIssue {
                        table: table.table.clone(),
                        code: IssueCode::Ref,
                        message: format!("值 {n} 在引用表 {target_table}.{target_field} 中不存在"),
                        row_index: Some(row_index),
                        excel_row,
                        column: None,
                        field: field.name.clone(),
                        value: Some(v.clone()),
                    });
                }
            }
        }
    }
    issues
}

/// 读取并校验选中的表。`excel_bytes` 为捕获的 Excel 字节（导出期）：
/// 给定后优先于磁盘读取，保证解析与发布前复核消费同一批字节。
pub fn prepare_tables(
    workspace: &Workspace,
    table_filter: Option<&str>,
    read_dependencies: bool,
    excel_bytes: Option<&std::collections::BTreeMap<PathBuf, Vec<u8>>>,
) -> PreparationResult {
    let selected = select_tables(workspace, table_filter);
    if let Some(filter) = table_filter {
        if selected.is_empty() {
            return PreparationResult {
                unknown_table: Some(filter.to_string()),
                ..Default::default()
            };
        }
    }

    let records = workspace.resources.records_map();
    let enums = workspace.resources.enums_map();
    let manifest_dir = workspace.manifest_dir();
    let explicit_names: HashSet<String> = selected.iter().map(|t| t.table.clone()).collect();
    let dependencies = if read_dependencies {
        ref_dependency_tables(workspace, &selected)
    } else {
        Vec::new()
    };
    let read_set: Vec<TableResource> = selected.iter().cloned().chain(dependencies).collect();

    let mut result = PreparationResult {
        selected,
        ..Default::default()
    };

    let dep_resources: Vec<Resource> = workspace
        .resources
        .records
        .iter()
        .cloned()
        .map(Resource::Record)
        .chain(
            workspace
                .resources
                .enums
                .iter()
                .cloned()
                .map(Resource::Enum),
        )
        .collect();

    for table in &read_set {
        let excel_path = workspace.excel_dir().join(
            table
                .excel_file
                .clone()
                .unwrap_or_else(|| format!("{}.xlsx", table.table)),
        );
        let excel_present = match excel_bytes {
            Some(map) => map.contains_key(&excel_path),
            None => excel_path.exists(),
        };
        if !excel_present {
            result.missing_excel.push(excel_path.clone());
            result.issues.push(ValidationIssue {
                table: table.table.clone(),
                code: IssueCode::Workspace,
                message: format!("Excel 文件不存在: {}", excel_path.display()),
                ..ValidationIssue::new(&table.table, IssueCode::Workspace, "")
            });
            continue;
        }
        let layout = build_layout(table, &compute_schema_hash(table, &dep_resources), &records);
        let manifest = std::fs::read_to_string(manifest_dir.join(format!("{}.json", table.table)))
            .ok()
            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
            .and_then(|value| LayoutManifest::parse(&value));
        let compatibility =
            check_reading_compatibility(&table.table, &layout, &excel_path, manifest.as_ref());
        if !compatibility.ok {
            result.issues.extend(compatibility.issues);
            continue;
        }
        let report = match match excel_bytes.and_then(|m| m.get(&excel_path)) {
            Some(bytes) => ct_excel::reader::probe_xlsx_bytes(bytes),
            None => probe_xlsx(&excel_path),
        } {
            Ok(report) => report,
            Err(e) => {
                result.issues.push(ValidationIssue::new(
                    &table.table,
                    IssueCode::Workspace,
                    format!("Excel 读取失败: {e}"),
                ));
                continue;
            }
        };
        let rows: BTreeMap<u32, Vec<RawValue>> = rows_from_probe(&report);
        let parsed = read_canonical_rows(&layout, table, &records, &enums, &rows);
        result.issues.extend(parsed.issues.iter().cloned());
        let mut seen = HashSet::new();
        result
            .issues
            .extend(primary_issues(table, &parsed, &mut seen));
        result.issues.extend(codename_issues(table, &parsed));
        result
            .issues
            .extend(enum_issues(table, &parsed, &enums, &records));
        result.id_sets.insert(table.table.clone(), seen);
        result.prepared.push(PreparedTable {
            table: table.clone(),
            layout,
            excel_path,
            parsed,
            explicit: explicit_names.contains(&table.table),
        });
    }

    // ref 外键值校验需要全部选中表的主键集，单独一轮
    for item in &result.prepared {
        result
            .issues
            .extend(ref_issues(&item.table, &item.parsed, &result.id_sets));
    }
    result
}

/// 只读校验入口：摊平为问题列表。
pub fn canonical_validate(
    workspace: &Workspace,
    table_filter: Option<&str>,
) -> Vec<ValidationIssue> {
    let result = prepare_tables(workspace, table_filter, true, None);
    if let Some(unknown) = &result.unknown_table {
        return vec![ValidationIssue::new(
            unknown,
            IssueCode::Workspace,
            format!("表 '{unknown}' 不存在"),
        )];
    }
    result.issues
}
