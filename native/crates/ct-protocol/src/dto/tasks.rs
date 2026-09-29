//! tasks.list / tasks.issues / tasks.dismiss DTO。

use serde::{Deserialize, Serialize};

use crate::event::Issue;
use crate::pagination::PageRequest;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Running,
    Success,
    Error,
    Cancelled,
    /// worker 断连且无终态：不谎报成功/取消，不自动重放。
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskInfo {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<u64>,
    pub method: String,
    pub status: TaskStatus,
    #[serde(default)]
    pub message: String,
    /// Unix 秒。
    pub started_at: f64,
    /// 已被用户关闭的通知重连后不复活。
    #[serde(default)]
    pub dismissed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TasksListResult {
    #[serde(default)]
    pub tasks: Vec<TaskInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskIssuesParams {
    pub task_id: String,
    #[serde(default)]
    pub page: PageRequest,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskIssuesResult {
    #[serde(default)]
    pub issues: Vec<Issue>,
    /// 分页契约：令牌绑定的快照代次（见 v1.md §9）。
    pub revision: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskDismissParams {
    pub task_id: String,
}
