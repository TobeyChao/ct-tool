//! C#/Lua accessor 文本对照（rust-native-core 任务 3.5/3.6）。

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

use ct_domain::schema::{EnumResource, QueryIndex, RecordResource, TableResource};
use ct_export::accessor_csharp::{generate_csharp_accessor, generate_csharp_enums};
use ct_export::accessor_lua::{generate_lua_accessor, generate_lua_enums};
use ct_export::accessor_model::build_accessor_model;
use ct_export::binary::plan_object_layout;
use serde::Deserialize;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/template")
}

#[derive(Deserialize)]
struct SchemaDoc {
    table: TableResource,
    #[serde(default)]
    records: HashMap<String, RecordSpec>,
}

#[derive(Deserialize)]
struct RecordSpec {
    fields: Vec<ct_domain::schema::FieldDef>,
}

#[derive(Deserialize)]
struct EnumDoc {
    #[serde(default)]
    comment: String,
    values: Vec<ct_domain::schema::EnumItem>,
}

fn records_pool() -> HashMap<String, RecordResource> {
    let text = std::fs::read_to_string(fixtures_dir().join("schema_v1.json")).unwrap();
    let doc: SchemaDoc = serde_json::from_str(&text).unwrap();
    doc.records
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
        .collect()
}

fn enums_pool() -> BTreeMap<String, EnumResource> {
    let text = std::fs::read_to_string(fixtures_dir().join("enums.json")).unwrap();
    let doc: HashMap<String, EnumDoc> = serde_json::from_str(&text).unwrap();
    doc.into_iter()
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
        .collect()
}

fn load_table(file: &str) -> TableResource {
    let text = std::fs::read_to_string(fixtures_dir().join(file)).unwrap();
    let doc: SchemaDoc = serde_json::from_str(&text).unwrap();
    doc.table
}

fn golden(name: &str) -> String {
    std::fs::read_to_string(fixtures_dir().join("expected").join(name)).unwrap()
}

#[test]
fn csharp_item_offsets_mode() {
    let table = load_table("schema_v1.json");
    let records = records_pool();
    let model = build_accessor_model(&table, &[QueryIndex], Some(&records), None, None, None);
    let text = generate_csharp_accessor(&model, &records);
    assert_eq!(text, golden("Item_accessor.cs.txt"), "C# 变长模式不一致");
}

#[test]
fn csharp_item_uniform_literal_mode() {
    let table = load_table("schema_v1.json");
    let records = records_pool();
    let fields: Vec<&ct_domain::schema::FieldDef> = table.client_fields().collect();
    let layout = plan_object_layout(&fields, &records).unwrap();
    let offsets: HashMap<u32, u32> = (0..fields.len())
        .map(|i| (4 + 2 * i) as u32)
        .zip(layout.offsets.iter().copied())
        .collect();
    let model = build_accessor_model(
        &table,
        &[QueryIndex],
        Some(&records),
        Some(offsets),
        None,
        None,
    );
    let text = generate_csharp_accessor(&model, &records);
    assert_eq!(
        text,
        golden("Item_accessor_uniform.cs.txt"),
        "C# 定宽模式不一致"
    );
}

#[test]
fn csharp_buff_i18n() {
    let table = load_table("schema_buff.json");
    let records = records_pool();
    let model = build_accessor_model(&table, &[], Some(&records), None, None, None);
    let text = generate_csharp_accessor(&model, &records);
    assert_eq!(text, golden("Buff_accessor.cs.txt"), "C# i18n 表不一致");
}

#[test]
fn lua_item_and_buff() {
    let records = records_pool();
    let item = load_table("schema_v1.json");
    let model = build_accessor_model(&item, &[QueryIndex], Some(&records), None, None, None);
    let text = generate_lua_accessor(&model, &records);
    assert_eq!(text, golden("Item_accessor.lua.txt"), "Lua Item 不一致");

    let buff = load_table("schema_buff.json");
    let model = build_accessor_model(&buff, &[], Some(&records), None, None, None);
    let text = generate_lua_accessor(&model, &records);
    assert_eq!(text, golden("Buff_accessor.lua.txt"), "Lua Buff 不一致");
}

#[test]
fn enum_declarations() {
    let enums = enums_pool();
    let cs = generate_csharp_enums(&enums);
    assert!(cs.contains("public enum ItemRarity : byte"));
    assert!(cs.contains("Common = 0,"));
    assert!(cs.contains("Epic = 2,"));
    let lua = generate_lua_enums(&enums);
    assert!(lua.contains("Enums.ItemRarity = {"));
    assert!(lua.contains("Epic = 2,"));
}
