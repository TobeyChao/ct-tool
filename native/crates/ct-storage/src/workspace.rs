//! 共享工作区事务入口（对应 Python `ct/storage/workspace_transaction.py`）。
//!
//! Schema 保存、导出、部署共用一把排他锁与一次恢复；恢复在任何配置/资源
//! 加载之前完成（global.yaml 可能已被改坏，中断的发布必须先回滚）。
//! 锁不可重入：每个用例恰好进入一次事务。

use std::path::Path;

use crate::lock::{WorkspaceBusyError, WorkspaceLock};
use crate::publication::FilePublisher;

/// 工作区事务守卫：持锁期间恢复已完成，Drop 释放锁。
pub struct WorkspaceTransaction {
    _lock: WorkspaceLock,
    /// 恢复描述（没有待恢复事务时为 None）
    pub recovery: Option<String>,
}

impl std::fmt::Debug for WorkspaceTransaction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("WorkspaceTransaction")
            .field("recovery", &self.recovery)
            .finish()
    }
}

impl WorkspaceTransaction {
    /// 获取锁并恢复中断的发布。
    pub fn begin(root: &Path) -> Result<Self, TransactionError> {
        let lock = WorkspaceLock::acquire(root).map_err(TransactionError::Busy)?;
        let recovery = FilePublisher::new(root).recover().map_err(|e| {
            TransactionError::Recovery(format!("恢复记录无法处理，已保留材料并阻止写入：{e}"))
        })?;
        if let Some(note) = crate::journal::legacy_apply_note(root) {
            return Err(TransactionError::Recovery(note));
        }
        Ok(WorkspaceTransaction {
            _lock: lock,
            recovery,
        })
    }
}

/// 事务入口错误：busy（重试）或恢复失败（需人工检查材料）。
#[derive(Debug)]
pub enum TransactionError {
    Busy(WorkspaceBusyError),
    Recovery(String),
}

impl std::fmt::Display for TransactionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TransactionError::Busy(e) => write!(f, "{e}"),
            TransactionError::Recovery(m) => f.write_str(m),
        }
    }
}

impl std::error::Error for TransactionError {}
