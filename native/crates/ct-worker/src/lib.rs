//! stdio worker：读取 NDJSON 请求、分发给 `ct-app` 用例并回报事件。
//!
//! 只做传输适配与任务生命周期管理，不包含业务规则。

pub mod control;
pub mod dispatcher;
pub mod event_queue;
pub mod methods;
pub mod runtime;
pub mod session;
pub mod shutdown;
pub mod task;

/// 内核诊断 → 协议 Issue（客户端据此跳转，不解析文本）。
pub(crate) fn issue_of(
    issue: &ct_domain::diagnostics::ValidationIssue,
) -> ct_protocol::event::Issue {
    let field_path = if issue.field.is_empty() {
        let mut parts = String::new();
        if let Some(column) = issue.column {
            parts = ct_domain::diagnostics::column_letter(column);
        }
        parts
    } else {
        issue.field.clone()
    };
    ct_protocol::event::Issue {
        code: issue.code.as_str().to_string(),
        message: issue.message.clone(),
        resource: (!issue.table.is_empty()).then(|| issue.table.clone()),
        field_path: (!field_path.is_empty()).then_some(field_path),
        excel_row: issue.excel_row,
        file: None,
    }
}
