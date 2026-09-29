//! 读取兼容闸门（`ct/excel/reading_compat.py`）：
//! 在解释任何数据之前证明工作簿可按当前布局读取（manifest + 受管表头）。

use std::path::Path;

use ct_domain::diagnostics::{column_letter, IssueCode, ValidationIssue};

use crate::layout::Layout;
use crate::manifest::LayoutManifest;
use crate::reader::probe_xlsx;
use crate::template::segments_for;

/// 闸门结果。
pub struct ReadingCompatibility {
    pub ok: bool,
    pub issues: Vec<ValidationIssue>,
    pub reason: String,
}

fn cell_text(value: &crate::reader::ProbeValue) -> String {
    match value {
        crate::reader::ProbeValue::Text(s) => {
            if s.trim().is_empty() {
                String::new()
            } else {
                s.clone()
            }
        }
        crate::reader::ProbeValue::Number(n) => crate::canonical::raw_number_text(*n),
        crate::reader::ProbeValue::Bool(b) => b.to_string(),
        crate::reader::ProbeValue::DateTime(s) | crate::reader::ProbeValue::Error(s) => s.clone(),
    }
}

/// 期望的受管表头网格：(row, col) → 文本（`expected_header_grid`）。
pub fn expected_header_grid(layout: &Layout) -> Vec<((u32, u32), String)> {
    let max_depth = layout.header_rows / 2;
    let mut grid: Vec<((u32, u32), String)> = Vec::new();
    for depth in 1..=max_depth {
        let mut grouped: Vec<(Vec<String>, Vec<&Column>)> = Vec::new();
        for column in &layout.columns {
            let parts = segments_for(&layout.table_id, &column.stable_path);
            if parts.len() < depth as usize {
                continue;
            }
            let prefix: Vec<String> = parts[..depth as usize].to_vec();
            if let Some((_, cols)) = grouped.iter_mut().find(|(p, _)| *p == prefix) {
                cols.push(column);
            } else {
                grouped.push((prefix, vec![column]));
            }
        }
        for (parts, cols) in &grouped {
            let anchor = cols.iter().map(|c| c.index).min().unwrap();
            let segment = parts.last().unwrap();
            let annotation = if cols[0].field_annotation.is_empty() {
                &cols[0].annotation
            } else {
                &cols[0].field_annotation
            };
            let annotation = if depth > 1 && segment.starts_with('#') {
                &cols[0].type_text
            } else {
                annotation
            };
            grid.push(((depth * 2, anchor), format!("{segment}\n{annotation}")));
        }
    }
    grid
}

use crate::layout::Column;

/// 读取工作簿的字段行（注释行不参与结构）。
pub fn read_header_grid(excel_path: &Path, header_rows: u32) -> Vec<((u32, u32), String)> {
    let Ok(report) = probe_xlsx(excel_path) else {
        return Vec::new();
    };
    report
        .cells
        .iter()
        .filter(|c| c.row <= header_rows && c.row % 2 == 0)
        .filter_map(|c| {
            let text = cell_text(&c.value);
            if text.is_empty() {
                None
            } else {
                Some(((c.row, c.col), text))
            }
        })
        .collect()
}

fn blocker(table: &str, message: String) -> ValidationIssue {
    ValidationIssue::new(table, IssueCode::Template, message)
}

fn manifest_signature(manifest: &LayoutManifest) -> Vec<(u64, String, String, u64)> {
    manifest
        .columns
        .iter()
        .map(|c| {
            (
                c.get("index").and_then(|v| v.as_u64()).unwrap_or(0),
                c.get("stablePath")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                c.get("typeExpr")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                c.get("depth").and_then(|v| v.as_u64()).unwrap_or(0),
            )
        })
        .collect()
}

fn layout_signature(layout: &Layout) -> Vec<(u64, String, String, u64)> {
    layout
        .columns
        .iter()
        .map(|c| {
            (
                c.index as u64,
                c.stable_path.clone(),
                c.type_text.clone(),
                c.depth as u64,
            )
        })
        .collect()
}

