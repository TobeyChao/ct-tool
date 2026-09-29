//! Excel 读取对照（rust-native-core 任务 1.5）：
//! calamine 探针输出必须与 openpyxl（read_only+data_only）期望值逐项一致。

use std::collections::BTreeMap;
use std::path::PathBuf;

use ct_excel::reader::{probe_xlsx, serial_to_iso, ProbeValue};
use serde::Deserialize;

#[derive(Deserialize)]
struct ExpectedCell {
    row: u32,
    col: u32,
    kind: String,
    value: serde_json::Value,
}

#[derive(Deserialize)]
struct Expected {
    file: String,
    sheets: Vec<String>,
    active_sheet: String,
    epoch: String,
    cells: Vec<ExpectedCell>,
}

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/excel")
}

fn load_expected(stem: &str) -> Expected {
    let path = fixtures_dir().join("expected").join(format!("{stem}.json"));
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("读取期望值失败 {}: {e}", path.display()));
    serde_json::from_str(&text).expect("期望值 JSON 非法")
}

fn value_matches(kind: &str, expected: &serde_json::Value, actual: &ProbeValue) -> bool {
    match (kind, actual) {
        ("int" | "float", ProbeValue::Number(v)) => expected.as_f64().is_some_and(|e| e == *v),
        ("text", ProbeValue::Text(v)) => expected.as_str() == Some(v),
        ("bool", ProbeValue::Bool(v)) => expected.as_bool() == Some(*v),
        ("datetime", ProbeValue::DateTime(v)) => expected.as_str() == Some(v),
        ("error", ProbeValue::Error(v)) => expected.as_str() == Some(v),
        _ => false,
    }
}

fn check_fixture(stem: &str) {
    let expected = load_expected(stem);
    let path = fixtures_dir().join(&expected.file);
    let report = probe_xlsx(&path).unwrap_or_else(|e| panic!("探针失败 {stem}: {e}"));

    assert_eq!(report.sheets, expected.sheets, "{stem}: sheet 列表不一致");
    assert_eq!(
        report.active_sheet.as_deref(),
        Some(expected.active_sheet.as_str()),
        "{stem}: 活跃 Sheet 不一致"
    );
    assert_eq!(
        report.is_1904,
        expected.epoch == "1904",
        "{stem}: 日期系统不一致"
    );

    let actual: BTreeMap<(u32, u32), &ProbeValue> = report
        .cells
        .iter()
        .map(|c| ((c.row, c.col), &c.value))
        .collect();
    let want: BTreeMap<(u32, u32), &ExpectedCell> =
        expected.cells.iter().map(|c| ((c.row, c.col), c)).collect();

    let missing: Vec<_> = want.keys().filter(|k| !actual.contains_key(*k)).collect();
    let extra: Vec<_> = actual.keys().filter(|k| !want.contains_key(*k)).collect();
    assert!(missing.is_empty(), "{stem}: 缺少单元格 {missing:?}");
    assert!(extra.is_empty(), "{stem}: 多出单元格 {extra:?}");

    for (key, want_cell) in &want {
        let actual_value = actual[key];
        assert!(
            value_matches(&want_cell.kind, &want_cell.value, actual_value),
            "{stem}: 单元格 {key:?} 期望 {}={:?}，实际 {actual_value:?}",
            want_cell.kind,
            want_cell.value
        );
    }
}

#[test]
fn fixture_active_sheet() {
    check_fixture("active_sheet");
}

#[test]
fn fixture_dates_1900() {
    check_fixture("dates_1900");
}

#[test]
fn fixture_dates_1904() {
    check_fixture("dates_1904");
}

#[test]
fn fixture_formula_cache() {
    check_fixture("formula_cache");
}

#[test]
fn fixture_errors() {
    check_fixture("errors");
}

#[test]
fn fixture_rich_text() {
    check_fixture("rich_text");
}

#[test]
fn serial_conversion_boundaries() {
    // 1900 系以 1899-12-30 为基（openpyxl 语义；serial 1 对应 1899-12-31，
    // 不模拟 Excel 显示的 1900-01-01，serial 61 起两边一致）。
    assert_eq!(serial_to_iso(1.0, false), "1899-12-31T00:00:00");
    assert_eq!(serial_to_iso(61.0, false), "1900-03-01T00:00:00");
    // 1904 系：serial 0 = 1904-01-01。
    assert_eq!(serial_to_iso(0.0, true), "1904-01-01T00:00:00");
    // 闰日：2000-02-29。
    assert_eq!(serial_to_iso(36585.0, false), "2000-02-29T00:00:00");
}
