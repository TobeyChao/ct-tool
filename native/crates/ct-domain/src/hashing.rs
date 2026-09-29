//! 稳定 schema hash（`ct/schema/hashing.py`）：
//! 默认字段省略 + 键排序 + sha256，用于模板漂移检测。

use sha2::{Digest, Sha256};

use crate::repository::Resource;
use crate::schema::{FieldDef, TableResource};
use crate::types::TypeExpr;

pub const CANONICAL_SCHEMA_FORMAT_VERSION: &str = "schema-resource/1";

/// 递归按字典序排序对象键（对齐 Python `json.dumps(sort_keys=True)`；
/// workspace 启用了 serde_json preserve_order，不能依赖 Map 默认顺序）。
pub fn sort_keys(value: &serde_json::Value) -> serde_json::Value {
    match value {
        serde_json::Value::Object(map) => {
            let mut entries: Vec<(&String, &serde_json::Value)> = map.iter().collect();
            entries.sort_by(|a, b| a.0.cmp(b.0));
            let mut sorted = serde_json::Map::new();
            for (key, item) in entries {
                sorted.insert(key.clone(), sort_keys(item));
            }
            serde_json::Value::Object(sorted)
        }
        serde_json::Value::Array(items) => {
            serde_json::Value::Array(items.iter().map(sort_keys).collect())
        }
        other => other.clone(),
    }
}

/// 稳定 sha256：JSON（键排序、无空格、Unicode 原样）。
pub fn stable_sha256(data: &serde_json::Value) -> String {
    let text = serde_json::to_string(&sort_keys(data)).expect("JSON 序列化不应失败");
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    format!("{:x}", hasher.finalize())
}

/// Python `json.dumps(sort_keys=True, ensure_ascii=False)` 等价序列化
/// （默认分隔符 `", "` / `": "`），供 candidateHash / schemaRevision 等
/// 需要与 Python 逐字节一致摘要的负载使用。
pub fn python_json_dumps(data: &serde_json::Value) -> String {
    let mut out = String::new();
    write_python_json(&sort_keys(data), &mut out);
    out
}

fn write_python_json(value: &serde_json::Value, out: &mut String) {
    match value {
        serde_json::Value::Null => out.push_str("null"),
        serde_json::Value::Bool(flag) => out.push_str(if *flag { "true" } else { "false" }),
        serde_json::Value::Number(_) | serde_json::Value::String(_) => {
            out.push_str(&serde_json::to_string(value).expect("标量序列化不应失败"));
        }
        serde_json::Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push_str(", ");
                }
                write_python_json(item, out);
            }
            out.push(']');
        }
        serde_json::Value::Object(map) => {
            out.push('{');
            for (index, (key, item)) in map.iter().enumerate() {
                if index > 0 {
                    out.push_str(", ");
                }
                out.push_str(&serde_json::to_string(key).expect("键序列化不应失败"));
                out.push_str(": ");
                write_python_json(item, out);
            }
            out.push('}');
        }
    }
}

/// sha256 十六进制摘要（字节）。
pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}

pub fn field_to_data(field: &FieldDef) -> serde_json::Value {
    let mut map = serde_json::Map::new();
    map.insert("name".into(), field.name.clone().into());
    map.insert("type".into(), field.type_expr.to_text().into());
    if field.i18n {
        map.insert("i18n".into(), true.into());
    }
    if let Some(r) = &field.ref_ {
        map.insert("ref".into(), r.clone().into());
    }
    if field.server_only {
        map.insert("server_only".into(), true.into());
    }
    if !field.comment.is_empty() {
        map.insert("comment".into(), field.comment.clone().into());
    }
    if let Some(n) = field.excel_columns {
        map.insert("excel_columns".into(), n.into());
    }
    serde_json::Value::Object(map)
}

