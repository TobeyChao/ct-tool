//! validate/export DTO。

use serde::{Deserialize, Serialize};

use crate::event::Issue;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ValidateParams {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub table: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ValidateResult {
    pub ok: bool,
    #[serde(default)]
    pub issues: Vec<Issue>,
}

/// `export` 参数。桌面导出只本地发布并记账，不自动部署；
/// `deploy` 是独立方法。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportParams {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub table: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lang: Option<String>,
    /// 强制重建：绕过解析/校验/生成缓存。
    #[serde(default)]
    pub all: bool,
}

/// 任务类方法的通用终态。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskOutcome {
    Succeeded,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StageStat {
    pub name: String,
    pub elapsed_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CacheStat {
    pub hits: u64,
    pub misses: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportResult {
    pub outcome: TaskOutcome,
    pub tables: u32,
    pub duration_ms: u64,
    #[serde(default)]
    pub stages: Vec<StageStat>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cache: Option<CacheStat>,
    #[serde(default)]
    pub issues: Vec<Issue>,
}
