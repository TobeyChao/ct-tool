//! 可恢复发布的各阶段故障注入对照（rust-native-core 任务 4.2）：
//! prepared/backed_up/publishing/committed 各阶段中断后的恢复语义、
//! 旧文件内容与 mtime 还原、新增文件清理、备份缺失保留材料。

use std::collections::BTreeMap;
use std::path::Path;

use ct_storage::publication::{sha256_hex, FilePublisher, PublicationEntry, PublicationJournal};

fn write(path: &Path, content: &[u8]) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content).unwrap();
}

fn mtime_secs(path: &Path) -> u64 {
    std::fs::metadata(path)
        .unwrap()
        .modified()
        .unwrap()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
}

fn set_mtime(path: &Path, secs: u64) {
    let file = std::fs::File::options().write(true).open(path).unwrap();
    file.set_modified(std::time::UNIX_EPOCH + std::time::Duration::from_secs(secs))
        .unwrap();
}

fn journal_fixture(root: &Path, phase: &str, entries: Vec<PublicationEntry>) {
    let journal = PublicationJournal {
        format: "export-publication/1".to_string(),
        operation_id: "op-test".to_string(),
        root: root.to_string_lossy().to_string(),
        phase: phase.to_string(),
        allowed_dirs: vec![root.join("out").to_string_lossy().to_string()],
        entries,
    };
    write(
        &root.join(".ct/export-publication.json"),
        serde_json::to_string_pretty(&journal).unwrap().as_bytes(),
    );
}

fn entry(
    root: &Path,
    name: &str,
    op: &str,
    existed: bool,
    backup: Option<&Path>,
    done: bool,
) -> PublicationEntry {
    PublicationEntry {
        path: root.join("out").join(name).to_string_lossy().to_string(),
        op: op.to_string(),
        existed,
        old_hash: None,
        old_mtime: None,
        new_hash: None,
        staged: None,
        backup: backup.map(|b| b.to_string_lossy().to_string()),
        done,
    }
}

#[test]
fn crash_after_prepared_cleans_private_only() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("out/old.yaml"), b"original");
    // 崩溃现场：目标已写定，但私有暂存文件还躺在产物目录里
    let staged = root.join("out/.ct-stage-op-test-old.yaml");
    write(&staged, b"pending-new-content");
    let mut pending = entry(root, "old.yaml", "replace", true, None, false);
    pending.staged = Some(staged.to_string_lossy().to_string());
    journal_fixture(root, "prepared", vec![pending]);

    let note = FilePublisher::new(root).recover().unwrap();
    assert!(note.unwrap().contains("仅清理私有材料"));
    assert_eq!(
        std::fs::read(root.join("out/old.yaml")).unwrap(),
        b"original",
        "prepared 阶段中断不得碰正式文件"
    );
    assert!(
        !staged.exists(),
        "恢复必须清掉本次记入 journal 的私有暂存文件，否则产物目录会永久残留"
    );
    assert!(!root.join(".ct/export-publication.json").exists());
}

#[test]
fn crash_mid_publish_restores_content_and_mtime_and_removes_created() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    // 现场：old.yaml 已被覆盖（崩溃在 publishing 中途），new.yaml 已被创建
    write(&root.join("out/old.yaml"), b"overwritten-by-crash");
    write(&root.join("out/new.yaml"), b"created-by-crash");
    // 备份：old.yaml 原始内容 + 固定 mtime
    let backup_dir = root.join(".ct/backup/op-test");
    let backup = backup_dir.join("1-old.yaml");
    write(&backup, b"original-content");
    let original_mtime = 1_700_000_000;

    let mut replaced = entry(root, "old.yaml", "replace", true, Some(&backup), true);
    replaced.old_mtime = Some(original_mtime);
    let created = entry(root, "new.yaml", "create", false, None, true);
    journal_fixture(root, "publishing", vec![replaced, created]);

    let note = FilePublisher::new(root).recover().unwrap();
    assert!(note.unwrap().contains("已回滚"));
    assert_eq!(
        std::fs::read(root.join("out/old.yaml")).unwrap(),
        b"original-content"
    );
    assert_eq!(mtime_secs(&root.join("out/old.yaml")), original_mtime);
    assert!(
        !root.join("out/new.yaml").exists(),
        "本事务新增文件必须清理"
    );
    assert!(!root.join(".ct/export-publication.json").exists());
    assert!(!backup_dir.exists(), "恢复材料应被清理");
}

#[test]
fn crash_after_committed_keeps_new_version() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("out/old.yaml"), b"new-version");
    let backup = root.join(".ct/backup/op-test/1-old.yaml");
    write(&backup, b"original");
    journal_fixture(
        root,
        "committed",
        vec![entry(
            root,
            "old.yaml",
            "replace",
            true,
            Some(&backup),
            true,
        )],
    );

    let note = FilePublisher::new(root).recover().unwrap();
    assert!(note.unwrap().contains("已提交"));
    assert_eq!(
        std::fs::read(root.join("out/old.yaml")).unwrap(),
        b"new-version"
    );
    assert!(!root.join(".ct/export-publication.json").exists());
}

#[test]
fn missing_backup_keeps_materials_and_blocks() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("out/old.yaml"), b"overwritten-by-crash");
    let missing = root.join(".ct/backup/op-test/1-old.yaml");
    journal_fixture(
        root,
        "publishing",
        vec![entry(
            root,
            "old.yaml",
            "replace",
            true,
            Some(&missing),
            false,
        )],
    );

    let err = FilePublisher::new(root).recover().unwrap_err();
    assert!(err.0.contains("备份缺失"), "{}", err.0);
    // 材料全部保留：journal、现状文件都不动
    assert!(root.join(".ct/export-publication.json").exists());
    assert_eq!(
        std::fs::read(root.join("out/old.yaml")).unwrap(),
        b"overwritten-by-crash"
    );
    // 幂等：再次 recover 仍报同样错误，不会吞掉材料
    assert!(FilePublisher::new(root).recover().is_err());
}

