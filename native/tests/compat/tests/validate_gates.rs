//! 校验闸门端到端（rust-native-core 任务 2.5）：
//! 主键 / CodeName / 枚举域 / ref 闭包，单表过滤仍拒绝坏引用，问题顺序确定。

use std::collections::HashMap;
use std::path::Path;

use ct_app::validate::canonical_validate;
use ct_app::workspace::Workspace;
use ct_domain::schema::{FieldDef, QueryIndex, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::layout::build_layout;
use ct_excel::manifest::LayoutManifest;
use ct_excel::template::{build_template, EnumDoc, EnumItemDoc, EnumMap};

fn field(name: &str, type_text: &str) -> FieldDef {
    FieldDef {
        name: name.into(),
        type_expr: TypeExpr::parse(type_text).unwrap(),
        i18n: false,
        ref_: None,
        server_only: false,
        comment: String::new(),
        excel_columns: None,
    }
}

fn item_table() -> TableResource {
    TableResource {
        table: "Item".into(),
        primary: "Id".into(),
        fields: vec![
            field("Id", "int32"),
            field("CodeName", "string"),
            field("Rarity", "ItemRarity"),
        ],
        json_key: None,
        excel_file: None,
        indexes: vec![QueryIndex],
        uniform: true,
    }
}

fn buff_table() -> TableResource {
    let mut item_id = field("ItemId", "int32");
    item_id.ref_ = Some("Item.Id".into());
    TableResource {
        table: "Buff".into(),
        primary: "Id".into(),
        fields: vec![field("Id", "int32"), item_id],
        json_key: None,
        excel_file: None,
        indexes: vec![],
        uniform: true,
    }
}

fn enums() -> EnumMap {
    [(
        "ItemRarity".to_string(),
        EnumDoc {
            comment: String::new(),
            values: vec![
                EnumItemDoc {
                    name: "Common".into(),
                    comment: String::new(),
                },
                EnumItemDoc {
                    name: "Rare".into(),
                    comment: String::new(),
                },
            ],
        },
    )]
    .into_iter()
    .collect()
}

/// 写一张表：模板 + 数据行 + manifest。
fn write_table(
    root: &Path,
    table: &TableResource,
    records: &HashMap<String, ct_domain::schema::RecordResource>,
    rows: &[Vec<serde_json::Value>],
) {
    let layout = build_layout(table, "sha256:test", records);
    let (mut bytes, _w) = build_template(&layout, &enums(), &table.primary).unwrap();
    if !rows.is_empty() {
        // 用 rust_xlsxwriter 重新生成：模板 + 数据
        let mut workbook = rust_xlsxwriter::Workbook::new();
        {
            let ws = workbook.add_worksheet();
            let enum_map = enums();
            let mut writer =
                ct_excel::template::TemplateWriter::new(&layout, &enum_map, &table.primary);
            writer.write_sheet(ws).unwrap();
            for (r, row) in rows.iter().enumerate() {
                let row0 = layout.header_rows + r as u32;
                for (c, value) in row.iter().enumerate() {
                    match value {
                        serde_json::Value::Number(n) => {
                            ws.write_number(row0, c as u16, n.as_f64().unwrap())
                                .unwrap();
                        }
                        serde_json::Value::String(s) => {
                            ws.write_string(row0, c as u16, s).unwrap();
                        }
                        serde_json::Value::Bool(b) => {
                            ws.write_boolean(row0, c as u16, *b).unwrap();
                        }
                        _ => {}
                    }
                }
            }
        }
        bytes = workbook.save_to_buffer().unwrap();
    }
    let excel_dir = root.join("excel");
    std::fs::create_dir_all(excel_dir.join("layout_manifests")).unwrap();
    std::fs::write(excel_dir.join(format!("{}.xlsx", table.table)), bytes).unwrap();
    let manifest = LayoutManifest::from_layout(&layout, &[]);
    std::fs::write(
        excel_dir
            .join("layout_manifests")
            .join(format!("{}.json", table.table)),
        serde_json::to_string_pretty(&manifest.payload()).unwrap(),
    )
    .unwrap();
}

/// 搭工作区：config + schemas + types + excel。
fn setup_workspace(
    item_rows: Vec<Vec<serde_json::Value>>,
    buff_rows: Vec<Vec<serde_json::Value>>,
    include_buff: bool,
) -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::create_dir_all(root.join("config/schemas")).unwrap();
    std::fs::create_dir_all(root.join("config/types")).unwrap();
    std::fs::write(root.join("config/global.yaml"), "primary_lang: zh\n").unwrap();
    std::fs::write(
        root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nindexes:\n  - kind: codename\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Rarity\n    type: ItemRarity\n",
    )
    .unwrap();
    if include_buff {
        std::fs::write(
            root.join("config/schemas/buff.yaml"),
            "table: Buff\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: ItemId\n    type: int32\n    ref: Item.Id\n",
        )
        .unwrap();
    }
    std::fs::write(
        root.join("config/types/rarity.yaml"),
        "kind: enum\nname: ItemRarity\nvalues:\n  - name: Common\n  - name: Rare\n",
    )
    .unwrap();

    let records = HashMap::new();
    write_table(root, &item_table(), &records, &item_rows);
    if include_buff {
        write_table(root, &buff_table(), &records, &buff_rows);
    }
    dir
}

