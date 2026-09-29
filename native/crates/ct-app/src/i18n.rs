//! i18n 用例（`ct/app/canonical_commands.py` 的 i18n 段）：
//! sync / status / compact / entries。

use std::collections::HashMap;
use std::path::PathBuf;

use ct_domain::schema::SchemaError;
use ct_excel::canonical::{read_canonical_rows, rows_from_probe};
use ct_excel::layout::build_layout;
use ct_excel::reader::probe_xlsx;
use ct_export::i18n::{
    compute_status, serialize_i18n_object, serialize_source_object, sync_lang_table, LangStatus,
};
use serde_json::{Map, Value};

use crate::workspace::Workspace;

fn i18n_dir(ws: &Workspace) -> PathBuf {
    ws.config.resolve("i18n_dir")
}

fn load_json_map(path: &PathBuf) -> HashMap<String, Map<String, Value>> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return HashMap::new();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

fn stage_if_changed(
    writes: &mut std::collections::BTreeMap<PathBuf, Vec<u8>>,
    path: &PathBuf,
    content: &str,
) {
    if std::fs::read(path).ok().as_deref() != Some(content.as_bytes()) {
        writes.insert(path.clone(), content.as_bytes().to_vec());
    }
}
fn publish(
    ws: &Workspace,
    writes: &std::collections::BTreeMap<PathBuf, Vec<u8>>,
) -> Result<(), SchemaError> {
    ct_storage::publication::FilePublisher::new(&ws.root)
        .publish(writes, &[])
        .map_err(|e| SchemaError(e.to_string()))
}

/// i18n 表（声明了 i18n 字段的表）。
pub fn i18n_tables(ws: &Workspace) -> Vec<ct_domain::schema::TableResource> {
    ws.resources
        .tables
        .iter()
        .filter(|t| t.fields.iter().any(|f| f.i18n))
        .cloned()
        .collect()
}

/// 从 Excel 重建一张表的 source 文本集。
fn source_for_table(
    ws: &Workspace,
    table: &ct_domain::schema::TableResource,
) -> Result<Option<HashMap<String, String>>, SchemaError> {
    let excel_path = ws.excel_dir().join(table.resolved_excel_file());
    if !excel_path.exists() {
        return Ok(None);
    }
    let records = ws.resources.records_map();
    let enums = ws.resources.enums_map();
    let layout = build_layout(table, "sha256:sync", &records);
    let report =
        probe_xlsx(&excel_path).map_err(|e| SchemaError(format!("Excel 读取失败: {e}")))?;
    let rows = rows_from_probe(&report);
    let parsed = read_canonical_rows(&layout, table, &records, &enums, &rows);
    let i18n_names: Vec<&str> = table
        .fields
        .iter()
        .filter(|f| f.i18n)
        .map(|f| f.name.as_str())
        .collect();
    let mut source = HashMap::new();
    for row in &parsed.rows {
        let row_id = row
            .get(&table.primary)
            .and_then(|v| {
                v.as_i64()
                    .map(|n| n.to_string())
                    .or_else(|| v.as_str().map(String::from))
            })
            .unwrap_or_default();
        for name in &i18n_names {
            let text = row
                .get(*name)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            source.insert(format!("{row_id}.{name}"), text);
        }
    }
    Ok(Some(source))
}

/// sync：刷新 source 文件与 lang 骨架。返回逐表消息，末条汇总。
pub fn i18n_sync(
    ws: &Workspace,
    table_filter: Option<&str>,
    lang_filter: Option<&str>,
) -> Result<Vec<String>, SchemaError> {
    if let Some(name) = table_filter {
        let table = ws.resources.tables.iter().find(|t| t.table == name);
        match table {
            None => return Err(SchemaError(format!("表 '{name}' 不存在"))),
            Some(t) if !t.fields.iter().any(|f| f.i18n) => {
                return Err(SchemaError(format!("表 '{name}' 没有 i18n 字段")))
            }
            _ => {}
        }
    }
    let langs: Vec<String> = match lang_filter {
        Some(lang) => {
            if !ws.config.secondary_langs.contains(&lang.to_string()) {
                return Err(SchemaError(format!(
                    "语言 '{lang}' 不在可导出语言中（可用: {}）",
                    ws.config.secondary_langs.join(", ")
                )));
            }
            vec![lang.to_string()]
        }
        None => ws.config.secondary_langs.clone(),
    };

    let i18n_dir = i18n_dir(ws);
    let mut messages = Vec::new();
    let mut writes = std::collections::BTreeMap::new();
    let mut totals = [0usize; 4]; // added/updated/stale/orphan
    let mut processed = 0;
    for table in i18n_tables(ws) {
        if table_filter.is_some_and(|f| f != table.table) {
            continue;
        }
        let Some(source) = source_for_table(ws, &table)? else {
            continue;
        };
        let field_order: Vec<String> = table
            .fields
            .iter()
            .filter(|f| f.i18n)
            .map(|f| f.name.clone())
            .collect();
        stage_if_changed(
            &mut writes,
            &i18n_dir
                .join("source")
                .join(format!("{}.json", table.table)),
            &serialize_source_object(&source, &field_order),
        );
        messages.push(format!("synced {}", table.table));
        processed += 1;
        for lang in &langs {
            let lang_path = i18n_dir.join(lang).join(format!("{}.json", table.table));
            let existing = load_json_map(&lang_path);
            let synced = sync_lang_table(&source, &existing);
            let added = synced.keys().filter(|k| !existing.contains_key(*k)).count();
            let updated = synced
                .iter()
                .filter(|(k, e)| existing.get(*k).is_some_and(|old| old != *e))
                .count();
            let stale = synced
                .values()
                .filter(|e| e.get("status").and_then(|v| v.as_str()) == Some("stale"))
                .count();
            let orphan = synced
                .values()
                .filter(|e| e.get("status").and_then(|v| v.as_str()) == Some("orphan"))
                .count();
            totals[0] += added;
            totals[1] += updated;
            totals[2] += stale;
            totals[3] += orphan;
            stage_if_changed(
                &mut writes,
                &lang_path,
                &serialize_i18n_object(&synced, &field_order),
            );
        }
    }
    messages.push(format!(
        "处理 {} 张表 × {} 语言：新增 {}、更新 {}、stale {}、orphan {}",
        processed,
        langs.len(),
        totals[0],
        totals[1],
        totals[2],
        totals[3]
    ));
    publish(ws, &writes)?;
    Ok(messages)
}

