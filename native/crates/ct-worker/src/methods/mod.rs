//! 方法路由表。方法名以 `docs/protocol/v1.md` 为唯一准绳。

pub mod deploy;
pub mod export;
pub mod history;
pub mod i18n;
pub mod logs;
pub mod resources;
pub mod schema;
pub mod table_preview;
pub mod tasks;
pub mod template;
pub mod validate;
pub mod workspace;

use std::path::Path;

use ct_protocol::methods;
use serde_json::Value;

use crate::dispatcher::{Emitter, HandlerResult};
use crate::session::Session;
use crate::task::CancelFlag;

/// 写方法：需要工作区锁、可能产生事件流。
pub fn is_write_method(method: &str) -> bool {
    matches!(
        method,
        methods::WORKSPACE_RECOVER
            | methods::SCHEMA_SAVE
            | methods::TEMPLATE_GENERATE
            | methods::EXPORT
            | methods::DEPLOY
            | methods::I18N_SAVE
            | methods::I18N_SYNC
            | methods::I18N_COMPACT
            | methods::TASKS_DISMISS
    )
}

/// 只读方法：主循环内同步执行。
pub fn handle_read(
    session: &mut Session,
    root: &Path,
    method: &str,
    params: &Value,
) -> HandlerResult {
    let _read_lock = if !matches!(
        method,
        methods::LOGS_LIST | methods::TASKS_LIST | methods::TASKS_ISSUES
    ) {
        Some(ct_storage::lock::WorkspaceLock::acquire(root).map_err(|e| {
            crate::dispatcher::Failure::new(ct_protocol::error::ErrorCode::Busy, e.to_string())
        })?)
    } else {
        None
    };
    // Workspace metadata methods report recovery state themselves. Every other
    // disk-backed read must stop before loading a partially published resource set.
    if _read_lock.is_some()
        && !matches!(
            method,
            methods::WORKSPACE_OPEN | methods::WORKSPACE_SNAPSHOT | methods::WORKSPACE_STATUS
        )
    {
        if let Some(note) = ct_app::workspace::recovery_needed(root) {
            return Err(crate::dispatcher::Failure::new(
                ct_protocol::error::ErrorCode::RecoveryNeeded,
                note,
            ));
        }
    }
    match method {
        methods::WORKSPACE_OPEN => workspace::open(session, root),
        methods::WORKSPACE_SNAPSHOT => workspace::snapshot(session, root),
        methods::WORKSPACE_STATUS => workspace::status(session, root),
        methods::RESOURCES_LIST => resources::list(session, root),
        methods::TABLE_PREVIEW => table_preview::preview(session, root, params),
        methods::SCHEMA_CANDIDATE => schema::candidate(root, params),
        methods::TEMPLATE_PLAN => template::plan(root, params),
        methods::VALIDATE => validate::validate(root, params),
        methods::I18N_QUERY => i18n::query(session, root, params),
        methods::I18N_STATUS => i18n::status(root),
        methods::HISTORY_LIST => history::list(root),
        methods::LOGS_LIST => logs::list(session, params),
        methods::TASKS_LIST => tasks::list(session),
        methods::TASKS_ISSUES => tasks::issues(session, params),
        other => Err(crate::dispatcher::Failure::new(
            ct_protocol::error::ErrorCode::UnknownMethod,
            format!("未知方法: {other}"),
        )),
    }
}

/// 写方法：工作线程执行，可取消。
pub fn run_write(
    shared: &crate::dispatcher::Shared,
    root: &Path,
    method: &str,
    params: &Value,
    cancel: &CancelFlag,
    emitter: &Emitter,
) -> HandlerResult {
    // A queued write can be cancelled before it acquires a workspace
    // transaction. Once it enters a non-cooperative write, its actual result
    // takes precedence over a late request.
    if cancel.requested() {
        return Ok(serde_json::json!({"outcome":"cancelled"}));
    }
    // Export/save/deploy/recover own their transactions. The remaining write
    // methods share the same lock and recovery boundary before loading data.
    let _transaction = if matches!(
        method,
        methods::TEMPLATE_GENERATE
            | methods::I18N_SAVE
            | methods::I18N_SYNC
            | methods::I18N_COMPACT
    ) {
        Some(
            ct_storage::workspace::WorkspaceTransaction::begin(root).map_err(|e| {
                let code = match &e {
                    ct_storage::workspace::TransactionError::Busy(_) => {
                        ct_protocol::error::ErrorCode::Busy
                    }
                    _ => ct_protocol::error::ErrorCode::Internal,
                };
                crate::dispatcher::Failure::new(code, e.to_string())
            })?,
        )
    } else {
        None
    };
    match method {
        methods::WORKSPACE_RECOVER => workspace::recover(shared, root, emitter),
        methods::SCHEMA_SAVE => schema::save(root, params, emitter),
        methods::TEMPLATE_GENERATE => template::generate(root, params, cancel, emitter),
        methods::EXPORT => export::export(root, params, cancel, emitter),
        methods::DEPLOY => deploy::deploy(root, params, emitter),
        methods::I18N_SAVE => i18n::save(root, params),
        methods::I18N_SYNC => i18n::sync(root, params, emitter),
        methods::I18N_COMPACT => i18n::compact(root, params, emitter),
        methods::TASKS_DISMISS => tasks::dismiss(shared, params),
        other => Err(crate::dispatcher::Failure::new(
            ct_protocol::error::ErrorCode::UnknownMethod,
            format!("未知写方法: {other}"),
        )),
    }
}
