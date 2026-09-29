//! 模板生成用例对照（rust-native-core 任务 3.9）：
//! 空模板生成、manifest 落盘、有 manifest 的数据迁移、缺 manifest 拒绝覆盖。

use std::collections::HashMap;
use std::path::Path;

use ct_app::template::gen_template;
use ct_app::workspace::Workspace;
use ct_excel::reader::probe_xlsx;

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content).unwrap();
}

fn setup() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("config/global.yaml"), "primary_lang: zh\n");
    write(
        &root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n",
    );
    write(
        &root.join("config/schemas/buff.yaml"),
        "table: Buff\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n",
    );
    dir
}

#[test]
fn fresh_template_and_manifest() {
    let dir = setup();
    let ws = Workspace::open(dir.path()).unwrap();
    let messages = gen_template(&ws, Some("Item"), false).unwrap();
    assert_eq!(messages, vec!["模板已生成: Item"]);
    // 模板可读、表头正确
    let report = probe_xlsx(&dir.path().join("excel/Item.xlsx")).unwrap();
    assert_eq!(report.active_sheet.as_deref(), Some("Item"));
    assert!(report.cells.iter().any(|c| c.row == 2
        && c.col == 1
        && matches!(&c.value, ct_excel::reader::ProbeValue::Text(t) if t.starts_with("Id"))));
    // manifest 落盘且可解析
    let manifest_text =
        std::fs::read_to_string(dir.path().join("excel/layout_manifests/Item.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&manifest_text).unwrap();
    let manifest = ct_excel::manifest::LayoutManifest::parse(&value).unwrap();
    assert_eq!(manifest.header_rows, 2);
    assert_eq!(manifest.columns.len(), 2);
    // 定宽表带 slot_offsets
    assert!(!manifest.slot_offsets.is_empty());
}

#[test]
fn missing_manifest_refuses_overwrite() {
    let dir = setup();
    // 手写一个无 manifest 的旧工作簿
    let mut workbook = rust_xlsxwriter::Workbook::new();
    workbook
        .add_worksheet()
        .write_string(0, 0, "旧数据")
        .unwrap();
    std::fs::create_dir_all(dir.path().join("excel")).unwrap();
    std::fs::write(
        dir.path().join("excel/Item.xlsx"),
        workbook.save_to_buffer().unwrap(),
    )
    .unwrap();
    let before = std::fs::read(dir.path().join("excel/Item.xlsx")).unwrap();

    let ws = Workspace::open(dir.path()).unwrap();
    let err = gen_template(&ws, Some("Item"), false).unwrap_err();
    assert!(err.0.contains("缺少布局 manifest"), "{err}");
    // 原文件不变
    let after = std::fs::read(dir.path().join("excel/Item.xlsx")).unwrap();
    assert_eq!(before, after);
}

#[test]
fn migration_with_manifest_preserves_data() {
    let dir = setup();
    // 先生成空模板
    let ws = Workspace::open(dir.path()).unwrap();
    gen_template(&ws, Some("Item"), false).unwrap();
    // 写入一行数据（重建模板 + 数据，一次写入）
    let path = dir.path().join("excel/Item.xlsx");
    let table = ws
        .resources
        .tables
        .iter()
        .find(|t| t.table == "Item")
        .unwrap();
    let layout =
        ct_excel::layout::build_layout(table, "sha256:x", &std::collections::HashMap::new());
    let mut workbook = rust_xlsxwriter::Workbook::new();
    {
        let sheet = workbook.add_worksheet();
        let enums = ct_excel::template::EnumMap::new();
        let mut writer = ct_excel::template::TemplateWriter::new(&layout, &enums, "Id");
        writer.write_sheet(sheet).unwrap();
        sheet.write_number(2, 0, 42.0).unwrap();
        sheet.write_string(2, 1, "sword_iron").unwrap();
    }
    std::fs::write(&path, workbook.save_to_buffer().unwrap()).unwrap();

    // schema 加一列 → 迁移保留数据
    write(
        &dir.path().join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Weight\n    type: float\n",
    );
    let ws = Workspace::open(dir.path()).unwrap();
    let messages = gen_template(&ws, Some("Item"), false).unwrap();
    assert_eq!(messages, vec!["模板已生成: Item"]);

    let report = probe_xlsx(&path).unwrap();
    let data: HashMap<(u32, u32), String> = report
        .cells
        .iter()
        .filter(|c| c.row > 2)
        .map(|c| (c.row, c.col, format!("{:?}", c.value)))
        .map(|(r, c, v)| ((r, c), v))
        .collect();
    assert!(
        data.values().any(|v| v.contains("42")),
        "数据丢失: {data:?}"
    );
    assert!(data.values().any(|v| v.contains("sword_iron")));
    // 新 manifest 有 3 列
    let manifest_text =
        std::fs::read_to_string(dir.path().join("excel/layout_manifests/Item.json")).unwrap();
    let value: serde_json::Value = serde_json::from_str(&manifest_text).unwrap();
    let manifest = ct_excel::manifest::LayoutManifest::parse(&value).unwrap();
    assert_eq!(manifest.columns.len(), 3);
}

#[test]
fn requires_scope_flag() {
    let dir = setup();
    let ws = Workspace::open(dir.path()).unwrap();
    let err = gen_template(&ws, None, false).unwrap_err();
    assert!(err.0.contains("--all 或 --table"), "{err}");
}