#[test]
fn publish_failure_rolls_back_with_mtime() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let target = root.join("out/old.yaml");
    write(&target, b"original");
    set_mtime(&target, 1_700_000_000);
    // 必败目标：同批写入中 fail.yaml 是目录
    let fail = root.join("out/fail.yaml");
    std::fs::create_dir_all(&fail).unwrap();

    let mut writes = BTreeMap::new();
    writes.insert(target.clone(), b"new-content".to_vec());
    writes.insert(fail.clone(), b"never".to_vec());

    let result = FilePublisher::new(root).publish(&writes, &[]);
    assert!(result.is_err());
    assert_eq!(std::fs::read(&target).unwrap(), b"original");
    assert_eq!(mtime_secs(&target), 1_700_000_000, "mtime 应一并还原");
    assert!(fail.is_dir());
    assert!(
        !root.join(".ct/export-publication.json").exists(),
        "回滚成功应清理 journal"
    );
}

#[test]
fn publish_then_recover_is_noop() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let mut writes = BTreeMap::new();
    writes.insert(root.join("out/a.yaml"), b"a".to_vec());
    FilePublisher::new(root).publish(&writes, &[]).unwrap();
    assert_eq!(FilePublisher::new(root).recover().unwrap(), None);
    assert_eq!(std::fs::read(root.join("out/a.yaml")).unwrap(), b"a");
}

#[test]
fn out_of_scope_journal_path_rejected() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let mut e = entry(root, "old.yaml", "replace", true, None, false);
    e.path = "C:/Windows/evil.yaml".to_string();
    journal_fixture(root, "publishing", vec![e]);
    let err = FilePublisher::new(root).recover().unwrap_err();
    assert!(err.0.contains("越界路径"), "{}", err.0);
    assert!(root.join(".ct/export-publication.json").exists());
}

/// 写穿暂存：`stage_private` 只落私有暂存文件，绝不提前创建/改动正式目标。
#[test]
fn staged_payload_does_not_touch_targets() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let publisher = FilePublisher::new(root);
    let target = root.join("out").join("a.json");
    let payload = publisher
        .stage_private("op-spill", &target, b"{\"a\":1}")
        .unwrap();
    assert!(!target.exists(), "写穿不该创建正式文件");
    assert!(payload.staged.is_file());
    assert!(
        payload.staged.starts_with(root.join(".ct")),
        "暂存必须在私有目录下"
    );
    assert_eq!(payload.bytes, 7);
    assert_eq!(payload.new_hash, sha256_hex(b"{\"a\":1}"));

    publisher
        .publish_staged("op-spill", &[(target.clone(), payload)], &[])
        .unwrap();
    assert_eq!(std::fs::read(&target).unwrap(), b"{\"a\":1}");
    assert!(
        !root.join(".ct").join("publication.json").exists(),
        "成功提交后不留 journal"
    );
}

/// 未发布的暂存可以被整体丢弃，正式文件一个都不动。
#[test]
fn dropping_staged_payloads_leaves_targets_untouched() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let publisher = FilePublisher::new(root);
    let a = root.join("out").join("a.json");
    let b = root.join("out").join("b.json");
    write(&a, b"old-a");
    let first = publisher.stage_private("op-drop", &a, b"new-a").unwrap();
    let second = publisher.stage_private("op-drop", &b, b"new-b").unwrap();
    publisher.drop_staged(&[first.staged, second.staged]);
    assert_eq!(
        std::fs::read(&a).unwrap(),
        b"old-a",
        "被丢弃的发布不得改到正式文件"
    );
    assert!(!b.exists());
    assert_eq!(
        publisher.sweep_staging().unwrap(),
        0,
        "已丢弃就不该再有残留"
    );
}

/// 崩溃残留的私有暂存：没有 journal 时清扫；有 journal 时绝不动（恢复要用）。
#[test]
fn sweep_staging_respects_journal() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    let publisher = FilePublisher::new(root);
    let target = root.join("out").join("c.json");
    let staged = publisher.stage_private("op-sweep", &target, b"x").unwrap();
    assert_eq!(publisher.sweep_staging().unwrap(), 1);
    assert!(!staged.staged.exists(), "无 journal 时崩溃残留应被清走");

    let kept = publisher.stage_private("op-keep", &target, b"y").unwrap();
    journal_fixture(
        root,
        "prepared",
        vec![PublicationEntry {
            path: target.to_string_lossy().to_string(),
            op: "create".to_string(),
            existed: false,
            old_hash: None,
            old_mtime: None,
            new_hash: Some(kept.new_hash.clone()),
            staged: Some(kept.staged.to_string_lossy().to_string()),
            backup: None,
            done: false,
        }],
    );
    assert_eq!(
        publisher.sweep_staging().unwrap(),
        0,
        "有 journal 时必须留给恢复处理"
    );
    assert!(kept.staged.is_file());
}

#[test]
fn atomic_write_replaces_target_while_reader_has_it_open() {
    let temp = tempfile::tempdir().unwrap();
    let target = temp.path().join("journal.json");
    std::fs::write(&target, b"old").unwrap();
    let reader = std::fs::File::open(&target).unwrap();
    ct_storage::publication::atomic_write(&target, b"new").unwrap();
    assert_eq!(std::fs::read(&target).unwrap(), b"new");
    drop(reader);
    assert_eq!(std::fs::read_dir(temp.path()).unwrap().count(), 1);
}
