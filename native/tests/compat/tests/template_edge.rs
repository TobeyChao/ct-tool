//! 模板/迁移边界语义对照（rust-native-core 任务 3.13）：
//! 超长枚举下拉跳过 + warning 透出、删除字段有数据拒绝且原文件不变、
//! 迁移不承诺保留任意工作簿内容（附加 Sheet 不随迁）。

use std::path::Path;

use ct_app::template::gen_template;
use ct_app::workspace::Workspace;
use ct_excel::reader::probe_xlsx;

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content.replace("\r\n", "\n")).unwrap();
}

fn write_schema(root: &Path, fields_yaml: &str) {
    write(&root.join("config/global.yaml"), "primary_lang: zh\n");
    write(
        &root.join("config/schemas/item.yaml"),
        &format!("table: Item\nprimary: Id\nfields:\n{fields_yaml}"),
    );
    // 超长枚举：候选公式超 255 字符
    std::fs::create_dir_all(root.join("config/types")).unwrap();
    let mut enum_yaml = String::new();
    for index in 0..20 {
        enum_yaml.push_str(&format!("  - name: QuiteLongEnumValueName{index:02}\n"));
    }
    std::fs::write(
        root.join("config/types/long_enum.yaml"),
        "kind: enum\nname: LongEnum\nvalues:\n".to_string() + &enum_yaml,
    )
    .unwrap();
}

#[test]
fn long_enum_dropdown_skipped_with_warning() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Big\n    type: LongEnum\n",
    );
    let ws = Workspace::open(root).unwrap();
    let messages = gen_template(&ws, Some("Item"), false).unwrap();
    // warning 透出（与 Python warnings.warn 同文）
    assert!(
        messages
            .iter()
            .any(|m| m.contains("Enum LongEnum 候选超过 Excel 255 字符限制")),
        "{messages:?}"
    );
    // 该列没有下拉，但表头 Note 仍在（批注部件存在）
    let report = probe_xlsx(&root.join("excel/Item.xlsx")).unwrap();
    assert_eq!(report.sheets, vec!["Item".to_string()]);
    let bytes = std::fs::read(root.join("excel/Item.xlsx")).unwrap();
    // 只有 Id 的 whole-number 校验，Big 列无 list 校验
    let sheet_xml = {
        let mut zip = zip::ZipArchive::new(std::io::Cursor::new(&bytes)).unwrap();
        let mut s = String::new();
        std::io::Read::read_to_string(
            &mut zip.by_name("xl/worksheets/sheet1.xml").unwrap(),
            &mut s,
        )
        .unwrap();
        s
    };
    assert_eq!(sheet_xml.matches("<dataValidation ").count(), 1);
    assert!(
        sheet_xml.contains(r#"type="whole""#) && sheet_xml.contains("-2147483648"),
        "Id 列 int32 数值校验缺失"
    );
    // 枚举 Note 部件存在（提示用户参考表头）
    let mut zip = zip::ZipArchive::new(std::io::Cursor::new(&bytes)).unwrap();
    assert!(zip.by_name("xl/comments1.xml").is_ok(), "缺少枚举批注部件");
}

#[test]
fn deleted_field_with_data_blocks_and_keeps_original() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    // v1：Id + CodeName + Name
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Name\n    type: string\n",
    );
    // 去掉 LongEnum 引用：本用例不需要它，但保留文件（空字段表也合法）
    let ws = Workspace::open(root).unwrap();
    gen_template(&ws, Some("Item"), false).unwrap();

    // 在 v1 模板里填一行数据（用 rust_xlsxwriter 重写一个带数据的同布局工作簿）
    let xlsx = root.join("excel/Item.xlsx");
    let mut workbook = rust_xlsxwriter::Workbook::new();
    let ws1 = workbook.add_worksheet();
    ws1.set_name("Item").unwrap();
    // 表头两行（内容不影响迁移，迁移认 manifest 布局）
    ws1.write_string(0, 0, "Id").unwrap();
    ws1.write_string(0, 1, "CodeName").unwrap();
    ws1.write_string(0, 2, "Name").unwrap();
    ws1.write_number(2, 0, 1001.0).unwrap();
    ws1.write_string(2, 1, "sword").unwrap();
    ws1.write_string(2, 2, "铁剑").unwrap();
    std::fs::write(&xlsx, workbook.save_to_buffer().unwrap()).unwrap();
    let before = std::fs::read(&xlsx).unwrap();

    // v2：删除 CodeName（有数据 → blocker）
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Name\n    type: string\n",
    );
    let ws = Workspace::open(root).unwrap();
    let err = gen_template(&ws, Some("Item"), false).unwrap_err();
    assert!(err.0.contains("无法安全迁移"), "{}", err.0);
    assert!(err.0.contains("CodeName"), "{}", err.0);
    // 原文件字节不变（不产生任何写入）
    assert_eq!(std::fs::read(&xlsx).unwrap(), before);
}