fn validate(root: &Path, filter: Option<&str>) -> Vec<String> {
    let ws = Workspace::open(root).unwrap();
    canonical_validate(&ws, filter)
        .iter()
        .map(|i| format!("{}:{}:{}", i.table, i.code.as_str(), i.message))
        .collect()
}

#[test]
fn clean_workspace_no_issues() {
    let dir = setup_workspace(
        vec![
            vec![1.into(), "sword_iron".into(), "Common".into()],
            vec![2.into(), "potion_red".into(), "Rare".into()],
        ],
        vec![vec![1.into(), 1.into()], vec![2.into(), 2.into()]],
        true,
    );
    assert!(validate(dir.path(), None).is_empty());
}

#[test]
fn duplicate_primary_key_rejected() {
    let dir = setup_workspace(
        vec![
            vec![1.into(), "a".into(), "Common".into()],
            vec![1.into(), "b".into(), "Rare".into()],
        ],
        vec![],
        false,
    );
    let issues = validate(dir.path(), None);
    assert!(
        issues
            .iter()
            .any(|i| i.contains("duplicate_pk") && i.contains("主键重复: 1")),
        "{issues:?}"
    );
}

#[test]
fn codename_empty_and_duplicate_rejected() {
    let dir = setup_workspace(
        vec![
            vec![1.into(), "".into(), "Common".into()],
            vec![2.into(), "dup".into(), "Rare".into()],
            vec![3.into(), "dup".into(), "Common".into()],
        ],
        vec![],
        false,
    );
    let issues = validate(dir.path(), None);
    assert!(
        issues.iter().any(|i| i.contains("CodeName 为空")),
        "{issues:?}"
    );
    assert!(
        issues
            .iter()
            .any(|i| i.contains("duplicate_codename") && i.contains("首次出现在第 2 行")),
        "{issues:?}"
    );
}

#[test]
fn unknown_enum_token_rejected() {
    let dir = setup_workspace(
        vec![vec![1.into(), "a".into(), "Legendary".into()]],
        vec![],
        false,
    );
    let issues = validate(dir.path(), None);
    assert!(
        issues
            .iter()
            .any(|i| i.contains("不在 Enum ItemRarity 的声明值中")),
        "{issues:?}"
    );
}

#[test]
fn bad_ref_rejected_even_with_table_filter() {
    let dir = setup_workspace(
        vec![vec![1.into(), "a".into(), "Common".into()]],
        vec![vec![1.into(), 99.into()]], // 99 不存在
        true,
    );
    // 单表过滤 Buff：仍读取 Item 闭包并拒绝坏引用
    let issues = validate(dir.path(), Some("Buff"));
    assert!(
        issues
            .iter()
            .any(|i| i.contains("ref") && i.contains("值 99 在引用表 Item.Id 中不存在")),
        "{issues:?}"
    );
}

#[test]
fn unknown_table_filter() {
    let dir = setup_workspace(vec![], vec![], false);
    let issues = validate(dir.path(), Some("Nope"));
    assert!(
        issues.iter().any(|i| i.contains("表 'Nope' 不存在")),
        "{issues:?}"
    );
}

#[test]
fn deterministic_issue_order() {
    // 同一输入两次校验顺序一致
    let dir = setup_workspace(
        vec![
            vec![1.into(), "".into(), "Nope".into()],
            vec![1.into(), "dup".into(), "Common".into()],
        ],
        vec![vec![1.into(), 42.into()]],
        true,
    );
    let a = validate(dir.path(), None);
    let b = validate(dir.path(), None);
    assert_eq!(a, b);
    assert!(!a.is_empty());
}
