//! 资源依赖图对照（rust-native-core 任务 2.2）：
//! 拓扑序、反向引用、循环检测、ref 校验、删除守卫。

use ct_domain::graph::{
    cross_table_ref_edges, named_dependency_edges, require_deletable, resource_topological_order,
    reverse_references,
};
use ct_domain::repository::Resource;
use ct_domain::schema::{EnumItem, EnumResource, FieldDef, RecordResource, TableResource};
use ct_domain::types::TypeExpr;

fn field(name: &str, type_text: &str) -> FieldDef {
    FieldDef {
        name: name.to_string(),
        type_expr: TypeExpr::parse(type_text).unwrap(),
        i18n: false,
        ref_: None,
        server_only: false,
        comment: String::new(),
        excel_columns: None,
    }
}

fn ref_field(name: &str, ref_: &str) -> FieldDef {
    FieldDef {
        ref_: Some(ref_.to_string()),
        ..field(name, "int32")
    }
}

fn enum_res(name: &str, values: &[&str]) -> Resource {
    Resource::Enum(EnumResource {
        kind: "enum".into(),
        name: name.into(),
        values: values
            .iter()
            .map(|v| EnumItem {
                name: v.to_string(),
                comment: String::new(),
            })
            .collect(),
        comment: String::new(),
    })
}

fn record_res(name: &str, fields: Vec<FieldDef>) -> Resource {
    Resource::Record(RecordResource {
        kind: "record".into(),
        name: name.into(),
        fields,
        comment: String::new(),
    })
}

fn table_res(name: &str, fields: Vec<FieldDef>) -> Resource {
    Resource::Table(TableResource {
        table: name.into(),
        primary: "Id".into(),
        fields: [vec![field("Id", "int32")], fields].concat(),
        json_key: None,
        excel_file: None,
        indexes: vec![],
        uniform: true,
    })
}

#[test]
fn named_edges_sorted_and_deduped() {
    let resources = vec![
        enum_res("ItemRarity", &["Common"]),
        record_res("Drop", vec![field("Rarity", "ItemRarity")]),
        table_res(
            "Item",
            vec![
                field("Rarity", "ItemRarity"),
                field("Tags", "vector<ItemRarity>"),
                field("Drop", "Drop"),
            ],
        ),
    ];
    let graph = named_dependency_edges(&resources);
    // 注意：裸名未解析时按裸名记录（加载期仓库已解析，本测试直接用裸名）
    assert_eq!(
        graph["table:Item"],
        vec!["Drop".to_string(), "ItemRarity".to_string()]
    );
    assert_eq!(graph["record:Drop"], vec!["ItemRarity".to_string()]);
}

#[test]
fn topological_order_named_before_tables() {
    let resources = vec![
        table_res("Item", vec![field("Rarity", "enum:ItemRarity")]),
        enum_res("ItemRarity", &["Common"]),
        table_res("Drop", vec![ref_field("ItemId", "Item.Id")]),
    ];
    let order = resource_topological_order(&resources).unwrap();
    let pos = |id: &str| order.iter().position(|x| x == id).unwrap();
    assert!(pos("enum:ItemRarity") < pos("table:Item"));
    assert!(pos("table:Item") < pos("table:Drop"));
}

#[test]
fn cycle_detected_with_path() {
    let resources = vec![
        record_res("A", vec![field("B", "record:B")]),
        record_res("B", vec![field("A", "record:A")]),
    ];
    let err = resource_topological_order(&resources).unwrap_err();
    assert!(err.0.contains("循环依赖"), "{err}");
}

#[test]
fn ref_target_must_be_primary() {
    let resources = vec![
        table_res("Item", vec![field("CodeName", "string")]),
        table_res("Drop", vec![ref_field("ItemId", "Item.CodeName")]),
    ];
    let err = cross_table_ref_edges(&resources).unwrap_err();
    assert!(err.0.contains("ref 目标必须是目标表主键"), "{err}");

    let missing = vec![table_res("Drop", vec![ref_field("ItemId", "Nope.Id")])];
    let err = cross_table_ref_edges(&missing).unwrap_err();
    assert!(err.0.contains("引用的表 'Nope' 不存在"), "{err}");
}

#[test]
fn reverse_references_cover_named_and_ref() {
    let resources = vec![
        enum_res("ItemRarity", &["Common"]),
        table_res("Item", vec![field("Rarity", "enum:ItemRarity")]),
        table_res("Drop", vec![ref_field("ItemId", "Item.Id")]),
    ];
    let reverse = reverse_references(&resources);
    assert_eq!(
        reverse["enum:ItemRarity"][0].field_path,
        "table:Item/Rarity"
    );
    assert_eq!(reverse["table:Item"][0].kind, "ref");
    assert_eq!(reverse["table:Item/Id"][0].field_path, "table:Drop/ItemId");

    // 删除守卫
    require_deletable("enum:ItemRarity", &reverse).unwrap_err();
    require_deletable("record:Free", &reverse).unwrap();
}
