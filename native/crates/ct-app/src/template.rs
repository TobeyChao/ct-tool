//! 模板生成用例（`canonical_gen_template`）：
//! 布局 → 模板 + manifest；已有工作簿按 manifest 迁移，缺 manifest 拒绝覆盖。

use std::collections::{BTreeMap, HashMap};

use ct_domain::hashing::{compute_schema_hash, sha256_hex};
use ct_domain::repository::Resource;
use ct_domain::schema::SchemaError;

fn to_schema_error(e: anyhow::Error) -> SchemaError {
    SchemaError(e.to_string())
}
use ct_excel::layout::build_layout;
use ct_excel::manifest::LayoutManifest;
use ct_excel::migrate::migrate_workbook;
use ct_excel::template::{build_template, EnumDoc, EnumItemDoc, EnumMap};
use ct_export::binary::plan_object_layout;

use crate::workspace::Workspace;

fn enum_map(ws: &Workspace) -> EnumMap {
    ws.resources
        .enums
        .iter()
        .map(|e| {
            (
                e.name.clone(),
                EnumDoc {
                    comment: e.comment.clone(),
                    values: e
                        .values
                        .iter()
                        .map(|v| EnumItemDoc {
                            name: v.name.clone(),
                            comment: v.comment.clone(),
                        })
                        .collect(),
                },
            )
        })
        .collect()
}

/// 定宽表的 slot_offsets（与导出路径同源：schema 推导，不需要数据）。
fn slot_offsets(ws: &Workspace, table: &ct_domain::schema::TableResource) -> Vec<(u32, u32)> {
    if !table.uniform {
        return Vec::new();
    }
    let records = ws.resources.records_map();
    let fields: Vec<_> = table.client_fields().collect();
    let Ok(layout) = plan_object_layout(&fields, &records) else {
        return Vec::new();
    };
    (0..fields.len())
        .map(|i| (4 + 2 * i) as u32)
        .zip(layout.offsets.iter().copied())
        .collect()
}

/// 生成模板（含迁移）。返回逐表消息与 warning。
pub fn gen_template(
    ws: &Workspace,
    table_filter: Option<&str>,
    all_tables: bool,
) -> Result<Vec<String>, SchemaError> {
    if table_filter.is_none() && !all_tables {
        return Err(SchemaError("请指定 --all 或 --table <表名>".into()));
    }
    if let Some(name) = table_filter {
        if !ws.resources.tables.iter().any(|t| t.table == name) {
            return Err(SchemaError(format!("表 '{name}' 不存在")));
        }
    }
    let records = ws.resources.records_map();
    let dep_resources: Vec<Resource> = ws
        .resources
        .records
        .iter()
        .cloned()
        .map(Resource::Record)
        .chain(ws.resources.enums.iter().cloned().map(Resource::Enum))
        .collect();
    let enums = enum_map(ws);
    let excel_dir = ws.excel_dir();
    std::fs::create_dir_all(&excel_dir).map_err(|e| SchemaError(format!("创建目录失败: {e}")))?;
    let manifest_dir = excel_dir.join("layout_manifests");

    let mut messages = Vec::new();
    let mut writes = std::collections::BTreeMap::new();
    let mut excel_hashes = BTreeMap::new();
    for table in &ws.resources.tables {
        if table_filter.is_some_and(|f| f != table.table) {
            continue;
        }
        let schema_hash = compute_schema_hash(table, &dep_resources);
        let layout = build_layout(table, &schema_hash, &records);
        let out_path = excel_dir.join(table.resolved_excel_file());
        let old_manifest =
            std::fs::read_to_string(manifest_dir.join(format!("{}.json", table.table)))
                .ok()
                .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
                .and_then(|value| LayoutManifest::parse(&value));

        if out_path.exists() && old_manifest.is_none() {
            return Err(SchemaError(format!(
                "{} 的 Excel 缺少布局 manifest，无法安全迁移；请先备份后删除旧文件，再重新生成空模板",
                table.table
            )));
        }

        // 模板/迁移 warning 必须透出（对齐 Python `warnings.warn`）：
        // 例如超长枚举下拉被跳过时用户需要知道。
        let warnings;
        if let Some(old_manifest) = old_manifest.filter(|_| out_path.exists()) {
            let old_layout = old_manifest.to_layout(&table.resource_id());
            let (bytes, migrate_warnings) = migrate_workbook(
                &out_path,
                &old_layout,
                &layout,
                true,
                &HashMap::new(),
                &enums,
                &table.primary,
            )
            .map_err(to_schema_error)?;
            warnings = migrate_warnings;
            excel_hashes.insert(table.table.clone(), sha256_hex(&bytes));
            writes.insert(out_path.clone(), bytes);
        } else {
            let (bytes, build_warnings) =
                build_template(&layout, &enums, &table.primary).map_err(to_schema_error)?;
            warnings = build_warnings;
            excel_hashes.insert(table.table.clone(), sha256_hex(&bytes));
            writes.insert(out_path.clone(), bytes);
        }
        messages.extend(warnings);

        let manifest = LayoutManifest::from_layout(&layout, &slot_offsets(ws, table));
        let text = ct_domain::hashing::python_json_pretty(&manifest.payload()) + "\n";
        writes.insert(
            manifest_dir.join(format!("{}.json", table.table)),
            text.into_bytes(),
        );
        messages.push(format!("模板已生成: {}", table.table));
    }
    if !excel_hashes.is_empty() {
        let cache_dir = ws.config.resolve("cache_dir");
        let state = ct_cache::state::load_state(&cache_dir).unwrap_or_default();
        let state = ct_cache::state::record_excel_hashes(state, &excel_hashes);
        writes.insert(
            cache_dir.join("state.json"),
            ct_cache::state::state_bytes(&state).map_err(SchemaError)?,
        );
    }
    ct_storage::publication::FilePublisher::new(&ws.root)
        .publish(&writes, &[])
        .map_err(|e| SchemaError(e.to_string()))?;
    Ok(messages)
}
