//! 请求消息与控制方法参数。

use serde::{Deserialize, Serialize};

/// 客户端请求。`request_id` 在同一连接内必须唯一，重复即拒绝
/// （`duplicate-request-id`），重连后不得重放写请求。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Request {
    pub request_id: u64,
    /// 方法名，见 [`crate::methods`] 常量；未知方法返回 `unknown-method`。
    pub method: String,
    pub workspace_root: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

/// `cancel` 方法参数：取消仅设置 token，发布边界之后延迟生效。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CancelParams {
    pub target_request_id: u64,
}

/// `cancel` 方法结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CancelState {
    /// 已设置取消 token，目标任务将在下一个检查点终止。
    Cancelling,
    /// 目标任务已有终态（含发布后进入完成阶段）。
    AlreadyTerminal,
    /// 目标任务不存在（本连接未接受过该 requestId）。
    UnknownRequest,
}
