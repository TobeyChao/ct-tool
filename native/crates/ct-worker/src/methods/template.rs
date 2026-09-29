//! template.plan / template.generate：迁移预检与显式生成。

use std::path::Path;

use ct_app::workspace::Workspace;
use ct_protocol::dto::excel::{
    TemplateGenerateParams, TemplateGenerateResult, TemplatePlanParams, TemplatePlanResult,
};
use ct_protocol::error::ErrorCode;
use ct_protocol::event::Issue;
use serde_json::Value;

use crate::dispatcher::{Emitter, Failure, HandlerResult};
use crate::task::CancelFlag;

fn issue(message: impl Into<String>) -> Issue {
    Issue {
        code: "template".to_string(),
        message: message.into(),
        resource: None,
        field_path: None,
        excel_row: None,
        file: None,
    }
}

pub fn plan(root: &Path, params: &Value) -> HandlerResult {
    let parsed: TemplatePlanParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("template.plan 参数非法: {e}")))?;
    let workspace = Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    let table = workspace
        .resources
        .tables
        .iter()
        .find(|t| t.table == parsed.table)
        .ok_or_else(|| {
            Failure::new(ErrorCode::Internal, format!("表 '{}' 不存在", parsed.table))
        })?;
    let excel_path = workspace.excel_dir().join(table.resolved_excel_file());
    let manifest = std::fs::read_to_string(
        workspace
            .manifest_dir()
            .join(format!("{}.json", table.table)),
    )
    .ok()
    .and_then(|text| serde_json::from_str::<Value>(&text).ok())
    .and_then(|value| ct_excel::manifest::LayoutManifest::parse(&value));
    let mut actions = Vec::new();
    let mut problems = Vec::new();
    let mut warnings = Vec::new();
    if !excel_path.exists() {
        actions.push("生成空模板（工作簿不存在）".to_string());
    } else if manifest.is_none() {
        problems.push(issue(format!(
            "{} 的 Excel 缺少布局 manifest，无法安全迁移；请先备份后删除旧文件，再重新生成空模板",
            table.table
        )));
    } else {
        actions.push("重建表头（样式与 stable column path）".to_string());
        actions.push("按稳定列路径迁移数据".to_string());
        let old_layout = manifest
            .expect("已确认存在")
            .to_layout(&table.resource_id());
        let records = workspace.resources.records_map();
        let enums = workspace.resources.enums_map();
        let layout = ct_excel::layout::build_layout(
            table,
            &ct_domain::hashing::compute_schema_hash(
                table,
                &workspace
                    .resources
                    .records
                    .iter()
                    .cloned()
                    .map(ct_domain::repository::Resource::Record)
                    .chain(
                        workspace
                            .resources
                            .enums
                            .iter()
                            .cloned()
                            .map(ct_domain::repository::Resource::Enum),
                    )
                    .collect::<Vec<_>>(),
            ),
            &records,
        );
        let data_rows = ct_excel::migrate::read_data_rows(&excel_path, old_layout.header_rows)
            .map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))?;
        let migration = ct_excel::migrate::plan_migration(
            &old_layout,
            &layout,
            &data_rows,
            true,
            &std::collections::HashMap::new(),
        );
        if migration.blocked() {
            problems.extend(migration.issues.iter().map(|i| issue(&i.message)));
        }
        for warning in &migration.issues {
            if !problems.iter().any(|p| p.message == warning.message) {
                warnings.push(issue(&warning.message));
            }
        }
        let _ = enums;
    }
    let result = TemplatePlanResult {
        can_generate: problems.is_empty(),
        actions,
        warnings,
        problems,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}

pub fn generate(
    root: &Path,
    params: &Value,
    _cancel: &CancelFlag,
    emitter: &Emitter,
) -> HandlerResult {
    let parsed: TemplateGenerateParams = serde_json::from_value(params.clone()).map_err(|e| {
        Failure::new(
            ErrorCode::Internal,
            format!("template.generate 参数非法: {e}"),
        )
    })?;
    let workspace = Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    emitter.progress("template", 0, 1);
    let messages = ct_app::template::gen_template(&workspace, Some(&parsed.table), false)
        .map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    for message in &messages {
        emitter.log("template", message);
    }
    emitter.progress("template", 1, 1);
    let result = TemplateGenerateResult {
        migrated_rows: 0,
        warnings: Vec::new(),
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
