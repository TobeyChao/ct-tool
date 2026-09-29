//! Schema revision / YAML-only 保存对照（rust-native-core 任务 3.11）：
//! 旧基线拒绝、candidateHash 守卫、目录成员变化、事务失败保留原文件、
//! 无变化保存不重排 YAML、Excel 路径归属冲突拒绝。

use std::path::Path;

use ct_app::schema::{
    build_schema_revision, capture_schema_contents, plan_yaml_save, publish_yaml_save,
    resource_target_path, SchemaSession,
};
use ct_domain::commands::Command;
use ct_domain::netdiff::MODIFIED;
use ct_domain::repository::Resource;

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    // 与仓库一致的 LF 字节（YAML 内容哈希依赖原始字节）
    std::fs::write(path, content.replace("\r\n", "\n")).unwrap();
}

fn read(path: &Path) -> Vec<u8> {
    std::fs::read(path).unwrap()
}

/// 标准临时工作区：Item（带索引/i18n/ref）+ Monster + DropRule + Rarity。
fn setup() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(
        &root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\n",
    );
    write(
        &root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\nindexes:\n  - kind: codename\n",
    );
    write(
        &root.join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Common\n",
    );
    dir
}

fn cmd(kind: &str, payload: serde_json::Value) -> Command {
    Command::new(kind, payload)
}

#[test]
fn revision_tracks_directory_membership() {
    let dir = setup();
    let root = dir.path();
    let config = ct_domain::config::GlobalConfig::load(root).unwrap();
    let before = build_schema_revision(&config, &capture_schema_contents(&config));

    // 新增成员
    write(
        &root.join("config/types/bonus.yaml"),
        "kind: record\nname: Bonus\nfields:\n  - name: Rate\n    type: float\n",
    );
    let after_add = build_schema_revision(&config, &capture_schema_contents(&config));
    assert_ne!(before.revision, after_add.revision);
    assert_eq!(
        after_add.changed_members(&before),
        vec!["types/bonus.yaml".to_string()]
    );

    // 编辑成员
    write(
        &root.join("config/types/bonus.yaml"),
        "kind: record\nname: Bonus\nfields:\n  - name: Rate\n    type: float\n  - name: Cap\n    type: int32\n",
    );
    let after_edit = build_schema_revision(&config, &capture_schema_contents(&config));
    assert_ne!(after_add.revision, after_edit.revision);
    assert_eq!(
        after_edit.changed_members(&after_add),
        vec!["types/bonus.yaml".to_string()]
    );

    // 删除成员
    std::fs::remove_file(root.join("config/types/bonus.yaml")).unwrap();
    let after_delete = build_schema_revision(&config, &capture_schema_contents(&config));
    assert_eq!(before.revision, after_delete.revision);

    // 配置本身也是基线的一部分
    write(&root.join("config/global.yaml"), "primary_lang: zh\n");
    let after_config = build_schema_revision(&config, &capture_schema_contents(&config));
    assert_ne!(after_delete.revision, after_config.revision);
}

#[test]
fn save_stale_revision_rejected_and_untouched() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let item_before = read(&root.join("config/schemas/item.yaml"));

    let rejection = session
        .save(
            "sha256:stale",
            "abc",
            &[cmd(
                "add_field",
                serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
            )],
            1,
        )
        .unwrap_err();
    assert_eq!(rejection.kind, "schema-revision");
    assert_eq!(read(&root.join("config/schemas/item.yaml")), item_before);
}

#[test]
fn save_bad_candidate_hash_rejected() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let revision = session.revision.revision.clone();
    let commands = vec![cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
    )];
    let rejection = session
        .save(&revision, "sha256:wrong", &commands, 1)
        .unwrap_err();
    assert_eq!(rejection.kind, "candidate-hash");
}

