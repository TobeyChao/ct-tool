//! Schema 草稿命令/候选/净差异对照（rust-native-core 任务 3.10）：
//! 创建/改名/删除、undo/redo、引用改写、跨类别名称冲突。

use ct_domain::candidate::{candidate_hash, merge_indexes, validate_candidate};
use ct_domain::commands::{apply_commands, Command, DraftLog, DraftState};
use ct_domain::netdiff::{compute_net_diff, ADDED, MODIFIED, REMOVED, RENAMED};
use ct_domain::repository::Resource;
use ct_domain::schema::{
    EnumItem, EnumResource, FieldDef, QueryIndex, RecordResource, TableResource,
};
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

fn record_res(name: &str, fields: Vec<FieldDef>) -> Resource {
    Resource::Record(RecordResource {
        kind: "record".into(),
        name: name.into(),
        fields,
        comment: String::new(),
    })
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

fn fields_of(resource: &Resource) -> &[FieldDef] {
    match resource {
        Resource::Table(t) => &t.fields,
        Resource::Record(r) => &r.fields,
        Resource::Enum(_) => &[],
    }
}

fn field_count(resource: &Resource) -> usize {
    fields_of(resource).len()
}

fn base_state() -> DraftState {
    DraftState {
        resources: vec![
            table_res("Item", vec![field("Name", "string")]),
            record_res("DropRule", vec![field("Min", "int32")]),
            enum_res("Rarity", &["Common", "Rare"]),
        ],
        indexes: [("table:Item".to_string(), vec![QueryIndex])]
            .into_iter()
            .collect(),
    }
}

fn cmd(kind: &str, payload: serde_json::Value) -> Command {
    Command::new(kind, payload)
}

#[test]
fn add_rename_delete_replay() {
    let mut log = DraftLog::new(base_state());
    log.execute(cmd(
        "add_resource",
        serde_json::json!({"kind": "record", "resource": {"name": "LootBonus", "fields": [{"name": "Rate", "type": "float"}]}}),
    ))
    .unwrap();
    log.execute(cmd(
        "rename_resource",
        serde_json::json!({"old": "LootBonus", "new": "LootPool"}),
    ))
    .unwrap();
    let state = log.current().unwrap();
    assert!(state
        .resources
        .iter()
        .any(|r| r.resource_id() == "record:LootPool"));
    assert!(!state
        .resources
        .iter()
        .any(|r| r.resource_id() == "record:LootBonus"));

    log.execute(cmd(
        "delete_resource",
        serde_json::json!({"name": "record:LootPool"}),
    ))
    .unwrap();
    let state = log.current().unwrap();
    assert_eq!(state.resources.len(), 3);
}

#[test]
fn undo_redo_cursor_semantics() {
    let mut log = DraftLog::new(base_state());
    log.execute(cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
    ))
    .unwrap();
    log.execute(cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Weight", "type": "int32"}}),
    ))
    .unwrap();
    assert_eq!(field_count(&log.current().unwrap().resources[0]), 4);

    assert!(log.undo());
    assert_eq!(field_count(&log.current().unwrap().resources[0]), 3);
    assert!(log.redo());
    assert_eq!(field_count(&log.current().unwrap().resources[0]), 4);

    // undo 后执行新命令：截断 redo 分支
    assert!(log.undo());
    log.execute(cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Level", "type": "int32"}}),
    ))
    .unwrap();
    assert_eq!(log.commands.len(), 2);
    assert!(!log.redo());
    let state = log.current().unwrap();
    let names: Vec<&str> = fields_of(&state.resources[0])
        .iter()
        .map(|f| f.name.as_str())
        .collect();
    assert_eq!(names, ["Id", "Name", "Price", "Level"]);
}

#[test]
fn rename_rewrites_named_refs_and_cross_table_refs() {
    let mut state = base_state();
    // Item 引用 DropRule；Monster 用 ref 指 Item.Id
    state.resources.push(table_res(
        "Monster",
        vec![FieldDef {
            ref_: Some("Item.Id".to_string()),
            ..field("LootItem", "int32")
        }],
    ));
    state.resources[0] = with_extra_field(&state.resources[0], field("Rules", "vector<DropRule>"));

    let renamed =
        ct_domain::commands::rename_resource(&state.resources, "DropRule", "DropEntry").unwrap();
    let item = renamed
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Item")
        .unwrap();
    let rules = &fields_of(item)[2];
    assert_eq!(rules.type_expr.to_text(), "vector<DropEntry>");
    assert_eq!(renamed.mapping["record:DropRule"], "record:DropEntry");

    let renamed =
        ct_domain::commands::rename_resource(&renamed.resources, "Item", "Goods").unwrap();
    let monster = renamed
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Monster")
        .unwrap();
    assert_eq!(fields_of(monster)[1].ref_.as_deref(), Some("Goods.Id"));
}

