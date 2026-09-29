//! 工作区锁与事务入口对照（rust-native-core 任务 4.1）：
//! 进程内互斥、跨进程互斥、进程死亡释放、事务先恢复、Python 锁区间互斥。

use std::path::Path;

use ct_storage::lock::WorkspaceLock;
use ct_storage::workspace::{TransactionError, WorkspaceTransaction};

fn temp_root() -> tempfile::TempDir {
    tempfile::tempdir().unwrap()
}

/// 子进程模式：持锁并写就绪标记后睡眠（父进程负责 kill）。
#[test]
fn child_holds_lock() {
    let Ok(root) = std::env::var("CT_LOCK_ROOT") else {
        return; // 父进程模式下直接跳过
    };
    let lock = WorkspaceLock::acquire(Path::new(&root)).expect("子进程应能拿到锁");
    std::fs::write(Path::new(&root).join(".ct/child-ready"), b"1").unwrap();
    let _ = lock;
    std::thread::sleep(std::time::Duration::from_secs(60));
}

#[test]
fn in_process_mutual_exclusion() {
    let dir = temp_root();
    let first = WorkspaceLock::acquire(dir.path()).unwrap();
    assert!(first.held());
    let busy = WorkspaceLock::acquire(dir.path()).unwrap_err();
    assert!(busy.0.contains("请稍后重试"), "{}", busy.0);
    // 锁文件不随 cache_dir 变化
    assert!(dir.path().join(".ct/export.lock").exists());
    drop(first);
    // 释放后可再次获取
    let second = WorkspaceLock::acquire(dir.path()).unwrap();
    assert!(second.held());
}

#[test]
fn different_roots_are_independent() {
    let a = temp_root();
    let b = temp_root();
    let _la = WorkspaceLock::acquire(a.path()).unwrap();
    let lb = WorkspaceLock::acquire(b.path());
    assert!(lb.is_ok(), "不同工作区不得互斥: {:?}", lb.err());
}

#[test]
fn cross_process_busy_and_death_release() {
    if std::env::var("CT_LOCK_ROOT").is_ok() {
        return; // 子进程分支由 child_holds_lock 处理
    }
    let dir = temp_root();
    let root = dir.path();
    let child = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["child_holds_lock", "--exact", "--nocapture"])
        .env("CT_LOCK_ROOT", root)
        .spawn()
        .unwrap();
    let mut child = child;
    // 等子进程持锁
    let ready = root.join(".ct/child-ready");
    for _ in 0..200 {
        if ready.exists() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(25));
    }
    assert!(ready.exists(), "子进程未能持锁");

    let busy = WorkspaceLock::acquire(root).unwrap_err();
    assert!(busy.0.contains("请稍后重试"));

    // 杀死持锁进程 → 系统释放 → 可获取
    child.kill().unwrap();
    child.wait().unwrap();
    let lock = WorkspaceLock::acquire(root);
    assert!(lock.is_ok(), "进程死亡后锁应被系统释放: {:?}", lock.err());
}

#[test]
fn transaction_recovers_pending_publish_before_work() {
    let dir = temp_root();
    let root = dir.path();
    // 手工构造一个 publishing 阶段的中断现场：原文件被覆盖、备份在
    let config_dir = root.join("config/schemas");
    std::fs::create_dir_all(&config_dir).unwrap();
    let target = config_dir.join("item.yaml");
    std::fs::write(&target, b"table: Item\n").unwrap();
    let backup_dir = root.join(".ct/backup/op-test");
    std::fs::create_dir_all(&backup_dir).unwrap();
    let backup = backup_dir.join("1-item.yaml");
    std::fs::write(&backup, b"table: Item\n").unwrap();
    std::fs::write(&target, b"corrupted-during-crash\n").unwrap();
    let journal = serde_json::json!({
        "format": "export-publication/1",
        "operation_id": "op-test",
        "root": root.to_string_lossy(),
        "phase": "publishing",
        "allowed_dirs": [config_dir.to_string_lossy()],
        "entries": [{
            "path": target.to_string_lossy(),
            "op": "replace",
            "existed": true,
            "old_hash": null,
            "backup": backup.to_string_lossy(),
            "done": false
        }],
    });
    std::fs::write(
        root.join(".ct/export-publication.json"),
        serde_json::to_string_pretty(&journal).unwrap(),
    )
    .unwrap();

    let tx = WorkspaceTransaction::begin(root).unwrap();
    assert!(tx.recovery.is_some(), "应报告恢复");
    assert!(tx.recovery.as_ref().unwrap().contains("已回滚"));
    // 恢复完成：文件回到备份内容，journal 清理
    assert_eq!(std::fs::read(&target).unwrap(), b"table: Item\n");
    assert!(!root.join(".ct/export-publication.json").exists());
    drop(tx);
    // 事务释放后可再次进入
    let tx2 = WorkspaceTransaction::begin(root).unwrap();
    assert!(tx2.recovery.is_none());
}

#[test]
fn transaction_reports_busy() {
    let dir = temp_root();
    let _hold = WorkspaceLock::acquire(dir.path()).unwrap();
    let err = WorkspaceTransaction::begin(dir.path()).unwrap_err();
    assert!(matches!(err, TransactionError::Busy(_)));
}