#[test]
fn save_writes_only_changed_yaml() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let rarity_before = read(&root.join("config/types/rarity.yaml"));
    let rarity_mtime = std::fs::metadata(root.join("config/types/rarity.yaml"))
        .unwrap()
        .modified()
        .unwrap();

    let commands = vec![cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();
    assert!(candidate.issues.is_empty(), "{:?}", candidate.issues);
    let outcome = session
        .save(
            &session.revision.revision.clone(),
            &candidate.hash,
            &commands,
            1,
        )
        .unwrap();
    assert!(!outcome.is_no_op);
    assert_eq!(outcome.written.len(), 1);
    assert!(outcome.written[0].ends_with("item.yaml"));

    // 新内容包含新字段；未变化的 rarity.yaml 字节与 mtime 均不变
    let item_text = String::from_utf8(read(&root.join("config/schemas/item.yaml"))).unwrap();
    assert!(item_text.contains("name: Price"), "{item_text}");
    assert_eq!(read(&root.join("config/types/rarity.yaml")), rarity_before);
    assert_eq!(
        std::fs::metadata(root.join("config/types/rarity.yaml"))
            .unwrap()
            .modified()
            .unwrap(),
        rarity_mtime
    );
    // 不遗留 journal / 暂存（.ct 空目录与 Python 行为一致），也不碰 Excel/翻译/产物
    assert!(!root.join(".ct/export-publication.json").exists());
    let backup_dir = root.join(".ct/backup");
    if backup_dir.exists() {
        // Python 只清理 operation 子目录，backup 空壳目录允许残留
        assert_eq!(std::fs::read_dir(&backup_dir).unwrap().count(), 0);
    }
    assert!(!root.join("excel").exists());
    assert!(!root.join("output").exists());

    // 保存后 revision 推进，可作为新基线继续保存
    let session2 = SchemaSession::open(&root).unwrap();
    assert_eq!(
        session2.revision.to_payload(),
        outcome.revision.to_payload(),
        "members: {:?} vs {:?}",
        session2.revision.members,
        outcome.revision.members
    );
}

#[test]
fn save_noop_touches_nothing() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let candidate = session.candidate(&[], 0).unwrap();
    let outcome = session
        .save(&session.revision.revision.clone(), &candidate.hash, &[], 0)
        .unwrap();
    assert!(outcome.is_no_op);
    assert_eq!(outcome.changed_resources, 0);
    assert!(!root.join(".ct").exists(), "空保存不得创建 journal");
}

