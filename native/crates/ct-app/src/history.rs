//! Shared export history. Writes run under the caller's workspace transaction.
use ct_domain::config::GlobalConfig;
use ct_domain::hashing::sha256_hex;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
pub const HISTORY_FORMAT: &str = "desktop-history/1";
pub const MAX_ENTRIES: usize = 5;
#[derive(Debug)]
pub struct HistoryError(pub String);
impl std::fmt::Display for HistoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
fn history_path(cache: &Path) -> PathBuf {
    cache.join("history.json")
}
fn payload(root: &Path) -> Value {
    let data = GlobalConfig::load(root)
        .ok()
        .and_then(|c| std::fs::read(history_path(&c.resolve("cache_dir"))).ok())
        .and_then(|s| serde_json::from_slice::<Value>(&s).ok());
    data.filter(|v| v["format"] == HISTORY_FORMAT)
        .unwrap_or(json!({"format":HISTORY_FORMAT,"entries":[]}))
}
pub fn read_history(root: &Path) -> Vec<Value> {
    payload(root)["entries"]
        .as_array()
        .cloned()
        .unwrap_or_default()
}
fn persist(root: &Path, value: &Value) -> Result<(), HistoryError> {
    let config = GlobalConfig::load(root).map_err(HistoryError)?;
    let path = history_path(&config.resolve("cache_dir"));
    let text = ct_domain::hashing::python_json_pretty(value) + "\n";
    ct_storage::publication::atomic_write(&path, text.as_bytes())
        .map_err(|e| HistoryError(format!("历史写入失败: {e}")))
}
fn normalized_legacy_entry(mut entry: Value) -> Result<Value, HistoryError> {
    let object = entry
        .as_object_mut()
        .ok_or_else(|| HistoryError("旧历史条目不是对象，保留原文件".into()))?;
    for key in ["time", "result"] {
        if !object.get(key).is_some_and(Value::is_string) {
            return Err(HistoryError(format!("旧历史条目缺少 {key}，保留原文件")));
        }
    }
    if object.get("result").and_then(Value::as_str) == Some("成功") {
        object.insert("result".into(), json!("success"));
    }
    if object.get("result").and_then(Value::as_str) != Some("success") {
        return Err(HistoryError("旧历史状态无法识别，保留原文件".into()));
    }
    object.entry("scope").or_insert_with(|| json!("all"));
    object.entry("tables").or_insert_with(|| json!(0));
    object.entry("elapsed").or_insert_with(|| json!(0.0));
    object.entry("forced").or_insert_with(|| json!(false));
    object.entry("error").or_insert_with(|| json!(""));
    // The native worker consumes these fields; rejecting malformed values avoids
    // silently hiding imported entries from the independent history reader.
    let valid = entry["scope"].is_string()
        && entry["tables"]
            .as_u64()
            .is_some_and(|v| v <= u32::MAX as u64)
        && entry["elapsed"].as_f64().is_some()
        && entry["forced"].is_boolean()
        && entry["error"].is_string();
    if !valid {
        return Err(HistoryError("旧历史条目字段无效，保留原文件".into()));
    }
    Ok(entry)
}
fn entry_id(entry: &Value) -> String {
    let stable = json!({
        "time": entry["time"], "scope": entry["scope"], "result": entry["result"],
        "tables": entry["tables"], "elapsed": entry["elapsed"],
        "forced": entry["forced"], "error": entry["error"],
    });
    sha256_hex(stable.to_string().as_bytes())
}
fn merge_legacy(root: &Path, data: &mut Value) -> Result<bool, HistoryError> {
    if data["legacyPanelImported"].as_bool() == Some(true) {
        return Ok(false);
    }
    let config = GlobalConfig::load(root).map_err(HistoryError)?;
    // Python panel used root/cache even when export used a custom cache_dir.
    let mut paths = vec![
        root.join("cache/panel_history.json"),
        config.resolve("cache_dir").join("panel_history.json"),
    ];
    paths.sort();
    paths.dedup();
    let mut entries = data["entries"].as_array().cloned().unwrap_or_default();
    let mut ids: HashSet<_> = entries.iter().map(entry_id).collect();
    let mut imported_ids = Vec::new();
    let mut sources = Vec::new();
    let mut found = false;
    for path in paths {
        if !path.exists() {
            continue;
        }
        found = true;
        let bytes =
            std::fs::read(&path).map_err(|e| HistoryError(format!("旧历史读取失败: {e}")))?;
        let old: Vec<Value> = serde_json::from_slice(&bytes)
            .map_err(|e| HistoryError(format!("旧历史格式损坏，保留原文件: {e}")))?;
        sources.push(json!({
            "path": path.strip_prefix(root).unwrap_or(&path).to_string_lossy().replace('\\', "/"),
            "sha256": sha256_hex(&bytes),
            "entries": old.len(),
        }));
        for raw in old {
            let entry = normalized_legacy_entry(raw)?;
            let id = entry_id(&entry);
            if ids.insert(id.clone()) {
                imported_ids.push(id);
                entries.push(entry);
            }
        }
    }
    if !found {
        return Ok(false);
    }
    entries.sort_by_key(|entry| std::cmp::Reverse(entry_time(entry)));
    entries.truncate(MAX_ENTRIES);
    data["entries"] = json!(entries);
    data["legacyPanelImported"] = true.into();
    data["legacyPanelSources"] = json!(sources);
    data["legacyPanelEntryIds"] = json!(imported_ids);
    Ok(true)
}
/// Idempotent import with marker and entries in one atomic file. Caller holds lock.
pub fn import_legacy_history(root: &Path) -> Result<(), HistoryError> {
    let mut data = payload(root);
    if merge_legacy(root, &mut data)? {
        persist(root, &data)?
    }
    Ok(())
}
pub fn append_history(root: &Path, entry: Value) -> Result<(), HistoryError> {
    let mut data = payload(root);
    // Bad legacy data must not prevent recording a successful native export.
    let warning = merge_legacy(root, &mut data).err();
    let mut entries = data["entries"].as_array().cloned().unwrap_or_default();
    let new_id = entry_id(&entry);
    // Replace one matching imported record, but keep distinct native exports
    // even when their second-precision timestamps and other fields match.
    if let Some(imported) = data["legacyPanelEntryIds"].as_array_mut() {
        if let Some(index) = imported
            .iter()
            .position(|id| id.as_str() == Some(new_id.as_str()))
        {
            if let Some(position) = entries.iter().position(|old| entry_id(old) == new_id) {
                entries.remove(position);
            }
            imported.remove(index);
        }
    }
    entries.insert(0, entry);
    entries.truncate(MAX_ENTRIES);
    data["entries"] = json!(entries);
    persist(root, &data)?;
    if let Some(warning) = warning {
        return Err(warning);
    }
    Ok(())
}

fn entry_time(entry: &Value) -> i64 {
    use chrono::TimeZone;
    let time = entry["time"].as_str().unwrap_or("");
    chrono::DateTime::parse_from_rfc3339(time)
        .map(|t| t.timestamp())
        .ok()
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(time, "%Y-%m-%d %H:%M:%S")
                .ok()
                .and_then(|t| chrono::Local.from_local_datetime(&t).earliest())
                .map(|t| t.timestamp())
        })
        .unwrap_or(0)
}
