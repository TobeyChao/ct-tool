//! deploy：独立部署，不更新成功账本。

use std::path::Path;

use ct_protocol::dto::deploy::{DeployParams, DeployResult};
use ct_protocol::error::ErrorCode;
use serde_json::Value;

use crate::dispatcher::{Emitter, Failure, HandlerResult};

pub fn deploy(root: &Path, params: &Value, emitter: &Emitter) -> HandlerResult {
    let parsed: DeployParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("deploy 参数非法: {e}")))?;
    // 与保存/导出共用一把锁与一次恢复
    let transaction = ct_storage::workspace::WorkspaceTransaction::begin(root)
        .map_err(|e| Failure::new(ErrorCode::Busy, e.to_string()))?;
    if let Some(note) = &transaction.recovery {
        emitter.log("deploy", &format!("[发布恢复] {note}"));
    }
    let config = ct_domain::config::GlobalConfig::load(root)
        .map_err(|e| Failure::new(ErrorCode::Internal, e))?;
    let (changed, logs) = ct_export::deploy::deploy(&config, parsed.for_build)
        .map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    for line in logs {
        emitter.log("deploy", &line);
    }
    let result = DeployResult {
        synced: changed as u32,
        unchanged: changed == 0,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
