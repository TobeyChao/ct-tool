//! tasks.list / tasks.issues / tasks.dismiss：任务查询、问题分页、关闭通知。

use ct_protocol::dto::tasks::{
    TaskDismissParams, TaskInfo, TaskIssuesParams, TaskIssuesResult, TasksListResult,
};
use ct_protocol::error::ErrorCode;
use ct_protocol::pagination::PageRequest;
use serde_json::Value;

use crate::dispatcher::{Failure, HandlerResult, Shared};
use crate::session::Session;

const DEFAULT_LIMIT: usize = 50;
const MAX_LIMIT: usize = 500;

fn internal(message: impl Into<String>) -> Failure {
    Failure::new(ErrorCode::Internal, message)
}

fn limit_of(page: &PageRequest) -> usize {
    page.limit
        .unwrap_or(DEFAULT_LIMIT as u32)
        .clamp(1, MAX_LIMIT as u32) as usize
}

pub fn list(session: &mut Session) -> HandlerResult {
    let tasks: Vec<TaskInfo> = session
        .tasks
        .iter()
        .map(|task| TaskInfo {
            id: task.id.clone(),
            request_id: Some(task.request_id),
            method: task.method.clone(),
            status: task.status,
            message: task.message.clone(),
            started_at: task.started_at,
            dismissed: task.dismissed || session.dismissed.contains(&task.id),
        })
        .collect();
    let result = TasksListResult { tasks };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

pub fn issues(session: &mut Session, params: &Value) -> HandlerResult {
    let parsed: TaskIssuesParams =
        serde_json::from_value(params.clone()).map_err(|e| internal(e.to_string()))?;
    let offset = session
        .resolve_page(parsed.page.cursor.as_deref())
        .map_err(|code| Failure::new(code, "分页令牌已过期，请整页重查"))?;
    let limit = limit_of(&parsed.page);
    let all: Vec<_> = session
        .tasks
        .iter()
        .filter(|task| task.id == parsed.task_id)
        .flat_map(|task| task.issues.iter().cloned())
        .collect();
    let start = offset.min(all.len());
    let end = (start + limit).min(all.len());
    let issues = all[start..end].to_vec();
    let next_cursor = (end < all.len()).then(|| session.page_token(end));
    let result = TaskIssuesResult {
        issues,
        revision: session.snapshot_revision,
        next_cursor,
    };
    serde_json::to_value(result).map_err(|e| internal(e.to_string()))
}

/// 关闭通知：标记后重连不复活（同一连接内以 dismissed 集合为准）。
pub fn dismiss(shared: &Shared, params: &Value) -> HandlerResult {
    let parsed: TaskDismissParams =
        serde_json::from_value(params.clone()).map_err(|e| internal(e.to_string()))?;
    let mut session = shared.lock().expect("会话中毒");
    let known = session.tasks.iter().any(|task| task.id == parsed.task_id)
        || session.dismissed.contains(&parsed.task_id);
    if !known {
        return Err(Failure::new(
            ErrorCode::Internal,
            format!("任务不存在: {}", parsed.task_id),
        ));
    }
    session.dismissed.insert(parsed.task_id.clone());
    if let Some(task) = session
        .tasks
        .iter_mut()
        .find(|task| task.id == parsed.task_id)
    {
        task.dismissed = true;
    }
    Ok(Value::Bool(true))
}
