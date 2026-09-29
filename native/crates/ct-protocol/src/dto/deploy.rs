//! deploy DTO：独立部署，不更新成功账本。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeployParams {
    #[serde(default)]
    pub for_build: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeployResult {
    /// 实际写入/替换的文件数。
    pub synced: u32,
    /// 目标已是最新、未发生写入。
    pub unchanged: bool,
}
