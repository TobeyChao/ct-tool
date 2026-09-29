//! FlatBuffers 二进制字节对照（rust-native-core 任务 1.7）：
//! Rust 原型输出必须与 Python canonical 生成器的 golden/*.bin 逐字节一致。

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

use ct_domain::schema::{EnumResource, RecordResource, TableResource};
use ct_export::binary::{
    build_canonical_bundle, build_canonical_table_bytes, count_vtables, BinaryBuilder,
};
use serde::Deserialize;
use serde_json::{Map, Value};

type Row = Map<String, Value>;

#[derive(Deserialize)]
struct BundleEntry {
    table: TableResource,
    rows: Vec<Row>,
}

/// records 映射的值部分（名字在键上）。
#[derive(Deserialize)]
struct RecordSpec {
    fields: Vec<ct_domain::schema::FieldDef>,
}

#[derive(Deserialize)]
struct Case {
    #[serde(default)]
    records: HashMap<String, RecordSpec>,
    #[serde(default)]
    enums: HashMap<String, Vec<String>>,
    table: TableResource,
    rows: Vec<Row>,
    #[serde(default)]
    bundle: Vec<BundleEntry>,
}

impl Case {
    fn record_map(&self) -> HashMap<String, RecordResource> {
        self.records
            .iter()
            .map(|(name, spec)| {
                (
                    name.clone(),
                    RecordResource {
                        kind: "record".to_string(),
                        name: name.clone(),
                        fields: spec.fields.clone(),
                        comment: String::new(),
                    },
                )
            })
            .collect()
    }

    fn enum_map(&self) -> HashMap<String, EnumResource> {
        self.enums
            .iter()
            .map(|(name, values)| {
                (
                    name.clone(),
                    EnumResource {
                        kind: "enum".to_string(),
                        name: name.clone(),
                        values: values
                            .iter()
                            .map(|v| ct_domain::schema::EnumItem {
                                name: v.clone(),
                                comment: String::new(),
                            })
                            .collect(),
                        comment: String::new(),
                    },
                )
            })
            .collect()
    }
}

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/binary")
}

fn load_case(stem: &str) -> Case {
    let path = fixtures_dir().join("input").join(format!("{stem}.json"));
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("读取夹具失败 {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("夹具 JSON 非法 {stem}: {e}"))
}

fn golden(stem: &str) -> Vec<u8> {
    let path = fixtures_dir().join("golden").join(format!("{stem}.bin"));
    std::fs::read(&path).unwrap_or_else(|e| panic!("读取 golden 失败 {}: {e}", path.display()))
}

fn run_case(stem: &str) -> Vec<u8> {
    let case = load_case(stem);
    let records = case.record_map();
    let enums = case.enum_map();
    let state = BinaryBuilder {
        records: &records,
        enums: &enums,
        uniform: case.table.uniform,
    };
    let bytes = build_canonical_table_bytes(&case.table, &case.rows, &state)
        .unwrap_or_else(|e| panic!("Rust 生成失败 {stem}: {e}"));

    let expected = golden(stem);
    assert_eq!(
        bytes.len(),
        expected.len(),
        "{stem}: 长度不一致 (rust={} py={})",
        bytes.len(),
        expected.len()
    );
    if bytes != expected {
        let pos = bytes
            .iter()
            .zip(expected.iter())
            .position(|(a, b)| a != b)
            .expect("长度相同但内容不同却没有首个差异点？");
        panic!(
            "{stem}: 字节差异 @ {pos}: rust={:02x?} py={:02x?}",
            &bytes[pos.saturating_sub(4)..(pos + 8).min(bytes.len())],
            &expected[pos.saturating_sub(4)..(pos + 8).min(expected.len())]
        );
    }
    bytes
}

#[test]
fn item_nonuniform_bytes_match() {
    let bytes = run_case("item_nonuniform");
    // 稀疏默认值 → 非 uniform 允许同一表出现多种 vtable
    assert!(count_vtables(&bytes) >= 1);
}

#[test]
fn item_uniform_bytes_match() {
    let bytes = run_case("item_uniform");
    assert_eq!(count_vtables(&bytes), 1, "uniform 表必须共享同一 vtable");
}

#[test]
fn empty_table_bytes_match() {
    let bytes = run_case("empty");
    assert_eq!(count_vtables(&bytes), 0);
}

#[test]
fn sparse_nonuniform_bytes_match() {
    run_case("sparse_nonuniform");
}

#[test]
fn sparse_uniform_bytes_match() {
    let bytes = run_case("sparse_uniform");
    assert_eq!(count_vtables(&bytes), 1, "uniform 表必须共享同一 vtable");
}

#[test]
fn bundle_bytes_match() {
    let case = load_case("bundle");
    let records = case.record_map();
    let enums = case.enum_map();
    let mut parts = HashMap::new();
    for entry in &case.bundle {
        let state = BinaryBuilder {
            records: &records,
            enums: &enums,
            uniform: entry.table.uniform,
        };
        let bytes = build_canonical_table_bytes(&entry.table, &entry.rows, &state)
            .expect("bundle 子表生成失败");
        parts.insert(entry.table.name().to_string(), bytes);
    }
    let bundle = build_canonical_bundle(&parts);
    assert_eq!(bundle, golden("bundle_bundle"), "bundle 字节不一致");
}

#[test]
fn rough_timing_smoke() {
    // 初步耗时对照（非正式基准）：同输入重复构建，打印供 findings 记录。
    let case = load_case("item_uniform");
    let records = case.record_map();
    let enums = case.enum_map();
    let state = BinaryBuilder {
        records: &records,
        enums: &enums,
        uniform: true,
    };
    // 预热
    for _ in 0..5 {
        let _ = build_canonical_table_bytes(&case.table, &case.rows, &state).unwrap();
    }
    let start = Instant::now();
    let rounds = 200;
    for _ in 0..rounds {
        let _ = build_canonical_table_bytes(&case.table, &case.rows, &state).unwrap();
    }
    let per_call = start.elapsed().as_secs_f64() / rounds as f64 * 1000.0;
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    eprintln!("item_uniform rust 原型: {per_call:.3} ms/次（{profile} 构建）");
}
