//! 终态响应：每个已接受请求至多一个终态（result 或 error）。

use serde::{Deserialize, Serialize};

use crate::error::ErrorBody;

/// 成功终态。任务类方法的取消以 `payload.outcome = "cancelled"` 表示，
/// 不使用 error。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResultResponse {
    pub request_id: u64,
    pub workspace_id: String,
    /// 连接内单调递增，客户端据此检测乱序与丢消息。
    pub seq: u64,
    pub payload: serde_json::Value,
}

/// 失败终态 / 连接级错误。
///
/// 仅当入站消息无法解析出 `requestId`（非法 JSON、超限、hello 之前
/// 收到其他消息）时 `request_id`/`workspace_id`/`seq` 缺省。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ErrorResponse {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub workspace_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub seq: Option<u64>,
    pub error: ErrorBody,
}
