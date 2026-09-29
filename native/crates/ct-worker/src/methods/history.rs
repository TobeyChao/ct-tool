//! history.list：最近五次成功桌面导出（跨重启保留）。

use std::path::Path;

use ct_protocol::dto::history::{HistoryEntry, HistoryListResult};
use ct_protocol::error::ErrorCode;

use crate::dispatcher::{Failure, HandlerResult};

pub fn list(root: &Path) -> HandlerResult {
    let entries: Vec<HistoryEntry> = ct_app::history::read_history(root)
        .into_iter()
        .filter_map(|item| serde_json::from_value(item).ok())
        .collect();
    let result = HistoryListResult { entries };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