/// 状态：每语言/每表计数与进度。
pub fn i18n_status(ws: &Workspace) -> HashMap<String, Value> {
    let i18n_dir = i18n_dir(ws);
    let tables = i18n_tables(ws);
    let mut result = HashMap::new();
    for lang in &ws.config.secondary_langs {
        let mut lang_counts = [0usize; 5]; // translated/missing/stale/orphan/total
        let mut table_detail = Map::new();
        for table in &tables {
            let source_path = i18n_dir
                .join("source")
                .join(format!("{}.json", table.table));
            let Ok(text) = std::fs::read_to_string(&source_path) else {
                continue;
            };
            let source: HashMap<String, String> = serde_json::from_str(&text).unwrap_or_default();
            let lang_path = i18n_dir.join(lang).join(format!("{}.json", table.table));
            let entries = load_json_map(&lang_path);
            let mut counts = [0usize; 5];
            for key in source.keys() {
                let entry = entries.get(key);
                let text = entry
                    .and_then(|e| e.get("text"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let confirmed = entry
                    .and_then(|e| e.get("confirmed"))
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false);
                match compute_status(text, confirmed, true) {
                    LangStatus::Translated => counts[0] += 1,
                    LangStatus::Missing => counts[1] += 1,
                    LangStatus::Stale => counts[2] += 1,
                    LangStatus::Orphan => counts[3] += 1,
                }
                counts[4] += 1;
            }
            for key in entries.keys() {
                if !source.contains_key(key) {
                    counts[3] += 1;
                    counts[4] += 1;
                }
            }
            table_detail.insert(
                table.table.clone(),
                serde_json::json!({
                    "translated": counts[0], "missing": counts[1], "stale": counts[2],
                    "orphan": counts[3], "total": counts[4],
                    "progress": progress(counts),
                }),
            );
            for i in 0..5 {
                lang_counts[i] += counts[i];
            }
        }
        result.insert(
            lang.clone(),
            serde_json::json!({
                "translated": lang_counts[0], "missing": lang_counts[1],
                "stale": lang_counts[2], "orphan": lang_counts[3], "total": lang_counts[4],
                "progress": progress(lang_counts), "tables": table_detail,
            }),
        );
    }
    result
}

/// 进度 = translated / (total - orphan)；无活跃条目视为 100%。
fn progress(counts: [usize; 5]) -> f64 {
    let active = counts[4] as i64 - counts[3] as i64;
    if active <= 0 {
        return 1.0;
    }
    (counts[0] as f64 / active as f64 * 10000.0).round() / 10000.0
}

/// compact：清理 orphan 条目；dry_run 只返回将删除的明细。
pub fn i18n_compact(
    ws: &Workspace,
    table_filter: Option<&str>,
    lang_filter: Option<&str>,
    dry_run: bool,
) -> Result<Value, SchemaError> {
    let langs: Vec<String> = match lang_filter {
        Some(lang) => vec![lang.to_string()],
        None => ws.config.secondary_langs.clone(),
    };
    let i18n_dir = i18n_dir(ws);
    let mut writes = std::collections::BTreeMap::new();
    let mut removed = 0usize;
    let mut touched = 0usize;
    let mut files = Vec::new();
    for table in i18n_tables(ws) {
        if table_filter.is_some_and(|f| f != table.table) {
            continue;
        }
        let field_order: Vec<String> = table
            .fields
            .iter()
            .filter(|f| f.i18n)
            .map(|f| f.name.clone())
            .collect();
        let source_path = i18n_dir
            .join("source")
            .join(format!("{}.json", table.table));
        let Ok(text) = std::fs::read_to_string(&source_path) else {
            continue;
        };
        let source: HashMap<String, String> = serde_json::from_str(&text).unwrap_or_default();
        for lang in &langs {
            let lang_path = i18n_dir.join(lang).join(format!("{}.json", table.table));
            if !lang_path.exists() {
                continue;
            }
            let mut entries = load_json_map(&lang_path);
            let orphans: Vec<String> = entries
                .keys()
                .filter(|k| !source.contains_key(*k))
                .cloned()
                .collect();
            if orphans.is_empty() {
                continue;
            }
            let mut orphans = orphans;
            orphans.sort();
            removed += orphans.len();
            touched += 1;
            files.push(serde_json::json!({
                "lang": lang, "table": table.table, "removed_keys": orphans,
            }));
            if dry_run {
                continue;
            }
            for key in &orphans {
                entries.remove(key);
            }
            stage_if_changed(
                &mut writes,
                &lang_path,
                &serialize_i18n_object(&entries, &field_order),
            );
        }
    }
    publish(ws, &writes)?;
    Ok(serde_json::json!({
        "dry_run": dry_run,
        "touched": touched,
        "total_removed": removed,
        "files": files,
    }))
}

/// 一条译文视图（key/source/text/confirmed/status）。
#[derive(Debug, Clone)]
pub struct I18nRow {
    pub key: String,
    pub source: String,
    pub text: String,
    pub confirmed: bool,
    pub status: LangStatus,
}

fn source_map(ws: &Workspace, table: &str) -> HashMap<String, String> {
    let path = i18n_dir(ws).join("source").join(format!("{table}.json"));
    std::fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

fn field_order_of(ws: &Workspace, table: &str) -> Vec<String> {
    ws.resources
        .tables
        .iter()
        .find(|t| t.table == table)
        .map(|t| {
            t.fields
                .iter()
                .filter(|f| f.i18n)
                .map(|f| f.name.clone())
                .collect()
        })
        .unwrap_or_default()
}

/// 查询一张表在某种语言下的全部条目（稳定顺序：`{id}.{field}` 排序）。
pub fn i18n_rows(ws: &Workspace, table: &str, lang: &str) -> Vec<I18nRow> {
    let source = source_map(ws, table);
    let lang_path = i18n_dir(ws).join(lang).join(format!("{table}.json"));
    let entries = sync_lang_table(&source, &load_json_map(&lang_path));
    let mut keys: Vec<String> = source.keys().chain(entries.keys()).cloned().collect();
    keys.sort();
    keys.dedup();
    keys.into_iter()
        .map(|key| {
            let entry = entries.get(&key);
            let text = entry
                .and_then(|e| e.get("text"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let confirmed = entry
                .and_then(|e| e.get("confirmed"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let in_source = source.contains_key(&key);
            let status = compute_status(&text, confirmed, in_source);
            I18nRow {
                source: entry
                    .and_then(|e| e.get("source"))
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string(),
                key,
                text,
                confirmed,
                status,
            }
        })
        .collect()
}

/// 保存单条译文：状态按 source/text/confirmed 重算，不信任客户端上报。
pub fn i18n_save_entry(
    ws: &Workspace,
    lang: &str,
    table: &str,
    key: &str,
    text: &str,
    confirmed: bool,
) -> Result<LangStatus, SchemaError> {
    if !ws.config.secondary_langs.iter().any(|l| l == lang) {
        return Err(SchemaError(format!("语言 '{lang}' 不在可导出语言中")));
    }
    if table.is_empty() || key.is_empty() {
        return Err(SchemaError("table 与 key 不能为空".to_string()));
    }
    if !i18n_tables(ws).iter().any(|t| t.table == table) {
        return Err(SchemaError(format!("表 '{table}' 不存在或没有 i18n 字段")));
    }
    let source = source_map(ws, table);
    let in_source = source.contains_key(key);
    let status = compute_status(text, confirmed, in_source);
    let lang_path = i18n_dir(ws).join(lang).join(format!("{table}.json"));
    let mut entries = load_json_map(&lang_path);
    let mut entry = Map::new();
    entry.insert("text".into(), Value::String(text.to_string()));
    entry.insert("confirmed".into(), Value::Bool(confirmed));
    entry.insert("status".into(), Value::String(status.as_str().to_string()));
    entry.insert(
        "source".into(),
        Value::String(source.get(key).cloned().unwrap_or_default()),
    );
    entries.insert(key.to_string(), entry);
    let order = field_order_of(ws, table);
    let mut writes = std::collections::BTreeMap::new();
    stage_if_changed(
        &mut writes,
        &lang_path,
        &serialize_i18n_object(&entries, &order),
    );
    publish(ws, &writes)?;
    Ok(status)
}

/// Web edits require a previously synchronized entry; worker keeps its upsert contract.
pub fn i18n_entry_exists(ws: &Workspace, table: &str, lang: &str, key: &str) -> bool {
    load_json_map(&i18n_dir(ws).join(lang).join(format!("{table}.json"))).contains_key(key)
}
