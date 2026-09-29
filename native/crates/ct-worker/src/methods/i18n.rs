//! i18n.query / save / sync / status / compact。

use std::path::Path;

use ct_app::workspace::Workspace;
use ct_protocol::dto::i18n::{
    I18nCompactParams, I18nCompactResult, I18nEntry, I18nQueryParams, I18nQueryResult,
    I18nSaveParams, I18nSaveResult, I18nStatusResult, I18nSyncParams, I18nSyncResult, LangProgress,
};
use ct_protocol::error::ErrorCode;
use ct_protocol::pagination::PageRequest;
use serde_json::Value;

use crate::dispatcher::{Emitter, Failure, HandlerResult};
use crate::session::Session;

const DEFAULT_LIMIT: usize = 200;
const MAX_LIMIT: usize = 2000;

fn internal(message: impl Into<String>) -> Failure {
    Failure::new(ErrorCode::Internal, message)
}

fn open(root: &Path) -> Result<Workspace, Failure> {
    Workspace::open(root).map_err(|e| internal(e.0))
}

pub fn query(session: &mut Session, root: &Path, params: &Value) -> HandlerResult {
    let parsed: I18nQueryParams = serde_json::from_value(params.clone())
        .map_err(|e| internal(format!("i18n.query 参数非法: {e}")))?;
    let page: PageRequest = parsed.page.clone();
    let offset = session
        .resolve_page(page.cursor.as_deref())
        .map_err(|code| Failure::new(code, "分页令牌已过期，请整页重查"))?;
    let limit = page
        .limit
        .unwrap_or(DEFAULT_LIMIT as u32)
        .clamp(1, MAX_LIMIT as u32) as usize;
    let workspace = open(root)?;
    let rows = ct_app::i18n::i18n_rows(&workspace, &parsed.table, &parsed.lang);
    let filtered: Vec<_> = rows
        .iter()
        .filter(|row| {
            parsed.status.is_none_or(|want| {
                let text = match row.status {
                    ct_export::i18n::LangStatus::Translated => "translated",
                    ct_export::i18n::LangStatus::Missing => "missing",
                    ct_export::i18n::LangStatus::Stale => "stale",
                    ct_export::i18n::LangStatus::Orphan => "orphan",
                };
                let want_text = match want {
                    ct_protocol::dto::i18n::I18nStatus::Translated => "translated",
                    ct_protocol::dto::i18n::I18nStatus::Missing => "missing",
                    ct_protocol::dto::i18n::I18nStatus::Stale => "stale",
                    ct_protocol::dto::i18n::I18nStatus::Orphan => "orphan",
                };
                text == want_text
            })
        })
        .collect();
    let entries: Vec<I18nEntry> = filtered
        .iter()
        .skip(offset)
        .take(limit)
        .map(|row| I18nEntry {
            key: row.key.clone(),
            source: row.source.clone(),
            text: row.text.clone(),
            confirmed: row.confirmed,
            status: match row.status {
                ct_export::i18n::LangStatus::Translated => {
                    ct_protocol::dto::i18n::I18nStatus::Translated
                }
                ct_export::i18n::LangStatus::Missing => ct_protocol::dto::i18n::I18nStatus::Missing,
                ct_export::i18n::LangStatus::Stale => ct_protocol::dto::i18n::I18nStatus::Stale,
                ct_export::i18n::LangStatus::Orphan => ct_protocol::dto::i18n::I18nStatus::Orphan,
            },
        })
        .collect();
    let next_offset = offset + entries.len();
    let next_cursor = (next_offset < filtered.len()).then(|| session.page_token(next_offset));
    let result = I18nQueryResult {
        revision: session.snapshot_revision,
        entries,
        next_cursor,
    };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

pub fn status(root: &Path) -> HandlerResult {
    let workspace = open(root)?;
    let report = ct_app::i18n::i18n_status(&workspace);
    let mut names: Vec<&String> = report.keys().collect();
    names.sort();
    let langs = names
        .into_iter()
        .map(|name| LangProgress {
            lang: name.clone(),
            translated: report[name]["translated"].as_u64().unwrap_or(0) as u32,
            missing: report[name]["missing"].as_u64().unwrap_or(0) as u32,
            stale: report[name]["stale"].as_u64().unwrap_or(0) as u32,
            orphan: report[name]["orphan"].as_u64().unwrap_or(0) as u32,
        })
        .collect();
    let result = I18nStatusResult { langs };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

pub fn save(root: &Path, params: &Value) -> HandlerResult {
    let parsed: I18nSaveParams = serde_json::from_value(params.clone())
        .map_err(|e| internal(format!("i18n.save 参数非法: {e}")))?;
    let workspace = open(root)?;
    let status = ct_app::i18n::i18n_save_entry(
        &workspace,
        &parsed.lang,
        &parsed.table,
        &parsed.key,
        &parsed.text,
        parsed.confirmed,
    )
    .map_err(|e| internal(e.0))?;
    let result = I18nSaveResult {
        status: match status {
            ct_export::i18n::LangStatus::Translated => {
                ct_protocol::dto::i18n::I18nStatus::Translated
            }
            ct_export::i18n::LangStatus::Missing => ct_protocol::dto::i18n::I18nStatus::Missing,
            ct_export::i18n::LangStatus::Stale => ct_protocol::dto::i18n::I18nStatus::Stale,
            ct_export::i18n::LangStatus::Orphan => ct_protocol::dto::i18n::I18nStatus::Orphan,
        },
    };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

pub fn sync(root: &Path, params: &Value, emitter: &Emitter) -> HandlerResult {
    let parsed: I18nSyncParams = serde_json::from_value(params.clone())
        .map_err(|e| internal(format!("i18n.sync 参数非法: {e}")))?;
    let workspace = open(root)?;
    let messages = ct_app::i18n::i18n_sync(&workspace, parsed.table.as_deref(), None)
        .map_err(|e| internal(e.0))?;
    let mut tables = 0u32;
    for message in &messages {
        emitter.log("i18n", message);
        if message.contains("同步") {
            tables += 1;
        }
    }
    let result = I18nSyncResult {
        tables,
        inserted: 0,
    };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

pub fn compact(root: &Path, params: &Value, emitter: &Emitter) -> HandlerResult {
    let parsed: I18nCompactParams = serde_json::from_value(params.clone())
        .map_err(|e| internal(format!("i18n.compact 参数非法: {e}")))?;
    let workspace = open(root)?;
    let result =
        ct_app::i18n::i18n_compact(&workspace, parsed.table.as_deref(), None, parsed.dry_run)
            .map_err(|e| internal(e.0))?;
    let entries: Vec<String> = result["files"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .flat_map(|item| {
            item["removed_keys"]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .iter()
                .filter_map(|k| k.as_str().map(String::from))
                .collect::<Vec<String>>()
        })
        .collect();
    let removed = result["total_removed"].as_u64().unwrap_or(0) as u32;
    emitter.log("i18n", &format!("compact 影响 {removed} 条 orphan"));
    let payload = I18nCompactResult {
        dry_run: parsed.dry_run,
        entries: if parsed.dry_run { entries } else { Vec::new() },
        removed,
    };
    serde_json::to_value(payload).map_err(|e| internal(e.to_string()))
}
