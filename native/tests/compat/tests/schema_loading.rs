//! YAML 资源仓库加载对照（rust-native-core 任务 2.1）：
//! 自定义目录、非法字段、跨平台大小写冲突、具名类型解析。

use std::collections::HashMap;
use std::path::PathBuf;

use ct_domain::repository::{Resource, YamlResourceRepository};
use ct_domain::types::{NamedKind, TypeExpr};

/// 在临时目录建工作区骨架，返回 (tempdir, schemas_dir, types_dir)。
fn setup(
    schemas: &[(&str, &str)],
    types: &[(&str, &str)],
) -> (tempfile::TempDir, PathBuf, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let schemas_dir = dir.path().join("config/schemas");
    let types_dir = dir.path().join("config/types");
    std::fs::create_dir_all(&schemas_dir).unwrap();
    std::fs::create_dir_all(&types_dir).unwrap();
    for (name, text) in schemas {
        std::fs::write(schemas_dir.join(format!("{name}.yaml")), text).unwrap();
    }
    for (name, text) in types {
        std::fs::write(types_dir.join(format!("{name}.yaml")), text).unwrap();
    }
    (dir, schemas_dir, types_dir)
}

const TABLE_ITEM: &str = r#"
table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: CodeName
    type: string
"#;

const ENUM_RARITY: &str = r#"
kind: enum
name: ItemRarity
values:
  - name: Common
  - name: Rare
"#;

const RECORD_DROP: &str = r#"
kind: record
name: DropReward
fields:
  - name: ItemId
    type: int32
  - name: Count
    type: int32
"#;

#[test]
fn custom_dirs_load_and_resolve() {
    let (_dir, schemas, types) = setup(&[("item", TABLE_ITEM)], &[("rarity", ENUM_RARITY)]);
    let repo = YamlResourceRepository::new(schemas, types);
    let ws = repo.load().unwrap();
    assert_eq!(ws.tables.len(), 1);
    assert_eq!(ws.enums.len(), 1);
    assert!(ws.by_name.contains_key("Item"));
    assert!(ws.by_id.contains_key("table:Item"));
    // 文件名可与资源名不同
    assert!(ws.sources["table:Item"].ends_with("item.yaml"));
}

