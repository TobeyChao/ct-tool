//! 任务登记与协作式取消令牌。

use ct_protocol::dto::tasks::TaskStatus;
use ct_protocol::event::Issue;

pub use ct_app::task::CancelFlag;

/// 一个已接受请求的任务记录（tasks.list / cancel / dismiss 的依据）。
pub struct TaskRecord {
    pub id: String,
    pub request_id: u64,
    pub method: String,
    pub status: TaskStatus,
    pub message: String,
    pub started_at: f64,
    pub dismissed: bool,
    pub issues: Vec<Issue>,
    pub cancel: CancelFlag,
}

impl TaskRecord {
    pub fn new(id: String, request_id: u64, method: &str, cancel: CancelFlag) -> Self {
        TaskRecord {
            id,
            request_id,
            method: method.to_string(),
            status: TaskStatus::Running,
            message: String::new(),
            started_at: unix_seconds(),
            dismissed: false,
            issues: Vec::new(),
            cancel,
        }
    }

    pub fn terminal(&self) -> bool {
        !matches!(self.status, TaskStatus::Running)
    }
}

pub fn unix_seconds() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or_default()
}