#[test]
fn migration_preserves_data_but_not_arbitrary_sheets() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Name\n    type: string\n",
    );
    let ws = Workspace::open(root).unwrap();
    gen_template(&ws, Some("Item"), false).unwrap();

    // 带附加 Sheet 的数据工作簿（Notes 页是用户私有内容）
    let xlsx = root.join("excel/Item.xlsx");
    let mut workbook = rust_xlsxwriter::Workbook::new();
    let ws1 = workbook.add_worksheet();
    ws1.set_name("Item").unwrap();
    ws1.write_string(0, 0, "Id").unwrap();
    ws1.write_string(0, 1, "Name").unwrap();
    ws1.write_number(2, 0, 1001.0).unwrap();
    ws1.write_string(2, 1, "铁剑").unwrap();
    let notes = workbook.add_worksheet();
    notes.set_name("Notes").unwrap();
    notes
        .write_string(0, 0, "用户随手记的备注，不属于数据区")
        .unwrap();
    std::fs::write(&xlsx, workbook.save_to_buffer().unwrap()).unwrap();

    // v2：新增字段 → 迁移
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Name\n    type: string\n  - name: Weight\n    type: float\n",
    );
    let ws = Workspace::open(root).unwrap();
    let messages = gen_template(&ws, Some("Item"), false).unwrap();
    assert!(messages.iter().any(|m| m.contains("模板已生成")));

    // 语义：只保留 canonical 表 Sheet（不承诺任意工作簿无损保留），数据随迁
    let report = probe_xlsx(&xlsx).unwrap();
    assert_eq!(
        report.sheets,
        vec!["Item".to_string()],
        "附加 Sheet 不应随迁"
    );
    assert!(report
        .cells
        .iter()
        .any(|c| matches!(&c.value, ct_excel::reader::ProbeValue::Text(t) if t == "铁剑")));
    assert!(report
        .cells
        .iter()
        .any(|c| matches!(&c.value, ct_excel::reader::ProbeValue::Number(n) if *n == 1001.0)));
}

#[test]
fn unconvertible_type_change_blocks() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Name\n    type: string\n",
    );
    let ws = Workspace::open(root).unwrap();
    gen_template(&ws, Some("Item"), false).unwrap();

    let xlsx = root.join("excel/Item.xlsx");
    let mut workbook = rust_xlsxwriter::Workbook::new();
    let ws1 = workbook.add_worksheet();
    ws1.set_name("Item").unwrap();
    ws1.write_string(0, 0, "Id").unwrap();
    ws1.write_string(0, 1, "Name").unwrap();
    ws1.write_number(2, 0, 1001.0).unwrap();
    ws1.write_string(2, 1, "铁剑").unwrap();
    std::fs::write(&xlsx, workbook.save_to_buffer().unwrap()).unwrap();
    let before = std::fs::read(&xlsx).unwrap();

    // Name: string → int32，现有文本数据无法转换 → blocker
    write_schema(
        root,
        "  - name: Id\n    type: int32\n  - name: Name\n    type: int32\n",
    );
    let ws = Workspace::open(root).unwrap();
    let err = gen_template(&ws, Some("Item"), false).unwrap_err();
    assert!(err.0.contains("无法转换"), "{}", err.0);
    assert_eq!(std::fs::read(&xlsx).unwrap(), before);
}
