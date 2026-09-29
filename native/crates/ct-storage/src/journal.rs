//! 发布 journal（`<root>/.ct/export-publication.json`，格式 export-publication/1）。
//!
//! 本模块当前提供只读探测（status/validate 报告 pending 用）；
//! 完整的发布/恢复协议在任务 4.x 落地。

use std::path::{Path, PathBuf};

pub const JOURNAL_FORMAT: &str = "export-publication/1";
pub const PRIVATE_DIRNAME: &str = ".ct";
pub const JOURNAL_NAME: &str = "export-publication.json";

pub fn journal_path(root: &Path) -> PathBuf {
    root.join(PRIVATE_DIRNAME).join(JOURNAL_NAME)
}

/// 只读探测：未完成的发布描述；没有则 None；损坏/未知格式返回错误描述。
pub fn pending_publication_note(root: &Path) -> Option<String> {
    if let Some(note) = legacy_apply_note(root) {
        return Some(note);
    }
    let path = journal_path(root);
    if !path.exists() {
        return None;
    }
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(e) => {
            return Some(format!(
                "发布恢复记录读取失败，已保留材料并拒绝继续：{}（{e}）",
                path.display()
            ))
        }
    };
    let data: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(e) => {
            return Some(format!(
                "发布恢复记录损坏，已保留材料并拒绝继续：{}（{e}）",
                path.display()
            ))
        }
    };
    if !data.is_object() || data.get("format").and_then(|f| f.as_str()) != Some(JOURNAL_FORMAT) {
        return Some(format!(
            "发布恢复记录格式未知，已保留材料并拒绝继续：{}",
            path.display()
        ));
    }
    let operation = data
        .get("operation_id")
        .and_then(|v| v.as_str())
        .unwrap_or("?");
    let phase = data.get("phase").and_then(|v| v.as_str()).unwrap_or("?");
    Some(format!(
        "存在未完成的发布（operation {operation}，阶段 {phase}）——下一次 export/deploy 会先恢复，或人工检查 {}",
        path.display()
    ))
}

/// Retired Apply journals cannot be interpreted as an export publication.
/// Keep all evidence and block writes instead of guessing at a recovery plan.
pub fn legacy_apply_note(root: &Path) -> Option<String> {
    let cache = ct_domain::config::GlobalConfig::load(root)
        .map(|c| c.resolve("cache_dir"))
        .unwrap_or_else(|_| root.join("cache"));
    for path in [
        cache.join("apply.journal.json"),
        root.join("cache/apply.journal.json"),
    ] {
        if path.exists() {
            return Some(format!(
                "旧 Apply 事务材料无法可靠还原，已保留并阻止写入：{}",
                path.display()
            ));
        }
    }
    None
}
