//! 非终态事件：进度/日志/结构化问题。
//!
//! 事件队列有界：progress 可合并，log 可限流，issue 与终态不可丢弃。

use serde::{Deserialize, Serialize};

/// 阶段进度。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProgressEvent {
    pub request_id: u64,
    pub workspace_id: String,
    pub seq: u64,
    pub stage: String,
    pub done: u64,
    pub total: u64,
}

/// 运行日志行（业务日志查询走 `logs.list`，这里只是实时流）。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LogEvent {
    pub request_id: u64,
    pub workspace_id: String,
    pub seq: u64,
    pub module: String,
    pub level: String,
    pub message: String,
}

/// 结构化问题事件。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IssueEvent {
    pub request_id: u64,
    pub workspace_id: String,
    pub seq: u64,
    pub issue: Issue,
}

/// 结构化问题定位：客户端据此跳转，不解析人类可读日志。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Issue {
    /// 稳定错误码（业务码由内核定义，如 `duplicate-primary-key`）。
    pub code: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub resource: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub field_path: Option<String>,
    /// 原始 Excel 行号；非 Excel 来源的问题缺省。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excel_row: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file: Option<String>,
}
