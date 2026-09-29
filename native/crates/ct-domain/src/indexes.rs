//! 表级 CodeName 查询索引（对应 Python `ct/schema/indexes.py`）。
//!
//! codename 索引是固定指向 `CodeName` 字段的辅助唯一查询，声明不携带
//! `field`；旧写法 `kind: code` / 已砍掉的 `group` 一律拒绝（不给兼容别名）。

use crate::schema::{QueryIndex, TableResource, CODENAME_FIELD};
use crate::types::TypeExpr;

/// 解析声明式索引列表（每种 kind 最多一条）。
pub fn parse_indexes(raw: &[serde_json::Value]) -> Result<Vec<QueryIndex>, String> {
    let mut indexes = Vec::new();
    let mut seen = false;
    for item in raw {
        let map = item
            .as_object()
            .ok_or_else(|| "indexes 条目必须是对象".to_string())?;
        let extra: Vec<&String> = map.keys().filter(|k| k.as_str() != "kind").collect();
        if !extra.is_empty() {
            // 静默忽略多余键比报错危险：写 field 的人会以为字段名是可配的
            return Err(format!(
                "indexes 条目只接受 kind 一个键，多出 {extra:?}（codename 固定指向 {CODENAME_FIELD}，不写 field）"
            ));
        }
        let kind = map.get("kind").and_then(|k| k.as_str()).unwrap_or("");
        if kind != "codename" {
            return Err("indexes 每条必须包含 kind(codename)；codename 不写 field".to_string());
        }
        if seen {
            return Err(format!("每张表最多一个 {kind} 索引"));
        }
        seen = true;
        indexes.push(QueryIndex);
    }
    Ok(indexes)
}

/// 按表结构校验索引（不扫描数据）。
pub fn validate_indexes(table: &TableResource, indexes: &[QueryIndex]) -> Result<(), String> {
    for _index in indexes {
        // 目前唯一的 kind 就是 codename
        let field = table
            .fields
            .iter()
            .find(|f| f.name == CODENAME_FIELD)
            .ok_or_else(|| {
                format!(
                    "表 {}: codename 索引要求存在名为 {CODENAME_FIELD} 的字段（type: string），\
                     当前字段列表里没有（如需删除/改名该字段，先移除 codename 索引声明）",
                    table.table
                )
            })?;
        if field.i18n {
            return Err(format!(
                "表 {}/{CODENAME_FIELD}: 索引字段不能带 i18n（查询键不能随导出语言改变）",
                table.table
            ));
        }
        if field.server_only {
            return Err(format!(
                "表 {}/{CODENAME_FIELD}: 索引字段不能是 server_only（该字段不进客户端二进制，客户端建不出索引）",
                table.table
            ));
        }
        if matches!(&field.type_expr, TypeExpr::Vector(_)) {
            return Err(format!(
                "表 {}/{CODENAME_FIELD}: 索引字段不能是 vector",
                table.table
            ));
        }
        if !matches!(&field.type_expr, TypeExpr::Scalar(s) if s == "string") {
            return Err(format!(
                "表 {}/{CODENAME_FIELD}: codename 索引要求 {CODENAME_FIELD} 是非 i18n 的 string",
                table.table
            ));
        }
    }
    Ok(())
}
