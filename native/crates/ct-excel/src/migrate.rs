//! Excel 数据迁移（任务 1.6 原型）：按稳定列路径把旧工作簿数据迁入新模板。
//!
//! 逐语义移植 `ct/excel/planning.py::plan_excel_migration` 与
//! `ct/app/canonical_commands.py::_migrate_excel_rows` 的安全闸门：
//! 缺 manifest / 删除列有数据 / 类型不可转换 → 拒绝，不产生任何写入。

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::{bail, Result};

use crate::layout::{Column, Layout};
use crate::reader::{probe_xlsx, ProbeValue};
use crate::template::EnumMap;

/// 迁移单元格值（calamine 数据区的可用形态）。
#[derive(Debug, Clone, PartialEq)]
pub enum CellValue {
    Text(String),
    Number(f64),
    Bool(bool),
    /// 日期/其他形态按 ISO/文本透传（数据区实践上不出现公式）。
    Other(String),
}

impl CellValue {
    fn is_blank(&self) -> bool {
        matches!(self, CellValue::Text(s) if s.trim().is_empty())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IssueKind {
    Blocker,
    Warning,
    Untracked,
}

#[derive(Debug, Clone)]
pub struct PlanIssue {
    pub kind: IssueKind,
    pub message: String,
    pub field_path: String,
    pub rows: Vec<u32>,
}

#[derive(Debug, Clone)]
pub struct ColumnMigration {
    pub old_index: u32,
    pub new_index: Option<u32>,
    pub old_path: String,
    pub new_path: Option<String>,
}

#[derive(Debug, Default)]
pub struct ExcelPlan {
    pub migrations: Vec<ColumnMigration>,
    pub issues: Vec<PlanIssue>,
    pub untracked: bool,
}

impl ExcelPlan {
    pub fn blocked(&self) -> bool {
        self.untracked || self.issues.iter().any(|i| i.kind == IssueKind::Blocker)
    }
}

fn logical_path(stable_path: &str, group_index: Option<u32>) -> String {
    if group_index.is_none() {
        return stable_path.to_string();
    }
    match stable_path.find('[') {
        Some(open) => {
            let close = stable_path[open..]
                .find(']')
                .map(|c| open + c)
                .unwrap_or(open);
            format!("{}{}", &stable_path[..open], &stable_path[close + 1..])
        }
        None => stable_path.to_string(),
    }
}

/// 类型可转换性（对齐 Python `canonical_reader._coerce_scalar` 的可承载判定）。
fn coerce_ok(new_type: &str, value: &CellValue) -> bool {
    if new_type == "string" {
        return true;
    }
    if new_type == "bool" {
        return match value {
            CellValue::Bool(_) => true,
            CellValue::Text(t) => matches!(
                t.trim(),
                "true"
                    | "false"
                    | "1"
                    | "0"
                    | "yes"
                    | "no"
                    | "TRUE"
                    | "FALSE"
                    | "True"
                    | "False"
                    | "YES"
                    | "NO"
                    | "Yes"
                    | "No"
                    | "✓"
                    | "✗"
            ),
            _ => false,
        };
    }
    if new_type == "float" || new_type == "double" {
        return match value {
            CellValue::Number(_) | CellValue::Bool(_) => true,
            CellValue::Text(t) => t.trim().parse::<f64>().is_ok(),
            CellValue::Other(_) => false,
        };
    }
    if let Some((low, high)) = ct_domain::types::integer_scalar_range(new_type) {
        return match value {
            CellValue::Number(n) => n.fract() == 0.0 && *n >= low as f64 && *n <= high as f64,
            // int(True)=1，与 Python int(raw) 对 bool 的行为一致
            CellValue::Bool(_) => true,
            CellValue::Text(t) => t
                .trim()
                .parse::<i128>()
                .is_ok_and(|v| v >= low && v <= high),
            CellValue::Other(_) => false,
        };
    }
    // enum / 具名：字符串标识，任何值按 str(raw) 承载
    true
}

/// 规划迁移：stable path 优先，logical path 仅在唯一命中时兜底。
pub fn plan_migration(
    old_layout: &Layout,
    new_layout: &Layout,
    data_rows: &[(u32, Vec<Option<CellValue>>)],
    has_manifest: bool,
    rename_map: &HashMap<String, String>,
) -> ExcelPlan {
    let new_stable: HashMap<&str, &Column> = new_layout
        .columns
        .iter()
        .map(|c| (c.stable_path.as_str(), c))
        .collect();
    // logical path → 候选新列（多个则不可安全兜底）
    let mut new_logical: HashMap<String, Vec<&Column>> = HashMap::new();
    for column in &new_layout.columns {
        new_logical
            .entry(logical_path(&column.stable_path, column.group_index))
            .or_default()
            .push(column);
    }

    let mut plan = ExcelPlan {
        untracked: !has_manifest,
        ..Default::default()
    };
    let mut new_used: HashSet<u32> = HashSet::new();

    for old_column in &old_layout.columns {
        let stable_mapped = rename_map
            .get(&old_column.stable_path)
            .cloned()
            .unwrap_or_else(|| old_column.stable_path.clone());
        let mut target = new_stable.get(stable_mapped.as_str()).copied();
        if target.is_none() {
            let logical = logical_path(&old_column.stable_path, old_column.group_index);
            let mapped = rename_map.get(&logical).cloned().unwrap_or(logical);
            target = new_stable.get(mapped.as_str()).copied();
            if target.is_none() {
                let candidates = new_logical.get(&mapped);
                if let Some(cols) = candidates {
                    if cols.len() == 1 {
                        target = Some(cols[0]);
                    }
                }
            }
        }

        let col_idx = (old_column.index - 1) as usize;
        let populated: Vec<u32> = data_rows
            .iter()
            .filter(|(_, row)| {
                row.get(col_idx)
                    .is_some_and(|v| matches!(v, Some(v) if !v.is_blank()))
            })
            .map(|(excel_row, _)| *excel_row)
            .collect();

        match target {
            None => {
                plan.migrations.push(ColumnMigration {
                    old_index: old_column.index,
                    new_index: None,
                    old_path: old_column.stable_path.clone(),
                    new_path: None,
                });
                if !populated.is_empty() {
                    plan.issues.push(PlanIssue {
                        kind: IssueKind::Blocker,
                        message: format!("字段 {} 被删除但存在非空数据", old_column.stable_path),
                        field_path: old_column.stable_path.clone(),
                        rows: populated.into_iter().take(5).collect(),
                    });
                }
            }
            Some(new_column) => {
                if new_used.contains(&new_column.index) {
                    plan.migrations.push(ColumnMigration {
                        old_index: old_column.index,
                        new_index: None,
                        old_path: old_column.stable_path.clone(),
                        new_path: None,
                    });
                    if !populated.is_empty() {
                        plan.issues.push(PlanIssue {
                            kind: IssueKind::Blocker,
                            message: format!(
                                "字段 {} 的目标列被先前列占用",
                                old_column.stable_path
                            ),
                            field_path: old_column.stable_path.clone(),
                            rows: populated.into_iter().take(5).collect(),
                        });
                    }
                    continue;
                }
                new_used.insert(new_column.index);
                plan.migrations.push(ColumnMigration {
                    old_index: old_column.index,
                    new_index: Some(new_column.index),
                    old_path: old_column.stable_path.clone(),
                    new_path: Some(new_column.stable_path.clone()),
                });
                if old_column.type_text != new_column.type_text {
                    let failed: Vec<u32> = data_rows
                        .iter()
                        .filter(|(_, row)| {
                            matches!(row.get(col_idx), Some(Some(v)) if !v.is_blank() && !coerce_ok(&new_column.type_text, v))
                        })
                        .map(|(excel_row, _)| *excel_row)
                        .collect();
                    if !failed.is_empty() {
                        plan.issues.push(PlanIssue {
                            kind: IssueKind::Blocker,
                            message: format!(
                                "字段 {} 类型从 {} 变为 {}，存在无法转换的数据",
                                old_column.stable_path, old_column.type_text, new_column.type_text
                            ),
                            field_path: old_column.stable_path.clone(),
                            rows: failed.into_iter().take(5).collect(),
                        });
                    }
                }
            }
        }
    }

    if plan.untracked {
        plan.issues.push(PlanIssue {
            kind: IssueKind::Untracked,
            message: "Excel 缺少可信路径清单（layout manifest），列映射需人工核对，不允许静默写回"
                .to_string(),
            field_path: String::new(),
            rows: vec![],
        });
    }
    plan
}

/// 读取数据区（表头之后），返回 (excel_row, 单元格向量)。
pub fn read_data_rows(path: &Path, header_rows: u32) -> Result<Vec<(u32, Vec<Option<CellValue>>)>> {
    let report = probe_xlsx(path)?;
    let max_col = report.cells.iter().map(|c| c.col).max().unwrap_or(0);
    let mut by_row: BTreeMapExt = BTreeMapExt::new();
    for cell in &report.cells {
        if cell.row <= header_rows {
            continue;
        }
        let value = match &cell.value {
            ProbeValue::Text(s) => CellValue::Text(s.clone()),
            ProbeValue::Number(n) => CellValue::Number(*n),
            ProbeValue::Bool(b) => CellValue::Bool(*b),
            ProbeValue::DateTime(s) | ProbeValue::Error(s) => CellValue::Other(s.clone()),
        };
        by_row.push(cell.row, cell.col, value);
    }
    Ok(by_row.into_rows(max_col))
}

/// 行聚合小工具（保持读顺序）。
struct BTreeMapExt {
    rows: Vec<(u32, Vec<Option<CellValue>>)>,
}

impl BTreeMapExt {
    fn new() -> Self {
        BTreeMapExt { rows: Vec::new() }
    }

    fn push(&mut self, row: u32, col: u32, value: CellValue) {
        if self.rows.last().map(|(r, _)| *r) != Some(row) {
            self.rows.push((row, Vec::new()));
        }
        let (_, cells) = self.rows.last_mut().unwrap();
        let idx = (col - 1) as usize;
        if cells.len() <= idx {
            cells.resize(idx + 1, None);
        }
        cells[idx] = Some(value);
    }

    fn into_rows(self, _max_col: u32) -> Vec<(u32, Vec<Option<CellValue>>)> {
        self.rows
    }
}

/// 生成迁移后的工作簿字节：新模板 + 按列映射的数据行。
pub fn migrate_workbook(
    old_path: &Path,
    old_layout: &Layout,
    new_layout: &Layout,
    has_manifest: bool,
    rename_map: &HashMap<String, String>,
    enums: &EnumMap,
    primary: &str,
) -> Result<(Vec<u8>, Vec<String>)> {
    let data_rows = read_data_rows(old_path, old_layout.header_rows)?;
    let plan = plan_migration(old_layout, new_layout, &data_rows, has_manifest, rename_map);
    if plan.blocked() {
        let details: Vec<String> = plan.issues.iter().map(|i| i.message.clone()).collect();
        bail!("Excel 数据无法安全迁移：{}", details.join("；"));
    }

    let targets: HashMap<u32, u32> = plan
        .migrations
        .iter()
        .filter_map(|m| m.new_index.map(|n| (m.old_index, n)))
        .collect();

    let mut workbook = rust_xlsxwriter::Workbook::new();
    let mut writer = crate::template::TemplateWriter::new(new_layout, enums, primary);
    {
        let ws = workbook.add_worksheet();
        writer.write_sheet(ws)?;
        let mut new_row = new_layout.header_rows; // 0-based 首个数据行
        for (_excel_row, cells) in &data_rows {
            let any_value = targets.keys().any(|old_index| {
                matches!(cells.get((*old_index - 1) as usize), Some(Some(v)) if !v.is_blank())
            });
            if !any_value {
                continue;
            }
            for (old_index, new_index) in &targets {
                let Some(Some(value)) = cells.get((*old_index - 1) as usize) else {
                    continue;
                };
                match value {
                    CellValue::Text(s) => ws.write_string(new_row, (*new_index - 1) as u16, s)?,
                    CellValue::Number(n) => {
                        ws.write_number(new_row, (*new_index - 1) as u16, *n)?
                    }
                    CellValue::Bool(b) => ws.write_boolean(new_row, (*new_index - 1) as u16, *b)?,
                    CellValue::Other(s) => ws.write_string(new_row, (*new_index - 1) as u16, s)?,
                };
            }
            new_row += 1;
        }
    }
    let warnings = writer.warnings().to_vec();
    Ok((workbook.save_to_buffer()?, warnings))
}