#[test]
fn unknown_field_key_rejected() {
    let bad = TABLE_ITEM.replace("type: int32", "type: int32\n    bogus_key: 1");
    let (_dir, schemas, types) = setup(&[("item", &bad)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("bogus_key"), "{err}");
}

#[test]
fn old_shape_rejected() {
    // 旧格式：field 里写 values
    let old = r#"
table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Rarity
    type: enum
    values: [Common, Rare]
"#;
    let (_dir, schemas, types) = setup(&[("item", old)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("旧格式"), "{err}");

    // 旧格式：enum values 是字符串列表
    let (_dir, schemas, types) = setup(
        &[("item", TABLE_ITEM)],
        &[(
            "rarity",
            "kind: enum\nname: ItemRarity\nvalues: [Common, Rare]\n",
        )],
    );
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("Enum values"), "{err}");
}

#[test]
fn duplicate_name_rejected() {
    let other = TABLE_ITEM.replace("table: Item", "table: Item2");
    let dup = other.replace("table: Item2", "table: Item"); // 同名不同文件
    let _ = other;
    let (_dir, schemas, types) = setup(&[("a", TABLE_ITEM), ("b", &dup)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("资源名 'Item' 重复"), "{err}");
    assert!(err.0.contains("a.yaml"), "{err}");
    assert!(err.0.contains("b.yaml"), "{err}");
}

#[test]
fn case_conflict_rejected() {
    let lower = TABLE_ITEM.replace("table: Item", "table: item");
    // item 首字符小写不合法（PascalCase），用小写不违规但大小写不同的名字：
    // Item 与 ITEM 均合法 PascalCase
    let upper = TABLE_ITEM.replace("table: Item", "table: ITEM");
    let _ = lower;
    let (_dir, schemas, types) = setup(&[("a", TABLE_ITEM), ("b", &upper)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("仅大小写不同"), "{err}");
}

#[test]
fn named_type_resolution() {
    let table = r#"
table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Rarity
    type: ItemRarity
  - name: Drop
    type: DropReward
"#;
    let (_dir, schemas, types) = setup(
        &[("item", table)],
        &[("rarity", ENUM_RARITY), ("drop", RECORD_DROP)],
    );
    let ws = YamlResourceRepository::new(schemas, types).load().unwrap();
    let item = &ws.tables[0];
    let TypeExpr::Named(rarity) = &item.fields[1].type_expr else {
        panic!()
    };
    assert_eq!(rarity.resource_id(), "enum:ItemRarity");
    assert_eq!(rarity.expected_kind(), Some(NamedKind::Enum));
    let TypeExpr::Named(drop) = &item.fields[2].type_expr else {
        panic!()
    };
    assert_eq!(drop.resource_id(), "record:DropReward");
}

#[test]
fn unknown_named_type_rejected() {
    let table = TABLE_ITEM.replace("type: string", "type: Missing");
    let (_dir, schemas, types) = setup(&[("item", &table)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("具名类型 'Missing' 不存在"), "{err}");
    assert!(err.0.contains("table:Item/CodeName"), "{err}");
}

#[test]
fn table_reference_rejected() {
    let other = TABLE_ITEM.replace("table: Item", "table: Other");
    let with_ref = TABLE_ITEM.replace("type: string", "type: Other");
    let (_dir, schemas, types) = setup(&[("item", &with_ref), ("other", &other)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("不能直接引用 Table 'Other'"), "{err}");
}

#[test]
fn expected_kind_mismatch_rejected() {
    let table = TABLE_ITEM.replace("type: string", "type: record:ItemRarity");
    let (_dir, schemas, types) = setup(&[("item", &table)], &[("rarity", ENUM_RARITY)]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("期望 record"), "{err}");
}

#[test]
fn vector_record_requires_excel_columns() {
    let table = TABLE_ITEM.replace("type: string", "type: vector<DropReward>");
    let (_dir, schemas, types) = setup(&[("item", &table)], &[("drop", RECORD_DROP)]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("必须配置 excel_columns"), "{err}");

    // 配置后通过
    let ok = table.replace(
        "type: vector<DropReward>",
        "type: vector<DropReward>\n    excel_columns: 2",
    );
    let (_dir, schemas, types) = setup(&[("item", &ok)], &[("drop", RECORD_DROP)]);
    YamlResourceRepository::new(schemas, types).load().unwrap();
}

#[test]
fn ref_on_vector_rejected() {
    let table = TABLE_ITEM.replace("type: string", "type: vector<string>\n    ref: table:Item");
    let (_dir, schemas, types) = setup(&[("item", &table)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("ref 字段不能声明 vector"), "{err}");
}

#[test]
fn primary_key_type_rule() {
    let bad = TABLE_ITEM.replace("type: int32", "type: uint32");
    let (_dir, schemas, types) = setup(&[("item", &bad)], &[]);
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("主键字段 'Id' 类型必须为 int32"), "{err}");
}

#[test]
fn captured_contents_mode_ignores_disk() {
    // 捕获模式：只从给定内容解析，不读盘
    let (_dir, schemas, types) = setup(&[("item", TABLE_ITEM)], &[]);
    let mut contents: HashMap<PathBuf, Vec<u8>> = HashMap::new();
    contents.insert(
        schemas.join("captured.yaml"),
        TABLE_ITEM
            .replace("table: Item", "table: Captured")
            .into_bytes(),
    );
    let repo = YamlResourceRepository::new(schemas, types);
    let ws = repo.load_captured(&contents).unwrap();
    assert_eq!(ws.tables.len(), 1);
    assert_eq!(ws.tables[0].table, "Captured");
}

#[test]
fn types_dir_kind_mismatch_rejected() {
    let (_dir, schemas, types) = setup(
        &[("item", TABLE_ITEM)],
        &[("bad", "kind: table\nname: X\n")],
    );
    let err = YamlResourceRepository::new(schemas, types)
        .load()
        .unwrap_err();
    assert!(err.0.contains("kind 必须为 record 或 enum"), "{err}");
}

#[test]
fn by_id_lookup() {
    let (_dir, schemas, types) = setup(&[("item", TABLE_ITEM)], &[("rarity", ENUM_RARITY)]);
    let ws = YamlResourceRepository::new(schemas, types).load().unwrap();
    match &ws.by_id["enum:ItemRarity"] {
        Resource::Enum(e) => assert_eq!(e.value_names(), vec!["Common", "Rare"]),
        other => panic!("应为 Enum: {other:?}"),
    }
}
