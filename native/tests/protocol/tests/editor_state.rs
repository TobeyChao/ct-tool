//! 编辑器状态回显（native-flutter-workbench 任务 3.2 的内核侧契约）：
//! `resources.list` 必须带出已声明的索引 kind，`table.preview` 必须带出字段属性；
//! 否则界面只能凭猜测渲染开关，用户会以为自己把已有索引点没了。

use ct_tests_protocol::{rich_workspace, Wire};
use serde_json::json;

fn resource<'a>(listed: &'a serde_json::Value, name: &str) -> &'a serde_json::Value {
    listed["resources"]
        .as_array()
        .expect("resources 应为数组")
        .iter()
        .find(|entry| entry["name"] == name)
        .unwrap_or_else(|| panic!("清单里应有 {name}"))
}

#[test]
fn resources_list_reports_declared_index_kinds() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let listed = wire.payload("resources.list", json!({}));
    let item = resource(&listed, "Item");
    assert_eq!(item["indexes"], json!(["codename"]), "{item}");
    // 未声明索引的资源不得凭空长出键（缺失即空集，避免界面误读）。
    let rarity = resource(&listed, "Rarity");
    assert!(rarity.get("indexes").is_none(), "{rarity}");
    wire.shutdown();
}

#[test]
fn preview_columns_carry_field_properties() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let preview = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    let columns = preview["columns"].as_array().expect("columns 应为数组");
    let column = |name: &str| {
        columns
            .iter()
            .find(|c| c["name"] == name)
            .unwrap_or_else(|| panic!("预览列里应有 {name}"))
    };
    assert_eq!(column("Id")["role"], "primary");
    assert_eq!(column("Name")["i18n"], json!(true), "{:?}", column("Name"));
    // 未声明的属性一律缺席，而不是回一个假 false。
    assert!(column("Id").get("i18n").is_none(), "{:?}", column("Id"));
    assert!(column("Id").get("ref").is_none(), "{:?}", column("Id"));
    assert!(column("Name").get("excelColumns").is_none());
    wire.shutdown();
}