/// 判定 `excel_path` 能否按 `layout` 读取。
pub fn check_reading_compatibility(
    table: &str,
    layout: &Layout,
    excel_path: &Path,
    manifest: Option<&LayoutManifest>,
) -> ReadingCompatibility {
    let Some(manifest) = manifest else {
        return ReadingCompatibility {
            ok: false,
            issues: vec![blocker(
                table,
                format!(
                    "缺少布局 manifest，无法确认 Excel 与当前 schema 的读取布局兼容。\
                     该表还没有工作簿时，运行 `ct gen-template --table {table}` 生成空模板；\
                     已有旧工作簿时，工具不会在缺少 manifest 的情况下搬移数据：\
                     请先备份并删除旧工作簿，再生成空模板并重新录入（见 ct/docs/schema-save-migration.md）。"
                ),
            )],
            reason: "manifest-missing".into(),
        };
    };

    if manifest.header_rows != layout.header_rows {
        return ReadingCompatibility {
            ok: false,
            issues: vec![blocker(
                table,
                format!(
                    "表头行数不一致（manifest {} 行 vs 当前布局 {} 行），数据起始行无法确定；请更新模板",
                    manifest.header_rows, layout.header_rows
                ),
            )],
            reason: "header-rows".into(),
        };
    }

    let expected_columns = layout_signature(layout);
    let manifest_columns = manifest_signature(manifest);
    if manifest_columns != expected_columns {
        let mut detail = "列数与当前布局不同".to_string();
        let mut found = false;
        for (expected, actual) in expected_columns.iter().zip(manifest_columns.iter()) {
            if expected != actual {
                detail = format!(
                    "第 {} 列：manifest 记录 {}（{}，深度 {}），当前布局为 {}（{}，深度 {}）",
                    column_letter(expected.0 as u32),
                    actual.1,
                    actual.2,
                    actual.3,
                    expected.1,
                    expected.2,
                    expected.3
                );
                found = true;
                break;
            }
        }
        if !found {
            let extra = if manifest_columns.len() > expected_columns.len() {
                manifest_columns.get(expected_columns.len())
            } else {
                expected_columns.get(manifest_columns.len())
            };
            if let Some(extra) = extra {
                detail = format!("第 {} 列起托管列数量不同", column_letter(extra.0 as u32));
            }
        }
        return ReadingCompatibility {
            ok: false,
            issues: vec![blocker(
                table,
                format!(
                    "布局 manifest 与当前 schema 的读取结构不一致：{detail}；\
                     保存 YAML 不会重建模板，请先更新模板再校验/导出"
                ),
            )],
            reason: "manifest-layout".into(),
        };
    }

    let expected_grid = expected_header_grid(layout);
    let actual_grid = read_header_grid(excel_path, layout.header_rows);
    let actual: std::collections::HashMap<(u32, u32), &String> =
        actual_grid.iter().map(|(k, v)| (*k, v)).collect();

    for ((row, column), expected_text) in &expected_grid {
        let actual_text = actual.get(&(*row, *column));
        if actual_text == Some(&expected_text) {
            continue;
        }
        let location = format!("{}{}", column_letter(*column), row);
        let detail = match actual_text {
            None => format!("缺少表头单元格 {location}（期望 {expected_text:?}）"),
            Some(actual) => {
                format!("表头单元格 {location} 为 {actual:?}，期望 {expected_text:?}")
            }
        };
        return ReadingCompatibility {
            ok: false,
            issues: vec![blocker(
                table,
                format!(
                    "工作簿表头与当前 schema 的读取结构不一致：{detail}；请更新模板后再校验/导出"
                ),
            )],
            reason: "header-grid".into(),
        };
    }

    ReadingCompatibility {
        ok: true,
        issues: vec![],
        reason: String::new(),
    }
}
