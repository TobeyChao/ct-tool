use ct_domain::schema::{FieldDef, RecordResource, TableResource};
use ct_excel::layout::build_layout;
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
    let text = std::fs::read_to_string(dir.join("schema_v1.json")).unwrap();
    let doc: SchemaDoc = serde_json::from_str(&text).unwrap();
    let records: HashMap<String, RecordResource> = doc
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
    let layout = build_layout(&doc.table, "sha256:fixture0001", &records);
    let golden: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("layout_v1.json")).unwrap())
            .unwrap();
    for (i, c) in layout.columns.iter().enumerate() {
        let g = &golden["columns"][i];
        let gj = serde_json::to_value(c).unwrap();
        if gj != *g {
            println!(
                "列 {} 不一致:\n  rust={}\n  py  ={}",
                i + 1,
                serde_json::to_string(&gj).unwrap(),
                serde_json::to_string(g).unwrap()
            );
        }
    }
    println!(
        "rust {} 列 / py {} 列",
        layout.columns.len(),
        golden["columns"].as_array().unwrap().len()
    );
}
