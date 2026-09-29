//! validate：完整校验覆盖（只读，不写持久缓存）。

use std::path::Path;

use ct_app::workspace::Workspace;
use ct_protocol::dto::export::{ValidateParams, ValidateResult};
use ct_protocol::error::ErrorCode;
use serde_json::Value;

use crate::dispatcher::{Failure, HandlerResult};
use crate::issue_of;

pub fn validate(root: &Path, params: &Value) -> HandlerResult {
    let parsed: ValidateParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("validate 参数非法: {e}")))?;
    let workspace = Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    let issues = ct_app::validate::canonical_validate(&workspace, parsed.table.as_deref());
    let result = ValidateResult {
        ok: issues.is_empty(),
        issues: issues.iter().map(issue_of).collect(),
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
