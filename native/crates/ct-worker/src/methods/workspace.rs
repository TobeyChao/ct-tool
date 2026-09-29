//! workspace.open / snapshot / status / recover。

use std::path::Path;

use ct_app::workspace::{recover_workspace, recovery_needed, Workspace};
use ct_protocol::dto::workspace::{
    RecoverOutcome, RecoverResult, RecoveryInfo, WorkspaceSnapshot, WorkspaceStatus,
    WorkspaceStatusResult,
};
use ct_protocol::error::ErrorCode;

use crate::dispatcher::{Emitter, Failure, HandlerResult};
use crate::session::Session;

fn journals(root: &Path) -> Vec<String> {
    if root.join(".ct/export-publication.json").exists() {
        return vec![".ct/export-publication.json".to_string()];
    }
    Vec::new()
}

pub fn open(session: &mut Session, root: &Path) -> HandlerResult {
    session.bind(root);
    let pending = recovery_needed(root);
    let (status, tables, records, enums) = match pending {
        Some(_) => (WorkspaceStatus::RecoveryNeeded, 0, 0, 0),
        None => {
            let workspace =
                Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
            (
                WorkspaceStatus::Ready,
                workspace.resources.tables.len() as u32,
                workspace.resources.records.len() as u32,
                workspace.resources.enums.len() as u32,
            )
        }
    };
    let snapshot = WorkspaceSnapshot {
        revision: session.snapshot_revision,
        status,
        recovery: RecoveryInfo {
            needed: pending.is_some(),
            journals: journals(root),
        },
        tables,
        records,
        enums,
    };
    serde_json::to_value(snapshot).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}

pub fn snapshot(session: &mut Session, root: &Path) -> HandlerResult {
    if let Some(note) = recovery_needed(root) {
        return Err(Failure::new(ErrorCode::RecoveryNeeded, note));
    }
    open(session, root)
}

pub fn status(session: &mut Session, root: &Path) -> HandlerResult {
    let pending = recovery_needed(root).is_some();
    let changed_tables = if pending {
        Vec::new()
    } else {
        match Workspace::open(root) {
            Ok(workspace) => {
                let report = ct_app::status::canonical_status(&workspace);
                let mut changed = report.changed;
                changed.extend(report.missing);
                changed.sort();
                changed
            }
            Err(e) => return Err(Failure::new(ErrorCode::Internal, e.0)),
        }
    };
    let result = WorkspaceStatusResult {
        revision: session.snapshot_revision,
        pending_journal: pending,
        changed_tables,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}

pub fn recover(
    shared: &crate::dispatcher::Shared,
    root: &Path,
    emitter: &Emitter,
) -> HandlerResult {
    let report = recover_workspace(root).map_err(|e| Failure::new(ErrorCode::RecoveryNeeded, e))?;
    let note = report.note.unwrap_or_default();
    if !note.is_empty() {
        emitter.log("recover", &note);
    }
    // 恢复改写了工作区：先收敛代次，再把新基线回给客户端
    let revision = {
        let mut session = shared.lock().expect("会话中毒");
        session.after_write(root);
        session.snapshot_revision
    };
    let result = RecoverResult {
        outcome: if note.is_empty() {
            RecoverOutcome::Noop
        } else {
            RecoverOutcome::Recovered
        },
        revision: Some(revision),
        detail: if note.is_empty() {
            "无待恢复事务".to_string()
        } else {
            note
        },
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
