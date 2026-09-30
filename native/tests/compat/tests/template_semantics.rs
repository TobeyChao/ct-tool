//! Excel 模板写入与数据迁移对照（rust-native-core 任务 1.6）。
//!
//! Rust 模板通过独立 OOXML 读取器与冻结的 openpyxl 全语义逐项比较，
//! 并保留 zip 结构断言与迁移数据区 calamine 对照。

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::PathBuf;

use ct_excel::migrate::{migrate_workbook, read_data_rows};
use ct_excel::reader::probe_xlsx;
use ct_excel::template::{build_template, EnumMap, LayoutDoc};

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/template")
}

fn out_dir() -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join("template");
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn load_layout(stem: &str) -> LayoutDoc {
    let path = fixtures_dir().join(format!("{stem}.json"));
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("读取布局失败 {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap()
}

fn load_enums() -> EnumMap {
    let text = std::fs::read_to_string(fixtures_dir().join("enums.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}

fn open_archive(bytes: &[u8]) -> zip::ZipArchive<std::io::Cursor<Vec<u8>>> {
    let cursor = std::io::Cursor::new(bytes.to_vec());
    zip::ZipArchive::new(cursor).unwrap()
}

fn zip_entry(bytes: &[u8], name: &str) -> String {
    let mut archive = open_archive(bytes);
    let mut text = String::new();
    archive
        .by_name(name)
        .unwrap()
        .read_to_string(&mut text)
        .unwrap();
    text
}

fn zip_has(bytes: &[u8], name: &str) -> bool {
    open_archive(bytes).by_name(name).is_ok()
}

/// `variant` 是布局变体（v1/v2a）；读取 layout_<variant>.json，
/// 产出写入 target/，以独立 OOXML 读取器执行完整语义对照。
/// `tag` 区分调用者，避免并行测试互相覆盖同一输出文件。
fn build_and_dump(variant: &str, tag: &str) -> Vec<u8> {
    let layout = load_layout(&format!("layout_{variant}"));
    let enums = load_enums();
    let (bytes, warnings) = build_template(&layout, &enums, "Id").expect("模板生成失败");
    // LongEnum 超出 255 字符限制：跳过下拉并产生 warning
    assert_eq!(
        warnings.len(),
        1,
        "{variant}: 应有且仅有一条 255 限制 warning"
    );
    assert!(warnings[0].contains("LongEnum"));
    let path = out_dir().join(format!("template_{variant}.{tag}.rust.xlsx"));
    std::fs::write(&path, &bytes).unwrap();
    ct_test_support::xlsx_semantics::compare(
        &path,
        &fixtures_dir().join(format!("expected/template_{variant}.semantics.json")),
    )
    .unwrap();
    bytes
}

#[test]
fn independent_reader_matches_frozen_openpyxl_semantics() {
    for variant in ["v1", "v2a"] {
        ct_test_support::xlsx_semantics::compare(
            &fixtures_dir().join(format!("golden/template_{variant}.xlsx")),
            &fixtures_dir().join(format!("expected/template_{variant}.semantics.json")),
        )
        .unwrap();
    }
}

#[test]
fn full_semantics_rejects_a_changed_header() {
    let (bytes, _) = build_template(&load_layout("layout_v1"), &load_enums(), "Id").unwrap();
    let mut source = open_archive(&bytes);
    let mut writer = zip::ZipWriter::new(std::io::Cursor::new(Vec::new()));
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    for index in 0..source.len() {
        let mut file = source.by_index(index).unwrap();
        let mut content = Vec::new();
        file.read_to_end(&mut content).unwrap();
        if file.name() == "xl/sharedStrings.xml" {
            let text = String::from_utf8(content).unwrap();
            let changed = text.replace(">Id", ">BrokenId");
            assert_ne!(text, changed);
            content = changed.into_bytes();
        }
        writer.start_file(file.name(), options).unwrap();
        writer.write_all(&content).unwrap();
    }
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("changed.xlsx");
    std::fs::write(&path, writer.finish().unwrap().into_inner()).unwrap();
    let error = ct_test_support::xlsx_semantics::compare(
        &path,
        &fixtures_dir().join("expected/template_v1.semantics.json"),
    )
    .unwrap_err();
    assert!(error.to_string().contains("$.cells.2,1"), "{error}");
    assert!(error.to_string().contains("$.rich_runs.2,1"), "{error}");
}

#[test]
fn template_v1_structure() {
    let bytes = build_and_dump("v1", "structure");
    let sheet = zip_entry(&bytes, "xl/worksheets/sheet1.xml");

    // 冻结窗格：A7（6 行表头）
    assert!(sheet.contains("state=\"frozen\""), "缺少冻结窗格");
    assert!(sheet.contains("topLeftCell=\"A7\""), "冻结锚点应为 A7");
    // 19 个合并区域
    let merges = sheet.matches("<mergeCell ").count();
    assert_eq!(merges, 19, "合并区域数量不符");
    // 12 条数据验证
    let dvs = sheet.matches("<dataValidation ").count();
    assert_eq!(dvs, 12, "数据验证数量不符");
    assert!(sheet.contains("\"TRUE,FALSE\""), "bool 下拉缺失");
    assert!(
        sheet.contains(">−2147483648<") || sheet.contains(">-2147483648<"),
        "int32 范围缺失"
    );
    // 枚举 Note（comments part）
    assert!(zip_has(&bytes, "xl/comments1.xml"), "缺少批注部件");
    // 自定义属性
    let props = zip_entry(&bytes, "docProps/custom.xml");
    for key in [
        "ct_tool_version",
        "ct_table_name",
        "ct_header_rows",
        "ct_schema_hash",
        "ct_generated_at",
    ] {
        assert!(props.contains(key), "自定义属性 {key} 缺失");
    }
    // 富文本表头：run 字体在 sharedStrings 的 rPr 里（名称 Aptos 加粗 +
    // 类型 Consolas 斜体）
    let shared = zip_entry(&bytes, "xl/sharedStrings.xml");
    assert!(shared.contains("Aptos"), "缺名称字体");
    assert!(shared.contains("Consolas"), "缺类型字体");
    assert!(shared.contains("<b/>"), "缺名称加粗");
}

#[test]
fn template_v2a_structure() {
    let bytes = build_and_dump("v2a", "v2a");
    let sheet = zip_entry(&bytes, "xl/worksheets/sheet1.xml");
    assert!(sheet.contains("topLeftCell=\"A7\""));
    // v2a 多了 Weight 列 → 多一条 decimal 验证
    let dvs = sheet.matches("<dataValidation ").count();
    assert_eq!(dvs, 13, "v2a 数据验证数量不符");
}

#[test]
fn template_readback_via_calamine() {
    build_and_dump("v1", "readback");
    let path = out_dir().join("template_v1.readback.rust.xlsx");
    let report = probe_xlsx(&path).unwrap();
    assert_eq!(report.active_sheet.as_deref(), Some("Item"));
    // 富文本表头读回为拼接文本
    let id_header = report
        .cells
        .iter()
        .find(|c| c.row == 2 && c.col == 1)
        .expect("Id 表头缺失");
    match &id_header.value {
        ct_excel::reader::ProbeValue::Text(t) => {
            assert!(t.starts_with("Id"), "表头文本异常: {t}");
            assert!(t.contains("int32"));
        }
        other => panic!("表头应为文本: {other:?}"),
    }
}

#[test]
fn migration_matches_python_golden() {
    let old_layout = load_layout("layout_v1");
    let new_layout = load_layout("layout_v2a");
    let enums = load_enums();
    let old_path = fixtures_dir().join("golden").join("data_v1.xlsx");

    let (bytes, _warnings) = migrate_workbook(
        &old_path,
        &old_layout,
        &new_layout,
        true,
        &HashMap::new(),
        &enums,
        "Id",
    )
    .expect("迁移应成功");
    let rust_out = out_dir().join("migrated_v2a.rust.xlsx");
    std::fs::write(&rust_out, &bytes).unwrap();

    // 数据区对照：calamine 读 Rust 产出与 Python golden，全网格一致
    let rust_report = probe_xlsx(&rust_out).unwrap();
    let golden_report =
        probe_xlsx(&fixtures_dir().join("golden").join("migrated_v2a.xlsx")).unwrap();
    assert_eq!(
        rust_report.cells.len(),
        golden_report.cells.len(),
        "迁移结果单元格数量不一致"
    );
    for golden_cell in &golden_report.cells {
        let rust_cell = rust_report
            .cells
            .iter()
            .find(|c| c.row == golden_cell.row && c.col == golden_cell.col)
            .unwrap_or_else(|| panic!("缺少单元格 {:?}", (golden_cell.row, golden_cell.col)));
        assert_eq!(
            rust_cell.value, golden_cell.value,
            "单元格 ({},{}) 不一致",
            golden_cell.row, golden_cell.col
        );
    }
}

#[test]
fn migration_blocked_without_manifest() {
    let old_layout = load_layout("layout_v1");
    let new_layout = load_layout("layout_v2a");
    let enums = load_enums();
    let old_path = fixtures_dir().join("golden").join("data_v1.xlsx");

    let result = migrate_workbook(
        &old_path,
        &old_layout,
        &new_layout,
        false, // 无 manifest
        &HashMap::new(),
        &enums,
        "Id",
    );
    let err = result.expect_err("缺 manifest 必须拒绝");
    assert!(err.to_string().contains("无法安全迁移"), "错误信息: {err}");
    assert!(err.to_string().contains("路径清单"), "错误信息: {err}");
}

#[test]
fn migration_blocked_when_deleted_column_has_data() {
    let old_layout = load_layout("layout_v1");
    let new_layout = load_layout("layout_v2b"); // 删除了 Tags 列
    let enums = load_enums();
    let old_path = fixtures_dir().join("golden").join("data_v1.xlsx");

    // 确认 Tags 在数据里非空（夹具前提）
    let rows = read_data_rows(&old_path, old_layout.header_rows).unwrap();
    let tags_index = old_layout
        .columns
        .iter()
        .find(|c| c.stable_path.ends_with("/Tags"))
        .unwrap()
        .index;
    assert!(rows.iter().any(|(_, cells)| {
        matches!(cells.get((tags_index - 1) as usize), Some(Some(v)) if !matches!(v, ct_excel::migrate::CellValue::Text(s) if s.trim().is_empty()))
    }));

    let result = migrate_workbook(
        &old_path,
        &old_layout,
        &new_layout,
        true,
        &HashMap::new(),
        &enums,
        "Id",
    );
    let err = result.expect_err("删除列有数据必须拒绝");
    assert!(
        err.to_string().contains("被删除但存在非空数据"),
        "错误信息: {err}"
    );
}

#[test]
fn golden_input_layouts_parse() {
    // 夹具自洽：三份布局都能被 Rust 模型解析
    for stem in ["layout_v1", "layout_v2a", "layout_v2b"] {
        let layout = load_layout(stem);
        assert!(!layout.columns.is_empty());
        assert_eq!(layout.header_rows % 2, 0);
    }
}
