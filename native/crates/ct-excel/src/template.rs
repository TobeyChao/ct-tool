//! Excel 模板写入（任务 1.6 原型）：2D 表头、富文本、合并、冻结、
//! Enum Note、数据验证、自定义属性。
//!
//! 逐语义移植 `ct/excel/canonical_template.py`；与 Python 产出的对照方式：
//! `fixtures/template/compare_semantics.py`（openpyxl 语义转储 diff）+
//! `tests/compat/tests/template_semantics.rs`（zip 结构断言）。

use std::collections::BTreeMap;

pub use crate::layout::{Column as ColumnDoc, Layout as LayoutDoc};
use anyhow::{bail, Result};
use rust_xlsxwriter::{
    Color, DataValidation, DataValidationRule, Format, FormatAlign, FormatBorder, FormatPattern,
    Worksheet,
};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct EnumItemDoc {
    pub name: String,
    #[serde(default)]
    pub comment: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EnumDoc {
    #[serde(default)]
    pub comment: String,
    pub values: Vec<EnumItemDoc>,
}

pub type EnumMap = BTreeMap<String, EnumDoc>;

/// `segments_for`：稳定路径按 `[g]` 组标记展开为表头层级段。
pub fn segments_for(table_id: &str, stable_path: &str) -> Vec<String> {
    let tail = &stable_path[table_id.len() + 1..];
    let mut segments = Vec::new();
    for chunk in tail.split('/') {
        if let Some(bracket) = chunk.find('[') {
            let name = &chunk[..bracket];
            let group = chunk[bracket + 1..].split(']').next().unwrap_or("");
            segments.push(name.to_string());
            segments.push(format!("#{group}"));
        } else {
            segments.push(chunk.to_string());
        }
    }
    segments
}

/// `top_segment_for`：顶层字段名（不含组标记）。
pub fn top_segment_for(table_id: &str, stable_path: &str) -> String {
    let tail = &stable_path[table_id.len() + 1..];
    let head = tail.split('/').next().unwrap_or("");
    head.split('[').next().unwrap_or("").to_string()
}

fn rgb(argb: u32) -> Color {
    Color::RGB(argb & 0x00FF_FFFF)
}

const FILL_NORMAL: u32 = 0xFFE2E8F0;
const FILL_GROUP: u32 = 0xFFCFE8D8;
const FILL_ARRAY: u32 = 0xFFD7E6FA;
const FILL_SLOT: u32 = 0xFFE7D9F7;
const FILL_PRIMARY: u32 = 0xFFFBE6A5;
const FILL_COMMENT: u32 = 0xFFDCE3EC;

/// 表头单元格格式：居中换行 + 细边框 + 填充；最左/最右列粗边，末行双线底边。
fn header_format(
    fill: u32,
    comment_font: bool,
    left_edge: bool,
    right_edge: bool,
    bottom_edge: bool,
) -> Format {
    let thin = || FormatBorder::Thin;
    let mut fmt = Format::new()
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter)
        .set_text_wrap()
        .set_border_top(thin())
        .set_border_bottom(thin())
        .set_border_left(thin())
        .set_border_right(thin())
        .set_pattern(FormatPattern::Solid)
        .set_foreground_color(rgb(fill));
    if comment_font {
        fmt = fmt
            .set_font_name("Aptos")
            .set_font_size(9.0)
            .set_font_color(rgb(0xFF475569));
    }
    if left_edge {
        fmt = fmt
            .set_border_left(FormatBorder::Medium)
            .set_border_left_color(rgb(0xFF0F172A));
    }
    if right_edge {
        fmt = fmt
            .set_border_right(FormatBorder::Medium)
            .set_border_right_color(rgb(0xFF0F172A));
    }
    if bottom_edge {
        fmt = fmt
            .set_border_bottom(FormatBorder::Double)
            .set_border_bottom_color(rgb(0xFF334155));
    }
    fmt
}

