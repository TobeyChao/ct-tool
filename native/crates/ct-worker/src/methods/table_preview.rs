//! table.preview：分页只读预览（绑定快照代次，过期令牌返回 stale-page）。

use std::path::Path;

use ct_app::workspace::Workspace;
use ct_protocol::dto::excel::{PreviewColumn, TablePreviewParams, TablePreviewResult};
use ct_protocol::error::ErrorCode;
use ct_protocol::pagination::PageRequest;
use serde_json::Value;

use crate::dispatcher::{Failure, HandlerResult};
use crate::issue_of;
use crate::session::Session;

const DEFAULT_LIMIT: usize = 200;
const MAX_LIMIT: usize = 1000;

pub fn preview(session: &mut Session, root: &Path, params: &Value) -> HandlerResult {
    let parsed: TablePreviewParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("table.preview 参数非法: {e}")))?;
    let page: PageRequest = parsed.page.clone();
    let offset = session
        .resolve_page(page.cursor.as_deref())
        .map_err(|code| Failure::new(code, "分页令牌已过期，请整页重查"))?;
    let limit = page
        .limit
        .unwrap_or(DEFAULT_LIMIT as u32)
        .clamp(1, MAX_LIMIT as u32) as usize;

    let workspace = Workspace::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.0))?;
    let prepared = ct_app::validate::prepare_tables(&workspace, Some(&parsed.table), false, None);
    if prepared.unknown_table.is_some() {
        return Err(Failure::new(
            ErrorCode::Internal,
            format!("表 '{}' 不存在", parsed.table),
        ));
    }
    if !prepared.issues.is_empty() {
        return Err(Failure::with_issues(
            format!("表 '{}' 预览失败", parsed.table),
            prepared.issues.iter().map(issue_of).collect(),
        ));
    }
    let item = prepared.prepared.first().ok_or_else(|| {
        Failure::new(
            ErrorCode::Internal,
            format!("表 '{}' 无预览数据", parsed.table),
        )
    })?;
    let columns: Vec<PreviewColumn> = item
        .table
        .fields
        .iter()
        .map(|f| PreviewColumn {
            name: f.name.clone(),
            type_expr: f.type_text(),
            role: if f.name == item.table.primary {
                Some("primary".to_string())
            } else if f.i18n {
                Some("i18n".to_string())
            } else if f.server_only {
                Some("server_only".to_string())
            } else {
                None
            },
            i18n: f.i18n.then_some(true),
            server_only: f.server_only.then_some(true),
            comment: (!f.comment.is_empty()).then(|| f.comment.clone()),
            ref_: f.ref_.clone(),
            excel_columns: f.excel_columns,
        })
        .collect();
    // 行数组与列对齐；空单元格为 null（超范围整数由 bigint 规则在出站时编码）
    let rows: Vec<Vec<Value>> = item
        .parsed
        .rows
        .iter()
        .skip(offset)
        .take(limit)
        .map(|row| {
            item.table
                .fields
                .iter()
                .map(|f| row.get(&f.name).cloned().unwrap_or(Value::Null))
                .collect()
        })
        .collect();
    let next_offset = offset + rows.len();
    let next_cursor =
        (next_offset < item.parsed.rows.len()).then(|| session.page_token(next_offset));
    let result = TablePreviewResult {
        revision: session.snapshot_revision,
        columns,
        rows,
        next_cursor,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}