/// 资源的规范持久化表示（默认字段省略）。
pub fn resource_to_data(resource: &Resource) -> serde_json::Value {
    match resource {
        Resource::Table(t) => {
            let mut map = serde_json::Map::new();
            map.insert("table".into(), t.table.clone().into());
            map.insert("primary".into(), t.primary.clone().into());
            map.insert(
                "fields".into(),
                t.fields
                    .iter()
                    .map(field_to_data)
                    .collect::<Vec<_>>()
                    .into(),
            );
            if let Some(k) = &t.json_key {
                map.insert("json_key".into(), k.clone().into());
            }
            if let Some(f) = &t.excel_file {
                map.insert("excel_file".into(), f.clone().into());
            }
            if !t.indexes.is_empty() {
                map.insert(
                    "indexes".into(),
                    t.indexes
                        .iter()
                        .map(|_| serde_json::json!({"kind": "codename"}))
                        .collect::<Vec<_>>()
                        .into(),
                );
            }
            if !t.uniform {
                map.insert("uniform".into(), false.into());
            }
            serde_json::Value::Object(map)
        }
        Resource::Record(r) => {
            let mut map = serde_json::Map::new();
            map.insert("kind".into(), "record".into());
            map.insert("name".into(), r.name.clone().into());
            map.insert(
                "fields".into(),
                r.fields
                    .iter()
                    .map(field_to_data)
                    .collect::<Vec<_>>()
                    .into(),
            );
            if !r.comment.is_empty() {
                map.insert("comment".into(), r.comment.clone().into());
            }
            serde_json::Value::Object(map)
        }
        Resource::Enum(e) => {
            let mut map = serde_json::Map::new();
            map.insert("kind".into(), "enum".into());
            map.insert("name".into(), e.name.clone().into());
            map.insert(
                "values".into(),
                e.values
                    .iter()
                    .map(|item| {
                        if item.comment.is_empty() {
                            serde_json::json!({"name": item.name})
                        } else {
                            serde_json::json!({"name": item.name, "comment": item.comment})
                        }
                    })
                    .collect::<Vec<_>>()
                    .into(),
            );
            if !e.comment.is_empty() {
                map.insert("comment".into(), e.comment.clone().into());
            }
            serde_json::Value::Object(map)
        }
    }
}

/// 表 + 传递具名依赖的稳定 hash（跨表 ref 目标不影响模板）。
pub fn compute_schema_hash(table: &TableResource, dependencies: &[Resource]) -> String {
    let available: std::collections::HashMap<&str, &Resource> =
        dependencies.iter().map(|r| (r.name(), r)).collect();
    let mut reachable: std::collections::HashMap<String, &Resource> =
        std::collections::HashMap::new();

    fn visit<'a>(
        fields: &'a [FieldDef],
        available: &std::collections::HashMap<&'a str, &'a Resource>,
        reachable: &mut std::collections::HashMap<String, &'a Resource>,
    ) {
        for field in fields {
            let mut expr = &field.type_expr;
            if let TypeExpr::Vector(element) = expr {
                expr = element;
            }
            let TypeExpr::Named(named) = expr else {
                continue;
            };
            if reachable.contains_key(named.name()) {
                continue;
            }
            let Some(target) = available.get(named.name()) else {
                continue;
            };
            reachable.insert(named.name().to_string(), target);
            if let Resource::Record(record) = target {
                visit(&record.fields, available, reachable);
            }
        }
    }
    visit(&table.fields, &available, &mut reachable);

    let mut deps: Vec<&Resource> = reachable.values().copied().collect();
    deps.sort_by_key(|r| r.resource_id());
    let data = serde_json::json!({
        "format": CANONICAL_SCHEMA_FORMAT_VERSION,
        "table": resource_to_data(&Resource::Table(table.clone())),
        "dependencies": deps.iter().map(|r| resource_to_data(r)).collect::<Vec<_>>(),
    });
    stable_sha256(&data)[..16].to_string()
}

/// 单个资源的完整 sha256。
pub fn compute_resource_hash(resource: &Resource) -> String {
    stable_sha256(&serde_json::json!({
        "format": CANONICAL_SCHEMA_FORMAT_VERSION,
        "resource": resource_to_data(resource),
    }))
}

/// Python `json.dumps(sort_keys=True, indent=N, ensure_ascii=False)` 等价序列化
/// （带换行结尾由调用方决定；manifest 等需要与 Python 逐字节一致的格式化输出用）。
pub fn python_json_pretty(data: &serde_json::Value) -> String {
    let mut out = String::new();
    write_python_pretty(&sort_keys(data), 0, 4, &mut out);
    out
}

fn write_python_pretty(value: &serde_json::Value, level: usize, indent: usize, out: &mut String) {
    let pad = " ".repeat(level * indent);
    let child_pad = " ".repeat((level + 1) * indent);
    match value {
        serde_json::Value::Object(map) => {
            if map.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (index, (key, item)) in map.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&child_pad);
                out.push_str(&serde_json::to_string(key).expect("键序列化不应失败"));
                out.push_str(": ");
                write_python_pretty(item, level + 1, indent, out);
            }
            out.push('\n');
            out.push_str(&pad);
            out.push('}');
        }
        serde_json::Value::Array(items) => {
            if items.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                out.push('\n');
                out.push_str(&child_pad);
                write_python_pretty(item, level + 1, indent, out);
            }
            out.push('\n');
            out.push_str(&pad);
            out.push(']');
        }
        other => out.push_str(&serde_json::to_string(other).expect("标量序列化不应失败")),
    }
}
