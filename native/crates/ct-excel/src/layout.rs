//! 规范 Excel 列布局（`ct/excel/layout.py` + `layout_manifest.py`）。
//!
//! `Layout` 是 Table 字段 → Excel 列的唯一事实来源：每个叶列携带稳定
//! 规范路径、叶类型文本、表头注释与（定长展开的 vector）组序号。
//! 模板生成、读取、数据迁移与布局 manifest 都消费这一个模型。

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use ct_domain::schema::{FieldDef, RecordResource, TableResource};
use ct_domain::types::{NamedKind, TypeExpr};

/// 布局列。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Column {
    /// 1-based 列位置。
    pub index: u32,
    /// 规范叶路径（含组标记），如 `table:Item/Rewards[1]/Min`。
    pub stable_path: String,
    /// 叶类型表达式文本，如 `int32`。
    pub type_text: String,
    /// 表头注释，如 `vector<DropReward>`。
    pub annotation: String,
    /// 叶显示名（最后一段）。
    pub leaf: String,
    /// 1-based 组序号（展开的 vector）。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub group_index: Option<u32>,
    /// 1-based 发射深度（注释行不计）。
    #[serde(default = "default_depth")]
    pub depth: u32,
    #[serde(default)]
    pub comment: String,
    #[serde(default)]
    pub field_comment: String,
    #[serde(default)]
    pub field_annotation: String,
    #[serde(default, rename = "ref")]
    pub ref_: Option<String>,
    #[serde(default)]
    pub primary: bool,
}

fn default_depth() -> u32 {
    1
}

impl Column {
    /// 去 `[g]` 组标记的逻辑路径（稳定映射兜底用）。
    pub fn logical_path(&self) -> String {
        match self.group_index {
            None => self.stable_path.clone(),
            Some(_) => match self.stable_path.find('[') {
                None => self.stable_path.clone(),
                Some(open) => {
                    let close = self.stable_path[open..]
                        .find(']')
                        .map(|c| open + c)
                        .unwrap_or(open);
                    format!(
                        "{}{}",
                        &self.stable_path[..open],
                        &self.stable_path[close + 1..]
                    )
                }
            },
        }
    }
}

/// 表头结构节点。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeaderNode {
    pub stable_path: String,
    pub display_name: String,
    pub annotation: String,
    pub comment: String,
    pub kind: String,
    pub depth: u32,
    pub children: Vec<String>,
    pub slot_index: Option<u32>,
    pub leaf_start: u32,
    pub leaf_end: u32,
}

/// 完整布局。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Layout {
    pub table_id: String,
    pub schema_hash: String,
    /// 成对注释/字段行数：2 * 最大深度。
    pub header_rows: u32,
    pub columns: Vec<Column>,
    #[serde(default)]
    pub nodes: Vec<HeaderNode>,
}

impl Layout {
    pub fn column_count(&self) -> usize {
        self.columns.len()
    }
}

fn named_kind(
    named: &ct_domain::types::NamedRef,
    records: &HashMap<String, RecordResource>,
) -> NamedKind {
    if let Some(kind) = named.expected_kind() {
        return kind;
    }
    if records.contains_key(named.name()) {
        NamedKind::Record
    } else {
        NamedKind::Enum
    }
}