fn name_run_format() -> Format {
    Format::new()
        .set_font_name("Aptos")
        .set_bold()
        .set_font_size(11.0)
        .set_font_color(rgb(0xFF172033))
}

fn type_run_format(color: u32) -> Format {
    Format::new()
        .set_font_name("Consolas")
        .set_italic()
        .set_font_size(9.0)
        .set_font_color(rgb(color))
}

struct RichAnchor {
    row: u32,
    col: u16,
    name: String,
    annotation: String,
    type_color: u32,
    format: Format,
}

struct PlainCell {
    row: u32,
    col: u16,
    text: String,
    format: Format,
}

/// 模板写入器：先汇总合并与锚点，再一次性写入（merge 在内容之前声明）。
pub struct TemplateWriter<'a> {
    layout: &'a LayoutDoc,
    enums: &'a EnumMap,
    primary: &'a str,
    warnings: Vec<String>,
}

impl<'a> TemplateWriter<'a> {
    pub fn new(layout: &'a LayoutDoc, enums: &'a EnumMap, primary: &'a str) -> Self {
        TemplateWriter {
            layout,
            enums,
            primary,
            warnings: Vec::new(),
        }
    }

    pub fn warnings(&self) -> &[String] {
        &self.warnings
    }

    /// 把模板写入 worksheet（数据区不写；迁移在其后追加数据行）。
    pub fn write_sheet(&mut self, ws: &mut Worksheet) -> Result<()> {
        let layout = self.layout;
        let table_name = layout
            .table_id
            .split(':')
            .nth(1)
            .unwrap_or(&layout.table_id)
            .to_string();
        ws.set_name(&table_name)?;

        let col_count = layout.columns.len() as u32;
        let header_rows = layout.header_rows;
        let max_depth = header_rows / 2;

        // rust_xlsxwriter：行 u32、列 u16，均 0-based
        let mut merges: Vec<(u32, u16, u32, u16)> = Vec::new();
        let mut anchors: Vec<RichAnchor> = Vec::new();
        let mut comments: Vec<PlainCell> = Vec::new();
        // (row, col) -> 填充色（供边框兜底格式使用）
        let mut fills: BTreeMap<(u32, u32), u32> = BTreeMap::new();
        // 注释行高度
        let mut comment_heights: BTreeMap<u32, f64> = BTreeMap::new();
        // 枚举 Note：(row, col) -> 文本
        let mut notes: BTreeMap<(u32, u32), String> = BTreeMap::new();
        // 浅层叶的纵向合并起点（按列）
        let mut leaf_merge_start: BTreeMap<u32, u32> = BTreeMap::new();

        for depth in 1..=max_depth {
            // 按路径前缀分组
            let mut grouped: Vec<(Vec<String>, Vec<&ColumnDoc>)> = Vec::new();
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

            let comment_row = depth * 2 - 1;
            let field_row = depth * 2;
            for (parts, cols) in &grouped {
                let start = cols[0].index;
                let end = cols[cols.len() - 1].index;
                if start < end {
                    merges.push((
                        comment_row - 1,
                        (start - 1) as u16,
                        comment_row - 1,
                        (end - 1) as u16,
                    ));
                    merges.push((
                        field_row - 1,
                        (start - 1) as u16,
                        field_row - 1,
                        (end - 1) as u16,
                    ));
                }
                let segment = parts.last().unwrap().clone();
                let annotation = if cols[0].field_annotation.is_empty() {
                    cols[0].annotation.clone()
                } else {
                    cols[0].field_annotation.clone()
                };
                let annotation = if depth > 1 && segment.starts_with('#') {
                    cols[0].type_text.clone()
                } else {
                    annotation
                };
                let leaf_depth = segments_for(&layout.table_id, &cols[0].stable_path).len() as u32;
                let is_leaf = depth >= leaf_depth;
                let top_type = if cols[0].field_annotation.is_empty() {
                    cols[0].annotation.clone()
                } else {
                    cols[0].field_annotation.clone()
                };
                let is_primary = depth == 1 && segment == self.primary;
                let (node_fill, type_color) = if depth == 1 && top_type.starts_with("vector<") {
                    (FILL_ARRAY, 0xFF315B9A)
                } else if segment.starts_with('#') {
                    (FILL_SLOT, 0xFF6B4AA1)
                } else if !is_leaf {
                    (FILL_GROUP, 0xFF2F6B4A)
                } else {
                    (FILL_NORMAL, 0xFF64748B)
                };
                let (node_fill, type_color) = if is_primary {
                    (FILL_PRIMARY, 0xFF8A5A00)
                } else {
                    (node_fill, type_color)
                };

                let comment = if depth == 1 {
                    let c = if cols[0].field_comment.is_empty() {
                        &cols[0].comment
                    } else {
                        &cols[0].field_comment
                    };
                    c.clone()
                } else {
                    cols[0].comment.clone()
                };

                for col in start..=end {
                    fills.insert((comment_row, col), FILL_COMMENT);
                    fills.insert((field_row, col), node_fill);
                }

                anchors.push(RichAnchor {
                    row: field_row - 1,
                    col: (start - 1) as u16,
                    name: segment,
                    annotation,
                    type_color,
                    format: header_format(
                        node_fill,
                        false,
                        start == 1,
                        end == col_count,
                        field_row == header_rows,
                    ),
                });
                comments.push(PlainCell {
                    row: comment_row - 1,
                    col: (start - 1) as u16,
                    text: comment.clone(),
                    format: header_format(
                        FILL_COMMENT,
                        true,
                        start == 1,
                        end == col_count,
                        comment_row == header_rows,
                    ),
                });

                if !comment.is_empty() {
                    let width = ((end - start + 1).max(1) * 16) as f64;
                    let chars_per_line = (width / 1.2) as usize;
                    let chars_per_line = chars_per_line.max(10);
                    let lines: usize = comment
                        .split('\n')
                        .map(|line| line.len().div_ceil(chars_per_line).max(1))
                        .sum();
                    let height = (18 * lines as u32).clamp(30, 60);
                    comment_heights.insert(comment_row, height as f64);
                }
            }
        }

        // 浅层叶的纵向合并（跨越剩余表头行）
        for column in &layout.columns {
            let leaf_depth = segments_for(&layout.table_id, &column.stable_path).len() as u32;
            if leaf_depth >= max_depth {
                continue;
            }
            let start_row = leaf_depth * 2;
            if start_row == header_rows {
                continue;
            }
            merges.push((
                start_row - 1,
                (column.index - 1) as u16,
                header_rows - 1,
                (column.index - 1) as u16,
            ));
            leaf_merge_start.insert(column.index, start_row);
        }

        // ---- 写入：先全部空白+格式，再合并，再锚点内容 ----
        for row in 1..=header_rows {
            for col in 1..=col_count {
                let fill = fills.get(&(row, col)).copied().unwrap_or(FILL_NORMAL);
                let fmt = header_format(
                    fill,
                    row % 2 == 1,
                    col == 1,
                    col == col_count,
                    row == header_rows,
                );
                ws.write_blank(row - 1, (col - 1) as u16, &fmt)?;
            }
        }
        for (r1, c1, r2, c2) in &merges {
            // 合并区域格式以锚点格式为准（write_blank 已铺底，这里仅声明合并）
            let anchor_fill = fills
                .get(&(r1 + 1, (*c1 + 1) as u32))
                .copied()
                .unwrap_or(FILL_NORMAL);
            let fmt = header_format(
                anchor_fill,
                (r1 + 1) % 2 == 1,
                *c1 == 0,
                (*c2 + 1) as u32 == col_count,
                r2 + 1 == header_rows,
            );
            ws.merge_range(*r1, *c1, *r2, *c2, "", &fmt)?;
        }
        let name_fmt = name_run_format();
        for anchor in &anchors {
            let type_fmt = type_run_format(anchor.type_color);
            ws.write_rich_string_with_format(
                anchor.row,
                anchor.col,
                &[
                    (&name_fmt, format!("{}\n", anchor.name).as_str()),
                    (&type_fmt, anchor.annotation.as_str()),
                ],
                &anchor.format,
            )?;
        }
        for cell in &comments {
            if cell.text.is_empty() {
                continue;
            }
            ws.write_string_with_format(cell.row, cell.col, &cell.text, &cell.format)?;
        }

        // ---- 尺寸与冻结 ----
        for col in 1..=col_count {
            ws.set_column_width((col - 1) as u16, 16.0)?;
        }
        for row in 1..=header_rows {
            if let Some(&h) = comment_heights.get(&row) {
                ws.set_row_height(row - 1, h)?;
            } else {
                ws.set_row_height(row - 1, if row % 2 == 1 { 30.0 } else { 38.0 })?;
            }
        }
        ws.set_freeze_panes(header_rows, 0)?;
        // 把活动单元格锚定到可滚动窗格的首个数据行（否则 Excel 首屏
        // 会在两个窗格各画一次表头）。
        ws.set_selection(header_rows, 0, header_rows, 0)?;

        // ---- Enum Note ----
        for column in &layout.columns {
            let Some(enum_doc) = self.enums.get(&column.type_text) else {
                continue;
            };
            let mut lines = vec![format!("类型：{}", column.type_text)];
            if !enum_doc.comment.is_empty() {
                lines[0].push_str(&format!("；{}", enum_doc.comment));
            }
            for item in &enum_doc.values {
                if item.comment.is_empty() {
                    lines.push(item.name.clone());
                } else {
                    lines.push(format!("{}: {}", item.name, item.comment));
                }
            }
            let target_row_1based = (column.depth * 2).max(2);
            // 若目标位于纵向合并内，移到合并锚点
            let target_row = match leaf_merge_start.get(&column.index) {
                Some(&start) if start <= target_row_1based => start,
                _ => target_row_1based,
            };
            notes.insert((target_row, column.index), lines.join("\n"));
        }
        for ((row, col), text) in &notes {
            // 不设作者名：rust_xlsxwriter 会把作者名写进批注文本前缀，与 golden 不一致。
            ws.insert_note(
                row - 1,
                (col - 1) as u16,
                &rust_xlsxwriter::Note::new(text).add_author_prefix(false),
            )?;
        }

        // ---- 数据验证 ----
        let data_start_0 = header_rows; // 0-based 首个数据行
        let last_row_0 = 1_048_575u32; // Excel 最大行（1-based 1048576）
        for column in &layout.columns {
            let col0 = (column.index - 1) as u16;
            match column.type_text.as_str() {
                "bool" => {
                    let dv = DataValidation::new().allow_list_strings(&["TRUE", "FALSE"])?;
                    ws.add_data_validation(data_start_0, col0, last_row_0, col0, &dv)?;
                }
                "int32" => {
                    let dv = DataValidation::new()
                        .allow_whole_number(DataValidationRule::Between(i32::MIN, i32::MAX));
                    ws.add_data_validation(data_start_0, col0, last_row_0, col0, &dv)?;
                }
                "float" | "double" => {
                    // 用公式形态写出，与 golden 的 "-1E+307" 文本一致
                    let dv = DataValidation::new().allow_decimal_number_formula(
                        DataValidationRule::Between(
                            rust_xlsxwriter::Formula::new("-1E+307"),
                            rust_xlsxwriter::Formula::new("1E+307"),
                        ),
                    );
                    ws.add_data_validation(data_start_0, col0, last_row_0, col0, &dv)?;
                }
                other => {
                    let Some(enum_doc) = self.enums.get(other) else {
                        continue;
                    };
                    let names: Vec<&str> =
                        enum_doc.values.iter().map(|v| v.name.as_str()).collect();
                    let formula = format!("\"{}\"", names.join(","));
                    if formula.len() > 255 {
                        self.warnings.push(format!(
                            "Enum {other} 候选超过 Excel 255 字符限制，请参考表头 Note 填写"
                        ));
                        continue;
                    }
                    let dv = DataValidation::new().allow_list_strings(&names)?;
                    ws.add_data_validation(data_start_0, col0, last_row_0, col0, &dv)?;
                }
            }
        }

        Ok(())
    }
}