#[test]
fn candidate_counts_index_only_change() {
    let dir = setup();
    let session = SchemaSession::open(dir.path()).unwrap();
    let commands = vec![cmd(
        "set_indexes",
        serde_json::json!({"table": "table:Item", "indexes": []}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();

    assert!(candidate.issues.is_empty(), "{:?}", candidate.issues);
    assert_eq!(
        candidate.net_diff.changed_resources(),
        1,
        "只移除 codename 索引也必须进入净差异"
    );
    let change = &candidate.net_diff.changes[0];
    assert_eq!(change.kind, "table");
    assert_eq!(change.name, "Item");
    assert_eq!(change.change, MODIFIED);
}

#[test]
fn save_delete_and_rename_move_files() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let commands = vec![
        cmd(
            "rename_resource",
            serde_json::json!({"old": "Rarity", "new": "Quality"}),
        ),
        cmd("delete_resource", serde_json::json!({"name": "table:Item"})),
    ];
    let candidate = session.candidate(&commands, 2).unwrap();
    // Item 删除后 Rarity 仍被引用？此处 Item 不引用 Rarity，校验应通过
    assert!(candidate.issues.is_empty(), "{:?}", candidate.issues);
    let outcome = session
        .save(
            &session.revision.revision.clone(),
            &candidate.hash,
            &commands,
            2,
        )
        .unwrap();
    assert!(outcome.deleted.iter().any(|p| p.ends_with("item.yaml")));
    assert!(outcome.deleted.iter().any(|p| p.ends_with("rarity.yaml")));
    assert!(outcome.written.iter().any(|p| p.ends_with("Quality.yaml")));
    assert!(!root.join("config/schemas/item.yaml").exists());
    assert!(!root.join("config/types/rarity.yaml").exists());
    assert!(root.join("config/types/Quality.yaml").exists());
}

#[test]
fn save_with_candidate_issues_rejected() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    // 引用不存在的具名类型
    let commands = vec![cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Bad", "type": "NoSuchType"}}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();
    assert!(!candidate.issues.is_empty());
    let rejection = session
        .save(
            &session.revision.revision.clone(),
            &candidate.hash,
            &commands,
            1,
        )
        .unwrap_err();
    assert_eq!(rejection.kind, "issues");
    assert!(rejection.details.issues[0].message.contains("具名类型"));
}

#[test]
fn transaction_failure_preserves_original_files() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let session = SchemaSession::open(&root).unwrap();
    let item_before = read(&root.join("config/schemas/item.yaml"));

    // 构造两份写入：item.yaml（覆盖）+ types/fail.yaml（目标是目录 → rename 失败）
    let item_resource = session
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Item")
        .unwrap()
        .clone();
    let new_item = match &item_resource {
        Resource::Table(t) => {
            let mut t = t.clone();
            t.fields.push(ct_domain::schema::FieldDef {
                name: "Price".into(),
                type_expr: ct_domain::types::TypeExpr::parse("int32").unwrap(),
                i18n: false,
                ref_: None,
                server_only: false,
                comment: String::new(),
                excel_columns: None,
            });
            Resource::Table(t)
        }
        other => other.clone(),
    };
    let fail_dir = root.join("config/types/fail.yaml");
    std::fs::create_dir_all(&fail_dir).unwrap();

    let known = session.known_sources.clone();
    let mut plan = plan_yaml_save(&session.config, &[new_item], &known);
    // 手动加入必败的写入（绕过业务校验，只测事务回滚）
    plan.writes
        .insert(fail_dir.clone(), b"kind: record\n".to_vec());
    // BTreeMap 按键排序：config/schemas/item.yaml 在 config/types/fail.yaml 之前应用，
    // 因此 fail 处失败时 item 必须已被覆盖——用来验证回滚恢复。

    let result = publish_yaml_save(&root, &plan);
    assert!(result.is_err(), "目标为目录必须失败");
    // 原文件内容保留（已回滚），目录仍是目录，journal 已清理
    assert_eq!(read(&root.join("config/schemas/item.yaml")), item_before);
    assert!(fail_dir.is_dir());
    assert!(
        root.join("config/types/rarity.yaml").exists(),
        "删除的文件应被回滚恢复"
    );
    assert!(!root.join(".ct/export-publication.json").exists());
}

#[test]
fn excel_path_conflict_rejected() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    // 两个 Table 指向同一工作簿（仅大小写不同也算冲突）
    write(
        &root.join("config/schemas/extra.yaml"),
        "table: Extra\nprimary: Id\nexcel_file: ITEM.xlsx\nfields:\n  - name: Id\n    type: int32\n",
    );
    let session = SchemaSession::open(&root).unwrap();
    let candidate = session.candidate(&[], 0).unwrap();
    assert!(candidate.issues.is_empty(), "{:?}", candidate.issues);
    // 无净变化 → is_no_op；先制造一次变化以走到 plan 阶段：
    let commands = vec![cmd(
        "set_property",
        serde_json::json!({"owner": "table:Item", "name": "CodeName", "property": "comment", "value": "编码"}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();
    let rejection = session
        .save(
            &session.revision.revision.clone(),
            &candidate.hash,
            &commands,
            1,
        )
        .unwrap_err();
    assert_eq!(rejection.kind, "target");
    assert!(
        rejection.message.contains("同一 Excel 路径"),
        "{}",
        rejection.message
    );
}

#[test]
fn unchanged_content_not_rewritten_despite_formatting_drift() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    // 用不同键序与显式默认值重写 rarity.yaml：业务内容相同
    write(
        &root.join("config/types/rarity.yaml"),
        "kind: enum\ncomment: \"\"\nname: Rarity\nvalues:\n  - name: Common\n    comment: \"\"\n",
    );
    let session = SchemaSession::open(&root).unwrap();
    let before = read(&root.join("config/types/rarity.yaml"));
    let candidate = session.candidate(&[], 0).unwrap();
    let outcome = session
        .save(&session.revision.revision.clone(), &candidate.hash, &[], 0)
        .unwrap();
    assert!(outcome.is_no_op);
    // 内容等价 → 不重排、不改写（字节保持用户原样）
    assert_eq!(read(&root.join("config/types/rarity.yaml")), before);
    assert!(outcome.unchanged.iter().any(|p| p.ends_with("rarity.yaml")));
}

#[test]
fn resource_target_path_uses_kind_directories() {
    let dir = setup();
    let session = SchemaSession::open(dir.path()).unwrap();
    let table = session
        .resources
        .iter()
        .find(|r| r.resource_id() == "table:Item")
        .unwrap();
    let enum_ = session
        .resources
        .iter()
        .find(|r| r.resource_id() == "enum:Rarity")
        .unwrap();
    let table_path = resource_target_path(&session.config, table, &session.known_sources);
    let enum_path = resource_target_path(&session.config, enum_, &session.known_sources);
    assert!(table_path.ends_with("schemas/item.yaml"));
    assert!(enum_path.ends_with("types/rarity.yaml"));
}

#[test]
fn save_workspace_busy_and_recovery() {
    let dir = setup();
    let root = dir.path().to_path_buf();

    // 事务外持锁 → busy
    let hold = ct_storage::lock::WorkspaceLock::acquire(&root).unwrap();
    let err = ct_app::schema::save_workspace(&root, "x", "y", &[], 0).unwrap_err();
    assert_eq!(err.kind, "busy");
    drop(hold);

    // 中断现场（publishing + 备份）→ 保存入口先恢复再工作
    let target = root.join("config/schemas/item.yaml");
    let original = read(&target);
    let backup_dir = root.join(".ct/backup/op-save");
    std::fs::create_dir_all(&backup_dir).unwrap();
    let backup = backup_dir.join("1-item.yaml");
    std::fs::write(&backup, &original).unwrap();
    std::fs::write(&target, b"corrupted\n").unwrap();
    let journal = serde_json::json!({
        "format": "export-publication/1",
        "operation_id": "op-save",
        "root": root.to_string_lossy(),
        "phase": "publishing",
        "allowed_dirs": [root.join("config/schemas").to_string_lossy()],
        "entries": [{
            "path": target.to_string_lossy(),
            "op": "replace",
            "existed": true,
            "backup": backup.to_string_lossy(),
            "done": false
        }],
    });
    std::fs::write(
        root.join(".ct/export-publication.json"),
        serde_json::to_string_pretty(&journal).unwrap(),
    )
    .unwrap();

    // 恢复后基线 = 恢复现场；携带现场前 revision 的保存被拒绝
    let err = ct_app::schema::save_workspace(&root, "sha256:pre-crash", "y", &[], 0).unwrap_err();
    assert_eq!(err.kind, "schema-revision");
    assert_eq!(read(&target), original, "恢复应先回滚到备份内容");
    assert!(!root.join(".ct/export-publication.json").exists());

    // 基线一致的正常保存成功
    let session = SchemaSession::open(&root).unwrap();
    let commands = vec![cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();
    let (outcome, recovery) = ct_app::schema::save_workspace(
        &root,
        &session.revision.revision,
        &candidate.hash,
        &commands,
        1,
    )
    .unwrap();
    assert!(!outcome.is_no_op);
    assert!(recovery.is_none());
}

#[test]
fn recovery_changes_baseline_and_rejects_pre_recovery_draft() {
    let dir = setup();
    let root = dir.path().to_path_buf();

    // 中断的发布事务：本次新增 types/extra.yaml 已落盘（journal 记 create/未备份）
    let added = root.join("config/types/extra.yaml");
    std::fs::write(
        &added,
        "kind: record\nname: Extra\nfields:\n  - name: Id\n    type: int32\n",
    )
    .unwrap();
    let backup_dir = root.join(".ct/backup/op-recover");
    std::fs::create_dir_all(&backup_dir).unwrap();
    let journal = serde_json::json!({
        "format": "export-publication/1",
        "operation_id": "op-recover",
        "root": root.to_string_lossy(),
        "phase": "publishing",
        "allowed_dirs": [root.join("config/types").to_string_lossy()],
        "entries": [{
            "path": added.to_string_lossy(),
            "op": "create",
            "existed": false,
            "done": true
        }],
    });
    std::fs::write(
        root.join(".ct/export-publication.json"),
        serde_json::to_string_pretty(&journal).unwrap(),
    )
    .unwrap();

    // 客户端在恢复前读到的（混合状态）基线
    let mixed = SchemaSession::open(&root)
        .unwrap()
        .revision
        .revision
        .clone();

    // 恢复：清理本事务新增文件，基线随之变化
    let report = ct_app::workspace::recover_workspace(&root).unwrap();
    assert!(report.note.is_some());
    assert!(!added.exists(), "本事务新增文件必须被清理");
    assert_ne!(report.revision, mixed, "恢复后基线必须不同于恢复前快照");

    // 携带恢复前基线的保存必须被拒绝，且不再改动文件
    let item = root.join("config/schemas/item.yaml");
    let before = read(&item);
    let session = SchemaSession::open(&root).unwrap();
    let commands = vec![cmd(
        "add_field",
        serde_json::json!({"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}),
    )];
    let candidate = session.candidate(&commands, 1).unwrap();
    let err =
        ct_app::schema::save_workspace(&root, &mixed, &candidate.hash, &commands, 1).unwrap_err();
    assert_eq!(err.kind, "schema-revision");
    assert_eq!(read(&item), before, "被拒绝的保存不得改动文件");
}