/// Record 字段树的 1-based 深度（标量叶 = 1）。
fn record_depth(record: &RecordResource, records: &HashMap<String, RecordResource>) -> u32 {
    let mut max_depth = 1;
    for field in &record.fields {
        match &field.type_expr {
            TypeExpr::Named(named) if named_kind(named, records) == NamedKind::Record => {
                if let Some(nested) = records.get(named.name()) {
                    max_depth = max_depth.max(1 + record_depth(nested, records));
                }
            }
            TypeExpr::Vector(element) => {
                if let TypeExpr::Named(named) = element.as_ref() {
                    if named_kind(named, records) == NamedKind::Record
                        && field.excel_columns.unwrap_or(0) > 0
                    {
                        if let Some(nested) = records.get(named.name()) {
                            max_depth = max_depth.max(2 + record_depth(nested, records));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    max_depth
}

fn default_field_annotation(type_expr: &TypeExpr) -> String {
    match type_expr {
        TypeExpr::Vector(element) => format!("vector<{}>", element.display_name()),
        TypeExpr::Named(named) => named.name().to_string(),
        TypeExpr::Scalar(name) => name.clone(),
    }
}

pub struct LayoutBuilder<'a> {
    table: &'a TableResource,
    schema_hash: String,
    records: &'a HashMap<String, RecordResource>,
    columns: Vec<Column>,
    max_depth: u32,
}

impl<'a> LayoutBuilder<'a> {
    pub fn new(
        table: &'a TableResource,
        schema_hash: &str,
        records: &'a HashMap<String, RecordResource>,
    ) -> Self {
        LayoutBuilder {
            table,
            schema_hash: schema_hash.to_string(),
            records,
            columns: Vec::new(),
            max_depth: 1,
        }
    }

    pub fn build(mut self) -> Layout {
        let mut col = 1u32;
        let owner = self.table.resource_id();
        for field in &self.table.fields {
            col = self.emit(field, &format!("{owner}/{}", field.name), col, 1, None, "");
        }
        let columns = self.columns;
        let nodes = derive_header_nodes(&owner, &columns);
        Layout {
            table_id: owner,
            schema_hash: self.schema_hash,
            header_rows: self.max_depth * 2,
            columns,
            nodes,
        }
    }

    fn emit(
        &mut self,
        field: &FieldDef,
        path: &str,
        col: u32,
        depth: u32,
        group: Option<u32>,
        field_annotation: &str,
    ) -> u32 {
        let type_expr = field.type_expr.clone();
        self.max_depth = self.max_depth.max(depth);
        let field_annotation = if field_annotation.is_empty() {
            default_field_annotation(&type_expr)
        } else {
            field_annotation.to_string()
        };

        match &type_expr {
            TypeExpr::Vector(element) => {
                self.emit_vector(field, element, &field_annotation, path, col, depth, group)
            }
            TypeExpr::Named(named) if named_kind(named, self.records) == NamedKind::Record => {
                self.emit_record(named, path, col, depth, group, &field_annotation)
            }
            _ => {
                // 叶的 annotation 是叶自身类型文本；传播注解只进 field_annotation
                let leaf_text = field.type_text();
                self.emit_leaf(
                    col,
                    path,
                    &leaf_text,
                    &leaf_text,
                    depth,
                    group,
                    &field.comment,
                    &field_annotation,
                    "",
                    field.ref_.clone(),
                    field.name == self.table.primary,
                )
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn emit_vector(
        &mut self,
        field: &FieldDef,
        element: &TypeExpr,
        annotation: &str,
        path: &str,
        col: u32,
        depth: u32,
        group: Option<u32>,
    ) -> u32 {
        let groups = field.excel_columns.unwrap_or(0);
        let array_annotation = if groups > 0 {
            format!("{annotation}[{groups}]")
        } else {
            annotation.to_string()
        };
        if let TypeExpr::Named(named) = element {
            if named_kind(named, self.records) == NamedKind::Record && groups > 0 {
                let records = self.records;
                let record = &records[named.name()];
                self.max_depth = self
                    .max_depth
                    .max(depth + 1 + record_depth(record, self.records));
                let mut col = col;
                for g in 1..=groups {
                    for sub_field in &record.fields.clone() {
                        col = self.emit(
                            sub_field,
                            &format!("{path}[{g}]/{}", sub_field.name),
                            col,
                            depth + 1,
                            Some(g),
                            &array_annotation,
                        );
                    }
                }
                return col;
            }
        }
        if groups > 0 {
            // 标量/Enum/string 向量的固定 Excel 展开；运行时仍是变长 vector
            let element_text = element.display_name();
            self.max_depth = self.max_depth.max(depth + 1);
            let mut col = col;
            for g in 1..=groups {
                col = self.emit_leaf(
                    col,
                    &format!("{path}[{g}]"),
                    &element_text,
                    annotation,
                    depth + 1,
                    Some(g),
                    &format!("数据项[{g}]"),
                    &array_annotation,
                    &field.comment,
                    field.ref_.clone(),
                    field.name == self.table.primary,
                );
            }
            return col;
        }
        let element_text = element.display_name();
        // 未分组 vector：叶注解是 vector<T>，但继承下来的字段注解要原样传下去
        //（Python _emit_vector 尾部分支同语义：record 成员的表头第二行是所属 record 名）
        self.emit_leaf(
            col,
            path,
            &element_text,
            &format!("vector<{}>", element.display_name()),
            depth,
            group,
            &field.comment,
            annotation,
            "",
            field.ref_.clone(),
            field.name == self.table.primary,
        )
    }

    fn emit_record(
        &mut self,
        named: &ct_domain::types::NamedRef,
        path: &str,
        col: u32,
        depth: u32,
        group: Option<u32>,
        field_annotation: &str,
    ) -> u32 {
        let records = self.records;
        let record = &records[named.name()];
        self.max_depth = self
            .max_depth
            .max(depth + record_depth(record, self.records));
        let mut col = col;
        let annotation = if field_annotation.is_empty() {
            named.name()
        } else {
            field_annotation
        };
        for sub_field in &record.fields.clone() {
            col = self.emit(
                sub_field,
                &format!("{path}/{}", sub_field.name),
                col,
                depth,
                group,
                annotation,
            );
        }
        col
    }

    #[allow(clippy::too_many_arguments)]
    fn emit_leaf(
        &mut self,
        col: u32,
        path: &str,
        type_text: &str,
        annotation: &str,
        depth: u32,
        group: Option<u32>,
        comment: &str,
        field_annotation: &str,
        field_comment: &str,
        ref_: Option<String>,
        primary: bool,
    ) -> u32 {
        self.columns.push(Column {
            index: col,
            stable_path: path.to_string(),
            type_text: type_text.to_string(),
            annotation: annotation.to_string(),
            leaf: path.rsplit('/').next().unwrap_or(path).to_string(),
            group_index: group,
            depth,
            comment: comment.to_string(),
            field_comment: field_comment.to_string(),
            field_annotation: field_annotation.to_string(),
            ref_,
            primary,
        });
        col + 1
    }
}

/// 构建布局。
pub fn build_layout(
    table: &TableResource,
    schema_hash: &str,
    records: &HashMap<String, RecordResource>,
) -> Layout {
    LayoutBuilder::new(table, schema_hash, records).build()
}

fn path_parts(table_id: &str, path: &str) -> Vec<String> {
    let tail = &path[table_id.len() + 1..];
    let mut parts = Vec::new();
    for chunk in tail.split('/') {
        if let Some(open) = chunk.find('[') {
            let name = &chunk[..open];
            let group = chunk[open + 1..].split(']').next().unwrap_or("");
            parts.push(name.to_string());
            parts.push(group.to_string());
        } else {
            parts.push(chunk.to_string());
        }
    }
    parts
}

/// 从规范叶路径推导确定性表头结构节点。
pub fn derive_header_nodes(table_id: &str, columns: &[Column]) -> Vec<HeaderNode> {
    let mut buckets: Vec<(Vec<String>, Vec<&Column>)> = Vec::new();
    for column in columns {
        let parts = path_parts(table_id, &column.stable_path);
        for depth in 1..=parts.len() {
            let prefix: Vec<String> = parts[..depth].to_vec();
            if let Some((_, cols)) = buckets.iter_mut().find(|(p, _)| *p == prefix) {
                cols.push(column);
            } else {
                buckets.push((prefix, vec![column]));
            }
        }
    }
    buckets.sort_by_key(|(parts, cols)| (cols[0].index, parts.len()));

    let mut out = Vec::new();
    for (parts, cols) in &buckets {
        let segment = parts.last().unwrap().clone();
        let is_digit = segment.chars().all(|c| c.is_ascii_digit());
        let display_segment = if is_digit {
            format!("#{segment}")
        } else {
            segment.clone()
        };
        let leaf = parts.len() == path_parts(table_id, &cols[0].stable_path).len();
        let kind = if is_digit {
            "slot"
        } else if leaf {
            "field"
        } else if buckets.iter().any(|(p, _)| {
            p.len() > parts.len()
                && p[..parts.len()] == parts[..]
                && p[parts.len()].chars().all(|c| c.is_ascii_digit())
        }) {
            "array"
        } else {
            "record"
        };
        let mut path = format!("{table_id}/{}", parts[0]);
        for part in &parts[1..] {
            if part.chars().all(|c| c.is_ascii_digit()) {
                path.push_str(&format!("[{part}]"));
            } else {
                path.push_str(&format!("/{part}"));
            }
        }
        let child_keys: Vec<String> = buckets
            .iter()
            .filter(|(p, _)| p.len() == parts.len() + 1 && p[..parts.len()] == parts[..])
            .map(|(p, _)| p.join("/"))
            .collect();
        out.push(HeaderNode {
            stable_path: path,
            display_name: display_segment,
            annotation: if cols[0].field_annotation.is_empty() {
                cols[0].annotation.clone()
            } else {
                cols[0].field_annotation.clone()
            },
            comment: cols[0].comment.clone(),
            kind: kind.to_string(),
            depth: parts.len() as u32,
            children: child_keys,
            slot_index: if is_digit { segment.parse().ok() } else { None },
            leaf_start: cols.iter().map(|c| c.index).min().unwrap(),
            leaf_end: cols.iter().map(|c| c.index).max().unwrap(),
        });
    }
    out
}