#[test]
fn rename_field_rejects_primary_and_cross_table_broadcast() {
    let mut state = base_state();
    state
        .resources
        .push(table_res("Monster", vec![field("CodeName", "string")]));
    // Item 加 CodeName；Monster 也有 CodeName：改 Item 的不得广播到 Monster
    state.resources[0] = with_extra_field(&state.resources[0], field("CodeName", "string"));
    let result =
        ct_domain::commands::rename_field(&state.resources, "table:Item", "CodeName", "Slug")
            .unwrap();
    let monster = result
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Monster")
        .unwrap();
    assert!(fields_of(monster).iter().any(|f| f.name == "CodeName"));
    assert!(!fields_of(monster).iter().any(|f| f.name == "Slug"));

    let err = ct_domain::commands::rename_field(&result.resources, "table:Item", "Id", "NewId")
        .unwrap_err();
    assert!(err.contains("主键字段不可改名"), "{err}");
}

#[test]
fn candidate_cross_kind_name_conflict() {
    let mut state = base_state();
    state
        .resources
        .push(record_res("Item", vec![field("X", "int32")]));
    let merged = merge_indexes(&state.resources, &state.indexes);
    let issues = validate_candidate(&merged, &state.indexes);
    assert!(
        issues
            .iter()
            .any(|i| i.message.contains("资源名 'Item' 重复")),
        "{issues:?}"
    );
}

#[test]
fn candidate_missing_and_kind_mismatched_refs() {
    let mut state = base_state();
    state.resources[0] = with_extra_field(&state.resources[0], field("Missing1", "NoSuchType"));
    // 期望 enum 实际 record
    state.resources[0] = with_extra_field(&state.resources[0], {
        let mut f = field("Wrong", "DropRule");
        f.type_expr = TypeExpr::Named(ct_domain::types::NamedRef::parse("enum:DropRule").unwrap());
        f
    });
    let merged = merge_indexes(&state.resources, &state.indexes);
    let issues = validate_candidate(&merged, &state.indexes);
    assert!(
        issues
            .iter()
            .any(|i| i.message.contains("具名类型 'NoSuchType' 不存在")),
        "{issues:?}"
    );
    assert!(
        issues
            .iter()
            .any(|i| i.message.contains("期望 enum，实际为 record")),
        "{issues:?}"
    );
}

#[test]
fn candidate_hash_is_order_independent_and_change_sensitive() {
    let state = base_state();
    let hash_a = candidate_hash(&state.resources, &state.indexes);
    let mut reversed = state.clone();
    reversed.resources.reverse();
    let hash_b = candidate_hash(&reversed.resources, &reversed.indexes);
    assert_eq!(hash_a, hash_b, "资源顺序不得影响 candidateHash");

    let mut changed = state.clone();
    changed.resources[0] = with_extra_field(&changed.resources[0], field("Extra", "int32"));
    assert_ne!(hash_a, candidate_hash(&changed.resources, &changed.indexes));

    // 索引参与哈希
    let mut reindexed = state.clone();
    reindexed.indexes.insert("table:Item".to_string(), vec![]);
    assert_ne!(
        hash_a,
        candidate_hash(&reindexed.resources, &reindexed.indexes)
    );
}

