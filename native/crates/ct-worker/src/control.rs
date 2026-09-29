//! 控制消息：cancel 与 shutdown 的语义收口。

use ct_protocol::dto::tasks::TaskStatus;
use ct_protocol::request::{CancelParams, CancelState};
use serde_json::Value;

use crate::dispatcher::Shared;

/// `cancel`：只设置协作式 token；已有终态返回 already_terminal。
pub fn cancel(shared: &Shared, params: &Value) -> CancelState {
    let Ok(parsed) = serde_json::from_value::<CancelParams>(params.clone()) else {
        return CancelState::UnknownRequest;
    };
    let mut session = shared.lock().expect("会话中毒");
    let state = match session
        .tasks
        .iter_mut()
        .find(|t| t.request_id == parsed.target_request_id)
    {
        None => CancelState::UnknownRequest,
        Some(task) if task.terminal() => CancelState::AlreadyTerminal,
        Some(task) => {
            task.cancel.cancel();
            CancelState::Cancelling
        }
    };
    if matches!(state, CancelState::Cancelling) {
        session.push_log(
            "control",
            "info",
            &format!("已请求取消请求 #{}", parsed.target_request_id),
            Some(parsed.target_request_id),
        );
    }
    state
}

/// `shutdown`：标记退出；等待运行中的写任务到达发布安全边界。
pub fn begin_shutdown(shared: &Shared) {
    let mut session = shared.lock().expect("会话中毒");
    session.shutting_down = true;
    // 读任务无副作用；写任务由 runtime 等待其终态
    for task in session.tasks.iter_mut() {
        if matches!(task.status, TaskStatus::Running) {
            task.message.push_str("[shutdown pending] ");
        }
    }
}

/// 是否仍有写任务在跑（关闭前必须等待）。
pub fn running_tasks(shared: &Shared) -> usize {
    let session = shared.lock().expect("会话中毒");
    session
        .tasks
        .iter()
        .filter(|t| matches!(t.status, TaskStatus::Running))
        .count()
}
