//! export：本地发布并记账（桌面不自动部署）。

use std::path::Path;

use ct_app::export::{run_export, CompletionPolicy, ExportRequest};
use ct_protocol::dto::export::{CacheStat, ExportParams, ExportResult};
use ct_protocol::error::ErrorCode;
use serde_json::Value;

use crate::dispatcher::{Emitter, Failure, HandlerResult};
use crate::task::CancelFlag;

pub fn export(
    root: &Path,
    params: &Value,
    cancel: &CancelFlag,
    emitter: &Emitter,
) -> HandlerResult {
    let parsed: ExportParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("export 参数非法: {e}")))?;
    let request = ExportRequest {
        root: root.to_path_buf(),
        table_filter: parsed.table.clone(),
        lang_filter: parsed.lang,
        forced: parsed.all,
    };
    let started = std::time::Instant::now();
    let reporter = EmitterReporter(emitter.clone());
    match run_export(
        &request,
        // 桌面导出只本地发布并记账；部署是独立方法
        CompletionPolicy::export_only(),
        Some(cancel),
        Some(std::sync::Arc::new(reporter)),
        true,
    ) {
        Ok((result, _deploy_logs, recovery)) => {
            if let Some(note) = recovery {
                emitter.log("export", &format!("[发布恢复] {note}"));
            }
            // 历史写入失败与业务提交分开报告：终态仍是成功，问题以 issues[] 明细带出
            let issues = match &result.history_warning {
                Some(warning) => vec![ct_protocol::event::Issue {
                    code: "history-write-failed".to_string(),
                    message: warning.clone(),
                    resource: None,
                    field_path: None,
                    excel_row: None,
                    file: None,
                }],
                None => Vec::new(),
            };
            let payload = ExportResult {
                outcome: ct_protocol::dto::export::TaskOutcome::Succeeded,
                tables: result.tables as u32,
                duration_ms: (result.elapsed * 1000.0) as u64,
                stages: result
                    .stages
                    .iter()
                    .map(|(name, elapsed_ms)| ct_protocol::dto::export::StageStat {
                        name: name.clone(),
                        elapsed_ms: *elapsed_ms,
                    })
                    .collect(),
                cache: Some(CacheStat {
                    hits: result.cache_hits as u64,
                    misses: result.cache_misses as u64,
                }),
                issues,
            };
            serde_json::to_value(payload)
                .map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
        }
        Err(ct_app::export::RunError::Cancelled(failure)) => {
            // v1.md §4: accepted cancellation is a result, not an error.
            emitter.log("export", &format!("已按请求取消：{failure}"));
            let payload = ExportResult {
                outcome: ct_protocol::dto::export::TaskOutcome::Cancelled,
                tables: 0,
                duration_ms: started.elapsed().as_millis() as u64,
                stages: Vec::new(),
                cache: None,
                issues: Vec::new(),
            };
            serde_json::to_value(payload)
                .map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
        }
        Err(failure) => {
            // 校验失败：把结构化问题一并回传（客户端据此跳转，不解析文本）
            let issues = match &failure {
                ct_app::export::RunError::Validation(_, issues) => {
                    issues.iter().map(crate::issue_of).collect()
                }
                _ => Vec::new(),
            };
            Err(Failure {
                code: match &failure {
                    ct_app::export::RunError::Busy(_) => ErrorCode::Busy,
                    ct_app::export::RunError::Publish(_) => ErrorCode::Internal,
                    _ => ErrorCode::Internal,
                },
                message: failure.to_string(),
                issues,
            })
        }
    }
}

/// 把内核进度日志转成 worker 事件。
#[derive(Clone)]
pub struct EmitterReporter(pub Emitter);

impl ct_app::export::Reporter for EmitterReporter {
    fn stage(&self, name: &str, index: usize, total: usize) {
        self.0.progress(name, index as u64, total as u64);
    }

    fn log(&self, line: &str, err: bool) {
        let module = if line.starts_with("[deploy]") {
            "deploy"
        } else if line.starts_with("[发布恢复]") {
            "recover"
        } else {
            "export"
        };
        let _ = err;
        self.0.log(module, line);
    }
}
