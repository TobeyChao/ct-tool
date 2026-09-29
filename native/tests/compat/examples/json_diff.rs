use ct_domain::schema::{FieldDef, RecordResource, TableResource};
use ct_excel::canonical::{read_canonical_rows, rows_from_probe};
use ct_excel::layout::build_layout;
use ct_excel::reader::probe_xlsx;
use ct_export::json::serialize_table_json;
use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
struct SchemaDoc {
    table: TableResource,
    records: HashMap<String, RecordSpec>,
}
#[derive(Deserialize)]
struct RecordSpec {
    fields: Vec<FieldDef>,
}

fn main() {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/template");
    let doc: SchemaDoc =
        serde_json::from_str(&std::fs::read_to_string(dir.join("schema_v1.json")).unwrap())
            .unwrap();
    let records: HashMap<String, RecordResource> = doc
        .records
        .into_iter()
        .map(|(n, s)| {
            (
                n.clone(),
                RecordResource {
                    kind: "record".into(),
                    name: n,
                    fields: s.fields,
                    comment: String::new(),
                },
            )
        })
        .collect();
    let layout = build_layout(&doc.table, "sha256:fixture0001", &records);
    let report = probe_xlsx(&dir.join("golden").join("data_v1.xlsx")).unwrap();
    let rows = rows_from_probe(&report);
    let parsed = read_canonical_rows(&layout, &doc.table, &records, &HashMap::new(), &rows);
    let text = serialize_table_json(&parsed.rows, &doc.table);
    let golden = std::fs::read_to_string(dir.join("expected").join("json_v1.txt")).unwrap();
    for (i, (a, b)) in text.chars().zip(golden.chars()).enumerate() {
        if a != b {
            println!("首个差异 @ {i}: rust={a:?} py={b:?}");
            break;
        }
    }
    println!(
        "rust {} chars / py {} chars",
        text.chars().count(),
        golden.chars().count()
    );
}