/// 自定义属性名（与 Python `_write_metadata` 一致）。
pub const META_TOOL_VERSION: &str = "ct_tool_version";
pub const META_TABLE_NAME: &str = "ct_table_name";
pub const META_HEADER_ROWS: &str = "ct_header_rows";
pub const META_SCHEMA_HASH: &str = "ct_schema_hash";
pub const META_GENERATED_AT: &str = "ct_generated_at";

/// 生成模板工作簿字节。
pub fn build_template(
    layout: &LayoutDoc,
    enums: &EnumMap,
    primary: &str,
) -> Result<(Vec<u8>, Vec<String>)> {
    build_template_with_rows(layout, enums, primary, &[])
}

/// 生成模板工作簿字节，并在数据区写入初始数据行。
///
/// 与 `build_template` 同源（表头、合并、冻结、数据验证、自定义属性完全一致），
/// 只多写数据行；夹具生成需要有数据的真实形状工作簿，迁移路径之外没有别的写入入口。
pub fn build_template_with_rows(
    layout: &LayoutDoc,
    enums: &EnumMap,
    primary: &str,
    rows: &[Vec<Option<crate::migrate::CellValue>>],
) -> Result<(Vec<u8>, Vec<String>)> {
    let mut workbook = rust_xlsxwriter::Workbook::new();
    let mut writer = TemplateWriter::new(layout, enums, primary);
    {
        let ws = workbook.add_worksheet();
        writer.write_sheet(ws)?;
        let mut row0 = layout.header_rows; // 0-based 首个数据行
        for cells in rows {
            for (index, value) in cells.iter().enumerate() {
                let Some(value) = value else { continue };
                let col0 = index as u16;
                match value {
                    crate::migrate::CellValue::Text(text) => ws.write_string(row0, col0, text)?,
                    crate::migrate::CellValue::Number(number) => {
                        ws.write_number(row0, col0, *number)?
                    }
                    crate::migrate::CellValue::Bool(flag) => ws.write_boolean(row0, col0, *flag)?,
                    crate::migrate::CellValue::Other(text) => ws.write_string(row0, col0, text)?,
                };
            }
            row0 += 1;
        }
    }
    let table_name = layout
        .table_id
        .split(':')
        .nth(1)
        .unwrap_or(&layout.table_id);
    // 注意：rust_xlsxwriter 0.99 的自定义属性不支持 filetime 类型
    // （IntoCustomProperty 不含 ExcelDateTime），ct_generated_at 暂以
    // Unix 秒整数写入；对照只校验键存在性。升级库或手写 vt:filetime 时补齐。
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i32)
        .unwrap_or(0);
    let props = rust_xlsxwriter::DocProperties::new()
        .set_custom_property(META_TOOL_VERSION, "ct")
        .set_custom_property(META_TABLE_NAME, table_name)
        .set_custom_property(META_HEADER_ROWS, layout.header_rows as i32)
        .set_custom_property(META_SCHEMA_HASH, layout.schema_hash.as_str())
        .set_custom_property(META_GENERATED_AT, now);
    workbook.set_properties(&props);

    let bytes = workbook.save_to_buffer()?;
    let warnings = std::mem::take(&mut writer.warnings);
    if warnings.iter().any(|w| w.is_empty()) {
        bail!("内部错误：空 warning");
    }
    Ok((bytes, warnings))
}
