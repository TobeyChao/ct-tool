//! resources.list：资源清单（名称/类别/来源路径/excel_file/json_key）。

use std::path::Path;

use ct_app::workspace::Workspace;
use ct_domain::hashing::field_to_data;
use ct_protocol::dto::resources::{ResourceEntry, ResourceKind, ResourcesListResult};
use ct_protocol::error::ErrorCode;

use crate::dispatcher::{Failure, HandlerResult};
use crate::session::Session;

/// 索引 kind 列表：复用领域类型的序列化词汇，界面据此回显已声明的索引。
fn index_kinds(table: &ct_domain::schema::TableResource) -> Vec<String> {
    table
        .indexes
        .iter()
        .filter_map(|idx| serde_json::to_value(idx).ok())
        .filter_map(|v| v.as_str().map(str::to_string))
        .collect()
}

fn relative(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

pub fn list(session: &mut Session, root: &Path) -> HandlerResult {
    let workspace = Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    let mut resources = Vec::new();
    for table in &workspace.resources.tables {
        let source = workspace
            .resources
            .sources
            .get(&table.resource_id())
            .cloned()
            .unwrap_or_default();
        resources.push(ResourceEntry {
            name: table.table.clone(),
            kind: ResourceKind::Table,
            source_path: relative(root, &source),
            excel_file: Some(table.resolved_excel_file()),
            indexes: index_kinds(table),
            json_key: Some(table.resolved_json_key()),
            fields: Some(table.fields.iter().map(field_to_data).collect()),
            values: None,
            primary: Some(table.primary.clone()),
        });
    }
    for record in &workspace.resources.records {
        let source = workspace
            .resources
            .sources
            .get(&record.resource_id())
            .cloned()
            .unwrap_or_default();
        resources.push(ResourceEntry {
            name: record.name.clone(),
            kind: ResourceKind::Record,
            source_path: relative(root, &source),
            excel_file: None,
            indexes: Vec::new(),
            json_key: None,
            fields: Some(record.fields.iter().map(field_to_data).collect()),
            values: None,
            primary: None,
        });
    }
    for enum_ in &workspace.resources.enums {
        let source = workspace
            .resources
            .sources
            .get(&enum_.resource_id())
            .cloned()
            .unwrap_or_default();
        resources.push(ResourceEntry {
            name: enum_.name.clone(),
            kind: ResourceKind::Enum,
            source_path: relative(root, &source),
            excel_file: None,
            indexes: Vec::new(),
            json_key: None,
            fields: None,
            // 成员统一给 {name, comment} 形态：顺序即 ordinal，界面不猜。
            values: Some(
                enum_
                    .values
                    .iter()
                    .map(|item| serde_json::json!({"name": item.name, "comment": item.comment}))
                    .collect(),
            ),
            primary: None,
        });
    }
    // 编辑器需要同一份清单里就能拿到 schema 基线：否则客户端无法构造 candidate 守卫。
    let schema_revision = ct_app::schema::SchemaSession::open(root)
        .map(|session| session.revision.revision)
        .unwrap_or_default();
    let result = ResourcesListResult {
        revision: session.snapshot_revision,
        resources,
        schema_revision,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
