//! logs.list：连接内日志的模块/级别筛选与分页。

use ct_protocol::dto::logs::{LogsListResult, LogsQueryParams};
use ct_protocol::error::ErrorCode;
use ct_protocol::pagination::PageRequest;
use serde_json::Value;

use crate::dispatcher::{Failure, HandlerResult};
use crate::session::Session;

const DEFAULT_LIMIT: usize = 200;
const MAX_LIMIT: usize = 1000;

pub fn list(session: &mut Session, params: &Value) -> HandlerResult {
    let parsed: LogsQueryParams =
        serde_json::from_value(params.clone()).map_err(|e| internal(e.to_string()))?;
    let offset = session
        .resolve_page(parsed.page.cursor.as_deref())
        .map_err(|code| Failure::new(code, "分页令牌已过期，请整页重查"))?;
    let limit = limit_of(&parsed.page);
    let filtered: Vec<_> = session
        .logs
        .iter()
        .filter(|entry| {
            parsed.module.as_ref().is_none_or(|m| *m == entry.module)
                && parsed.level.as_ref().is_none_or(|l| *l == entry.level)
        })
        .cloned()
        .collect();
    let start = offset.min(filtered.len());
    let end = (start + limit).min(filtered.len());
    let entries = filtered[start..end].to_vec();
    let next_cursor = (end < filtered.len()).then(|| session.page_token(end));
    let result = LogsListResult {
        entries,
        revision: session.snapshot_revision,
        next_cursor,
    };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

fn limit_of(page: &PageRequest) -> usize {
    page.limit
        .unwrap_or(DEFAULT_LIMIT as u32)
        .clamp(1, MAX_LIMIT as u32) as usize
}

fn internal(message: impl Into<String>) -> Failure {
    Failure::new(ErrorCode::Internal, message)
}
