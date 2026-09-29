//! 规范行读取对照（rust-native-core 任务 2.4）：
//! calamine 探针 + Rust 读取器的行/诊断与 openpyxl canonical 读取逐项一致。

use std::collections::HashMap;
use std::path::PathBuf;

use ct_domain::schema::{EnumItem, EnumResource, FieldDef, RecordResource, TableResource};
use ct_excel::canonical::{read_canonical_rows, rows_from_probe};
use ct_excel::layout::build_layout;
use ct_excel::reader::probe_xlsx;
use serde::Deserialize;
use serde_json::Value;

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

#[derive(Deserialize)]
struct ExpectedParsed {
    rows: Vec<Value>,
    excel_rows: Vec<u32>,
    issues: Vec<Value>,
}

fn load_schema() -> (
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
    let enums_text = std::fs::read_to_string(fixtures_dir().join("enums.json")).unwrap();
    let enums_doc: HashMap<String, EnumDoc> = serde_json::from_str(&enums_text).unwrap();
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

fn read_fixture(
    xlsx: &str,
) -> (
    Vec<Value>,
    Vec<u32>,
    Vec<ct_domain::diagnostics::ValidationIssue>,
) {
    let (table, records, enums) = load_schema();
    let layout = build_layout(&table, "sha256:fixture0001", &records);
    let report = probe_xlsx(&fixtures_dir().join("golden").join(xlsx)).unwrap();
    let rows = rows_from_probe(&report);
    let parsed = read_canonical_rows(&layout, &table, &records, &enums, &rows);
    (
        parsed.rows.into_iter().map(Value::Object).collect(),
        parsed.excel_rows,
        parsed.issues,
    )
}

#[test]
fn clean_rows_match_python() {
    let (rows, excel_rows, issues) = read_fixture("data_v1.xlsx");
    let expected: ExpectedParsed = serde_json::from_str(
        &std::fs::read_to_string(fixtures_dir().join("expected").join("parsed_v1.json")).unwrap(),
    )
    .unwrap();
    assert!(issues.is_empty(), "干净数据不应有诊断: {issues:?}");
    assert_eq!(excel_rows, expected.excel_rows);
    assert_eq!(rows, expected.rows, "行数据不一致");
}

#[test]
fn bad_rows_match_python_issues() {
    let (rows, _excel_rows, issues) = read_fixture("bad_data_v1.xlsx");
    let expected: ExpectedParsed = serde_json::from_str(
        &std::fs::read_to_string(fixtures_dir().join("expected").join("parsed_bad_v1.json"))
            .unwrap(),
    )
    .unwrap();

    let summarize =
        |issues: &[ct_domain::diagnostics::ValidationIssue]| -> Vec<(String, u32, String, String)> {
            issues
                .iter()
                .map(|i| {
                    (
                        i.code.as_str().to_string(),
                        i.excel_row.unwrap_or(0),
                        i.field.clone(),
                        i.message.clone(),
                    )
                })
                .collect()
        };
    let actual = summarize(&issues);
    let want: Vec<(String, u32, String, String)> = expected
        .issues
        .iter()
        .map(|i| {
            (
                i["code"].as_str().unwrap().to_string(),
                i["excel_row"].as_u64().unwrap_or(0) as u32,
                i["field"].as_str().unwrap().to_string(),
                i["message"].as_str().unwrap().to_string(),
            )
        })
        .collect();
    assert_eq!(actual, want, "诊断不一致");
    assert_eq!(rows.len(), expected.rows.len(), "行数不一致");
}

#[test]
fn vector_cell_grammar() {
    use ct_excel::canonical::parse_vector_cell;
    let (values, err) = parse_vector_cell("[1, 2, 3]", "int32");
    assert!(err.is_none());
    assert_eq!(
        values,
        vec![
            serde_json::json!(1),
            serde_json::json!(2),
            serde_json::json!(3)
        ]
    );

    let (_, err) = parse_vector_cell("[1,]", "int32");
    assert!(err.unwrap().contains("尾逗号"));

    let (_, err) = parse_vector_cell(r#"["a", b]"#, "string");
    assert!(err.unwrap().contains("JSON 双引号"));

    let (values, _) = parse_vector_cell(r#"["攻击+10", "中文🎮"]"#, "string");
    assert_eq!(values[1], serde_json::json!("中文🎮"));

    let (_, err) = parse_vector_cell("[128]", "int8");
    assert!(err.unwrap().contains("超出 int8 值域"));

    let (_, err) = parse_vector_cell("[Rare, Not A Token]", "ItemRarity");
    assert!(err.unwrap().contains("Enum 标识符无效"));
}
