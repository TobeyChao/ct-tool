//! JSON 导出字节对照（rust-native-core 任务 3.1）。

use std::collections::HashMap;
use std::path::PathBuf;

use ct_domain::schema::{EnumItem, EnumResource, FieldDef, RecordResource, TableResource};
use ct_excel::canonical::{read_canonical_rows, rows_from_probe};
use ct_excel::layout::build_layout;
use ct_excel::reader::probe_xlsx;
use ct_export::json::serialize_table_json;
use serde::Deserialize;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/template")
}

#[derive(Deserialize)]
struct SchemaDoc {
    table: TableResource,
    records: HashMap<String, RecordSpec>,
}

#[derive(Deserialize)]
struct RecordSpec {
    fields: Vec<FieldDef>,
}

#[derive(Deserialize)]
struct EnumDoc {
    #[serde(default)]
    comment: String,
    values: Vec<EnumItem>,
}

fn load() -> (
    TableResource,
    HashMap<String, RecordResource>,
    HashMap<String, EnumResource>,
) {
    let text = std::fs::read_to_string(fixtures_dir().join("schema_v1.json")).unwrap();
    let doc: SchemaDoc = serde_json::from_str(&text).unwrap();
    let records = doc
        .records
        .into_iter()
        .map(|(name, spec)| {
            (
                name.clone(),
                RecordResource {
                    kind: "record".into(),
                    name,
                    fields: spec.fields,
                    comment: String::new(),
                },
            )
        })
        .collect();
    let enums_doc: HashMap<String, EnumDoc> =
        serde_json::from_str(&std::fs::read_to_string(fixtures_dir().join("enums.json")).unwrap())
            .unwrap();
    let enums = enums_doc
        .into_iter()
        .map(|(name, d)| {
            (
                name.clone(),
                EnumResource {
                    kind: "enum".into(),
                    name,
                    values: d.values,
                    comment: d.comment,
                },
            )
        })
        .collect();
    (doc.table, records, enums)
}

#[test]
fn json_bytes_match_python() {
    let (table, records, enums) = load();
    let layout = build_layout(&table, "sha256:fixture0001", &records);
    let report = probe_xlsx(&fixtures_dir().join("golden").join("data_v1.xlsx")).unwrap();
    let rows = rows_from_probe(&report);
    let parsed = read_canonical_rows(&layout, &table, &records, &enums, &rows);

    let text = serialize_table_json(&parsed.rows, &table);
    let golden =
        std::fs::read_to_string(fixtures_dir().join("expected").join("json_v1.txt")).unwrap();
    assert_eq!(text, golden, "JSON 输出与 golden 不一致");
}

#[test]
fn json_empty_table() {
    let (table, _r, _e) = load();
    let text = serialize_table_json(&[], &table);
    let golden =
        std::fs::read_to_string(fixtures_dir().join("expected").join("json_empty.txt")).unwrap();
    assert_eq!(text, golden);
}

#[test]
fn json_single_line_records() {
    // 单记录一行：行内不得有换行
    let (table, records, enums) = load();
    let layout = build_layout(&table, "sha256:fixture0001", &records);
    let report = probe_xlsx(&fixtures_dir().join("golden").join("data_v1.xlsx")).unwrap();
    let rows = rows_from_probe(&report);
    let parsed = read_canonical_rows(&layout, &table, &records, &enums, &rows);
    let text = serialize_table_json(&parsed.rows, &table);
    // 记录行 = 以 `{` 开始且含键值对的行（排除包装行 `{` / `]}`）
    let record_lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|l| l.starts_with('{') && l.contains("\":\""))
        .collect();
    assert!(!record_lines.is_empty());
    for line in record_lines {
        assert!(
            line.ends_with('}') || line.ends_with("},"),
            "记录行应单行收尾: {line}"
        );
    }
}
