//! JSON 导出（`ct/export/canonical_json.py`）：单记录一行、紧凑分隔、
//! Unicode 原样、根键为表名复数（或 json_key 覆盖）。

use ct_domain::schema::TableResource;

type Row = serde_json::Map<String, serde_json::Value>;

/// 序列化一张表的 JSON 文本（含结尾换行）。
pub fn serialize_table_json(rows: &[Row], table: &TableResource) -> String {
    let root_key = table.resolved_json_key();
    if rows.is_empty() {
        return format!("{{\"{root_key}\":[]}}\n");
    }
    let encoded: Vec<String> = rows
        .iter()
        .map(|row| serde_json::to_string(row).expect("行序列化不应失败"))
        .collect();
    format!(
        "{{\n  \"{root_key}\": [\n    {}\n  ]\n}}\n",
        encoded.join(",\n    ")
    )
}
