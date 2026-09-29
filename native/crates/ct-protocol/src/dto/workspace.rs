//! workspace.open/snapshot/status/recover 的 DTO。

use serde::{Deserialize, Serialize};

/// `workspace.open` / `workspace.snapshot` 结果。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceSnapshot {
    /// 快照代次：任何资源/配置变化后递增；分页令牌绑定该值。
    pub revision: u64,
    pub status: WorkspaceStatus,
    pub recovery: RecoveryInfo,
    pub tables: u32,
    pub records: u32,
    pub enums: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceStatus {
    Ready,
    /// 存在待恢复事务，只读查询被拒，须显式 `workspace.recover`。
    RecoveryNeeded,
}

/// 待恢复事务材料位置（相对 workspace 根）。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoveryInfo {
    pub needed: bool,
    #[serde(default)]
    pub journals: Vec<String>,
}

/// `workspace.status` 结果：只读概览，不写缓存、不做恢复。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceStatusResult {
    pub revision: u64,
    pub pending_journal: bool,
    /// 相对上次成功账本发生变化的表。
    #[serde(default)]
    pub changed_tables: Vec<String>,
}

/// `workspace.recover` 结果。恢复会改变基线，客户端须重载草稿。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoverResult {
    pub outcome: RecoverOutcome,
    /// 恢复后的新基线；`blocked` 时缺省。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revision: Option<u64>,
    #[serde(default)]
    pub detail: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoverOutcome {
    Recovered,
    Noop,
    /// 恢复材料不足或无法识别：保留现场并阻止写入。
    Blocked,
}
