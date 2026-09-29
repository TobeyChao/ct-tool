//! history.list DTO：桌面导出历史。

use serde::{Deserialize, Serialize};

/// 单条导出历史；`result` 为状态码（当前仅 `success`）。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoryEntry {
    pub time: String,
    pub scope: String,
    pub result: String,
    pub tables: u32,
    /// 秒。
    pub elapsed: f64,
    pub forced: bool,
    #[serde(default)]
    pub error: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HistoryListResult {
    /// 最新在前，最多 5 条；跨重启保留。
    #[serde(default)]
    pub entries: Vec<HistoryEntry>,
}
