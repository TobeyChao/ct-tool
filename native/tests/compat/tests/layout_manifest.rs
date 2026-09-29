//! 布局计划与 manifest 对照（rust-native-core 任务 2.3）：
//! Rust 从 schema 重建的布局必须与 Python golden 逐列一致；
//! manifest 载荷必须与 golden JSON 语义一致。

use std::collections::HashMap;
use std::path::PathBuf;

use ct_domain::schema::{FieldDef, RecordResource, TableResource};
use ct_excel::layout::{build_layout, Column, Layout};
use ct_excel::manifest::LayoutManifest;
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

fn rust_layout() -> Layout {
    let text = std::fs::read_to_string(fixtures_dir().join("schema_v1.json")).unwrap();
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
    build_layout(&doc.table, "sha256:fixture0001", &records)
}

#[test]
fn layout_columns_match_python_golden() {
    let layout = rust_layout();
    let golden_text = std::fs::read_to_string(fixtures_dir().join("layout_v1.json")).unwrap();
    let golden: serde_json::Value = serde_json::from_str(&golden_text).unwrap();

    assert_eq!(
        layout.header_rows,
        golden["header_rows"].as_u64().unwrap() as u32
    );
    assert_eq!(layout.table_id, golden["table_id"].as_str().unwrap());

    let golden_columns: Vec<Column> = serde_json::from_value(golden["columns"].clone()).unwrap();
    for (i, (a, b)) in layout.columns.iter().zip(golden_columns.iter()).enumerate() {
        assert_eq!(a, b, "列 {} 不一致:\n  rust={a:?}\n  py  ={b:?}", i + 1);
    }
    assert_eq!(layout.columns.len(), golden_columns.len());
}

#[test]
fn header_nodes_deterministic() {
    let layout = rust_layout();
    assert!(!layout.nodes.is_empty());
    // 槽位节点（vector 组）带 # 前缀与 slot_index
    let slot = layout
        .nodes
        .iter()
        .find(|n| n.kind == "slot")
        .expect("应有 slot 节点");
    assert!(slot.display_name.starts_with('#'));
    assert!(slot.slot_index.is_some());
    // record 节点（Effect → Position）
    assert!(layout.nodes.iter().any(|n| n.kind == "record"));
    // array 节点（Rewards 展开组）
    assert!(layout.nodes.iter().any(|n| n.kind == "array"));
}

#[test]
fn manifest_payload_matches_golden() {
    let layout = rust_layout();
    let manifest = LayoutManifest::from_layout(&layout, &[]);
    let payload = manifest.payload();

    let golden_text =
        std::fs::read_to_string(fixtures_dir().join("golden").join("manifest_v1.json")).unwrap();
    let golden: serde_json::Value = serde_json::from_str(&golden_text).unwrap();
    assert_eq!(payload, golden, "manifest 载荷与 golden 不一致");
}

#[test]
fn manifest_roundtrip_and_format_gate() {
    let layout = rust_layout();
    let manifest = LayoutManifest::from_layout(&layout, &[]);
    let payload = manifest.payload();
    let parsed = LayoutManifest::parse(&payload).expect("自产 manifest 应可解析");
    assert_eq!(parsed, manifest);

    // 格式不符 → None
    let mut bad = payload.clone();
    bad["format"] = serde_json::json!("template-layout/1");
    assert!(LayoutManifest::parse(&bad).is_none());
    // 损坏 → None
    assert!(LayoutManifest::parse(&serde_json::json!("junk")).is_none());
}
