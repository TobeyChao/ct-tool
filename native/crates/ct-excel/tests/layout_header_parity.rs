//! record 成员自身是「未分组 vector」时的表头/manifest 归属（任务 6.9 真实工作区对照发现）。
//!
//! Python 权威结论（用 `ct/.venv` 的现行实现对同一 schema 真跑 gen-template 抓取）：
//! 表头第二行取 `field_annotation or annotation` —— record 成员继承所属 record 名，
//! 而 manifest 的列 annotation 仍是它自己的 `vector<int32>`、typeExpr 是元素类型 `int32`。
//! 原生内核曾按叶自身类型生成表头期望值，导致真实 `gd` 的 ComplexShowcase 被误报
//! 「工作簿表头与当前 schema 的读取结构不一致」。这里把两侧语义同时钉住。

use std::collections::HashMap;

use ct_domain::schema::{FieldDef, QueryIndex, RecordResource, TableResource};
use ct_domain::types::TypeExpr;
use ct_excel::compat::expected_header_grid;
use ct_excel::layout::build_layout;
use ct_excel::manifest::LayoutManifest;

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

fn layout() -> ct_excel::layout::Layout {
    let reward = RecordResource {
        kind: "record".into(),
        name: "RewardDefinition".into(),
        comment: String::new(),
        fields: vec![field("Count", "int32"), field("ItemIds", "vector<int32>")],
    };
    let mut records: HashMap<String, RecordResource> = HashMap::new();
    records.insert(reward.name.clone(), reward);
    let table = TableResource {
        table: "Showcase".into(),
        primary: "Id".into(),
        fields: vec![field("Id", "int32"), field("Reward", "RewardDefinition")],
        json_key: None,
        excel_file: None,
        indexes: vec![QueryIndex],
        uniform: false,
    };
    build_layout(&table, "sha256:86bb6aa95a7ffe81", &records)
}

#[test]
fn header_grid_inherits_record_name_for_vector_member() {
    let grid = expected_header_grid(&layout());
    let member = grid
        .iter()
        .find(|((_, _), text)| text.starts_with("ItemIds\n"))
        .unwrap_or_else(|| panic!("表头网格里没有 ItemIds：{grid:?}"));
    assert_eq!(
        member.1, "ItemIds\nRewardDefinition",
        "record 成员的表头第二行必须是所属 record 名（与 Python 写入的真实工作簿一致）"
    );
    assert!(
        grid.iter()
            .any(|(_, text)| text == "Reward\nRewardDefinition"),
        "record 顶层表头用所属类型名：{grid:?}"
    );
}

#[test]
fn manifest_columns_match_python_reference_values() {
    let payload = LayoutManifest::from_layout(&layout(), &[]).payload();
    let columns = payload["columns"].as_array().expect("columns");
    let item_ids = columns
        .iter()
        .find(|column| column["leaf"] == "ItemIds")
        .expect("ItemIds 列");
    // Python 真跑抓取：annotation=vector<int32>、typeExpr=int32、depth=1
    assert_eq!(item_ids["annotation"], "vector<int32>");
    assert_eq!(item_ids["typeExpr"], "int32");
    assert_eq!(item_ids["depth"], 1);
    let nodes = payload["nodes"].as_array().expect("nodes");
    let node = nodes
        .iter()
        .find(|entry| entry["displayName"] == "ItemIds")
        .expect("ItemIds 节点");
    assert_eq!(node["annotation"], "RewardDefinition");
    assert_eq!(node["depth"], 2);
    assert_eq!(node["kind"], "field");
    assert_eq!(payload["format"], "template-layout/2");
    assert_eq!(payload["header_rows"], 4);
}