#[test]
fn netdiff_rename_chain_reports_single_rename() {
    let base = base_state();
    let commands = vec![
        cmd(
            "rename_resource",
            serde_json::json!({"old": "DropRule", "new": "DropEntry"}),
        ),
        cmd(
            "rename_resource",
            serde_json::json!({"old": "DropEntry", "new": "LootEntry"}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    assert_eq!(diff.changes.len(), 1);
    let change = &diff.changes[0];
    assert_eq!(change.change, RENAMED);
    assert_eq!(change.old_name.as_deref(), Some("DropRule"));
    assert_eq!(change.name, "LootEntry");
}

#[test]
fn netdiff_roundtrip_rename_is_noop() {
    let base = base_state();
    let commands = vec![
        cmd(
            "rename_resource",
            serde_json::json!({"old": "DropRule", "new": "DropEntry"}),
        ),
        cmd(
            "rename_resource",
            serde_json::json!({"old": "DropEntry", "new": "DropRule"}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    assert!(diff.is_empty(), "{}", diff.summary());
}

#[test]
fn netdiff_delete_then_add_is_not_rename() {
    let base = base_state();
    // 同名同 kind：删除+新增不猜成改名，按内容报 modified
    let commands = vec![
        cmd(
            "delete_resource",
            serde_json::json!({"name": "record:DropRule"}),
        ),
        cmd(
            "add_resource",
            serde_json::json!({"kind": "record", "resource": {"name": "DropRule", "fields": [{"name": "Max", "type": "int32"}]}}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    let kinds: Vec<&str> = diff.changes.iter().map(|c| c.change.as_str()).collect();
    assert_eq!(kinds, [MODIFIED], "{kinds:?}");

    // 不同名：一删一增，互不关联
    let commands = vec![
        cmd(
            "delete_resource",
            serde_json::json!({"name": "record:DropRule"}),
        ),
        cmd(
            "add_resource",
            serde_json::json!({"kind": "record", "resource": {"name": "LootRule", "fields": [{"name": "Max", "type": "int32"}]}}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    let kinds: Vec<&str> = diff.changes.iter().map(|c| c.change.as_str()).collect();
    assert!(kinds.contains(&REMOVED), "{kinds:?}");
    assert!(kinds.contains(&ADDED), "{kinds:?}");
    assert!(!kinds.contains(&RENAMED), "{kinds:?}");
}

#[test]
fn netdiff_enum_ordinal_risk_details() {
    let base = base_state();
    let commands = vec![
        cmd(
            "rename_enum_item",
            serde_json::json!({"name": "enum:Rarity", "oldName": "Rare", "newName": "MagicRare", "originalOrdinal": 1}),
        ),
        cmd(
            "set_enum_values",
            serde_json::json!({"name": "enum:Rarity", "values": [{"name": "MagicRare"}, {"name": "Common"}, {"name": "Epic"}]}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    let rarity = diff
        .changes
        .iter()
        .find(|c| c.resource_id() == "enum:Rarity")
        .unwrap();
    assert_eq!(rarity.change, MODIFIED);
    let text = format!("{:?}", rarity.fields);
    assert!(text.contains("ordinal 1 → 0"), "{text}");
    assert!(text.contains("wire 风险"), "{text}");
    assert!(rarity
        .fields
        .iter()
        .any(|f| f.change == ADDED && f.name == "Epic"));
}

#[test]
fn netdiff_field_property_details_sorted() {
    let base = base_state();
    let commands = vec![
        cmd(
            "set_property",
            serde_json::json!({"owner": "table:Item", "name": "Name", "property": "comment", "value": "显示名"}),
        ),
        cmd(
            "set_type",
            serde_json::json!({"owner": "table:Item", "name": "Name", "type_text": "string"}),
        ),
    ];
    let candidate = apply_commands(&base, &commands).unwrap();
    let diff = compute_net_diff(&base, &candidate, &commands, Some(2));
    let item = diff
        .changes
        .iter()
        .find(|c| c.resource_id() == "table:Item")
        .unwrap();
    assert_eq!(item.change, MODIFIED);
    let name_diff = item.fields.iter().find(|f| f.name == "Name").unwrap();
    assert_eq!(name_diff.details, vec!["comment".to_string()]);
}

#[test]
fn generated_name_conflict_detected() {
    let mut state = base_state();
    state.resources.push(table_res("ItemTable", vec![]));
    let merged = merge_indexes(&state.resources, &state.indexes);
    let issues = validate_candidate(&merged, &state.indexes);
    assert!(
        issues.iter().any(|i| i.message.contains("ItemTable")),
        "{issues:?}"
    );
}

#[test]
fn set_enum_values_and_move_field_guards() {
    let mut log = DraftLog::new(base_state());
    // 主键不可删/不可移动
    assert!(log
        .execute(cmd(
            "delete_field",
            serde_json::json!({"owner": "table:Item", "name": "Id"}),
        ))
        .unwrap_err()
        .contains("主键字段 'Id' 不可删除"));
    assert!(log
        .execute(cmd(
            "move_field",
            serde_json::json!({"owner": "table:Item", "name": "Id", "to": 1}),
        ))
        .unwrap_err()
        .contains("主键字段 'Id' 不可调整顺序"));
    // 失败命令不得入队
    assert_eq!(log.commands.len(), 0);

    log.execute(cmd(
        "move_field",
        serde_json::json!({"owner": "table:Item", "name": "Name", "to": 0}),
    ))
    .unwrap();
    let state = log.current().unwrap();
    let names: Vec<&str> = fields_of(&state.resources[0])
        .iter()
        .map(|f| f.name.as_str())
        .collect();
    assert_eq!(names, ["Name", "Id"]);
}

// ---- 测试辅助 ----

fn with_extra_field(resource: &Resource, f: FieldDef) -> Resource {
    match resource {
        Resource::Table(t) => {
            let mut updated = t.clone();
            updated.fields.push(f);
            Resource::Table(updated)
        }
        Resource::Record(r) => {
            let mut updated = r.clone();
            updated.fields.push(f);
            Resource::Record(updated)
        }
        other => other.clone(),
    }
}
