//! 规范行读取（`ct/excel/canonical_reader.py`）：
//! 按布局把 Excel 行重建为规范嵌套 dict，含类型/值域闸门与 vector 文法。

use std::collections::{BTreeMap, HashMap};

use ct_domain::diagnostics::{IssueCode, ValidationIssue};
use ct_domain::schema::{EnumResource, RecordResource, TableResource};
use ct_domain::types::{integer_scalar_range, scalar_default_json, NamedKind, TypeExpr};

use crate::layout::{Column, Layout};
use crate::reader::ProbeValue;

const BOOL_TRUE: &[&str] = &["true", "1", "yes", "TRUE", "True", "YES", "Yes", "✓"];
const BOOL_FALSE: &[&str] = &["false", "0", "no", "FALSE", "False", "NO", "No", "✗"];

/// Python `str()` 等价的数字文本（bool 走 True/False）。
pub fn raw_number_text(n: f64) -> String {
    if n.fract() == 0.0 && n.abs() < 1e16 {
        format!("{}", n as i64)
    } else {
        format!("{n}")
    }
}

/// 单元格原始值（读取层统一形态）。
#[derive(Debug, Clone, PartialEq)]
pub enum RawValue {
    Empty,
    Text(String),
    Number(f64),
    Bool(bool),
}

impl From<&ProbeValue> for RawValue {
    fn from(value: &ProbeValue) -> Self {
        match value {
            ProbeValue::Text(s) => RawValue::Text(s.clone()),
            ProbeValue::Number(n) => RawValue::Number(*n),
            ProbeValue::Bool(b) => RawValue::Bool(*b),
            ProbeValue::DateTime(s) | ProbeValue::Error(s) => RawValue::Text(s.clone()),
        }
    }
}

impl RawValue {
    fn is_blank(&self) -> bool {
        matches!(self, RawValue::Empty) || matches!(self, RawValue::Text(s) if s.trim().is_empty())
    }

    fn to_json(&self) -> serde_json::Value {
        match self {
            RawValue::Empty => serde_json::Value::Null,
            RawValue::Text(s) => serde_json::Value::String(s.clone()),
            RawValue::Number(n) => serde_json::json!(n),
            RawValue::Bool(b) => serde_json::json!(b),
        }
    }

    /// Python `str(raw)` 口径。
    fn as_text(&self) -> String {
        match self {
            RawValue::Empty => String::new(),
            RawValue::Text(s) => s.clone(),
            RawValue::Number(n) => raw_number_text(*n),
            RawValue::Bool(b) => if *b { "True" } else { "False" }.to_string(),
        }
    }
}

/// `_coerce_scalar`：返回 (值, 是否合法)。空值在标量下透传（调用方补默认）。
fn coerce_scalar(type_text: &str, raw: &RawValue) -> (serde_json::Value, bool) {
    if matches!(raw, RawValue::Empty) {
        return if type_text == "string" {
            (serde_json::Value::String(String::new()), true)
        } else {
            (serde_json::Value::Null, true)
        };
    }
    if let Some((low, high)) = integer_scalar_range(type_text) {
        let value: Option<i128> = match raw {
            RawValue::Number(n) => {
                if !n.is_finite() {
                    None
                } else {
                    Some(n.trunc() as i128)
                }
            }
            RawValue::Bool(b) => Some(*b as i128),
            RawValue::Text(s) => s.trim().parse::<i128>().ok(),
            RawValue::Empty => None,
        };
        return match value {
            Some(v) if (low..=high).contains(&v) => {
                if v >= 0 && (v > i64::MAX as i128 || type_text.starts_with('u')) {
                    (serde_json::Value::from(v as u64), true)
                } else {
                    (serde_json::Value::from(v as i64), true)
                }
            }
            _ => (raw.to_json(), false),
        };
    }
    match type_text {
        "float" | "double" => {
            let value: Option<f64> = match raw {
                RawValue::Number(n) => Some(*n),
                RawValue::Bool(b) => Some(*b as u8 as f64),
                RawValue::Text(s) => s.parse::<f64>().ok(),
                RawValue::Empty => None,
            };
            match value {
                Some(v) => (serde_json::json!(v), true),
                None => (raw.to_json(), false),
            }
        }
        "bool" => match raw {
            RawValue::Bool(b) => (serde_json::json!(b), true),
            other => {
                let text = other.as_text();
                let trimmed = text.trim();
                if BOOL_TRUE.contains(&trimmed) {
                    (serde_json::json!(true), true)
                } else if BOOL_FALSE.contains(&trimmed) {
                    (serde_json::json!(false), true)
                } else {
                    (other.to_json(), false)
                }
            }
        },
        // enum / 具名叶：字符串标识
        _ => (serde_json::Value::String(raw.as_text()), true),
    }
}

/// `parse_vector_cell`：规范 `[...]` 文法，返回 (值, 诊断)。
pub fn parse_vector_cell(
    text: &str,
    element_text: &str,
) -> (Vec<serde_json::Value>, Option<String>) {
    let source = text.trim();
    if source.is_empty() || source == "[]" || source == "[ ]" {
        return (vec![], None);
    }
    let chars: Vec<char> = source.chars().collect();
    if !(chars.first() == Some(&'[') && chars.last() == Some(&']')) {
        return (vec![], Some("变长 vector 必须使用 [...] 格式".to_string()));
    }
    let body = &chars[1..chars.len() - 1];
    let mut tokens: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < body.len() {
        while i < body.len() && body[i].is_whitespace() {
            i += 1;
        }
        if i >= body.len() {
            break;
        }
        let start = i;
        if body[i] == '"' {
            i += 1;
            let mut closed = false;
            let mut escaped = false;
            while i < body.len() {
                let ch = body[i];
                i += 1;
                if escaped {
                    escaped = false;
                } else if ch == '\\' {
                    escaped = true;
                } else if ch == '"' {
                    closed = true;
                    break;
                }
            }
            if !closed {
                return (
                    vec![],
                    Some(format!("字符串从位置 {} 开始未闭合", start + 2)),
                );
            }
            let token: String = body[start..i].iter().collect();
            if serde_json::from_str::<serde_json::Value>(&token).is_err() {
                return (vec![], Some(format!("位置 {} 的字符串转义无效", start + 2)));
            }
            tokens.push(token);
        } else {
            while i < body.len() && body[i] != ',' {
                i += 1;
            }
            let token: String = body[start..i].iter().collect::<String>().trim().to_string();
            if token.is_empty() {
                return (
                    vec![],
                    Some(format!("位置 {} 存在空元素或尾逗号", start + 2)),
                );
            }
            tokens.push(token);
        }
        while i < body.len() && body[i].is_whitespace() {
            i += 1;
        }
        if i < body.len() {
            if body[i] != ',' {
                return (vec![], Some(format!("位置 {} 缺少逗号", i + 2)));
            }
            i += 1;
            if i >= body.len() || body[i..].iter().all(|c| c.is_whitespace()) {
                return (vec![], Some(format!("位置 {} 存在尾逗号", i + 2)));
            }
        }
    }

    let mut values = Vec::new();
    for (index, token) in tokens.iter().enumerate() {
        let index = index + 1;
        match element_text {
            "string" => {
                if !(token.starts_with('"') && token.ends_with('"')) {
                    return (
                        vec![],
                        Some(format!("第{index}个元素 string 必须使用 JSON 双引号")),
                    );
                }
                match serde_json::from_str::<String>(token) {
                    Ok(v) => values.push(serde_json::Value::String(v)),
                    Err(_) => return (vec![], Some(format!("位置 {index} 的字符串转义无效"))),
                }
            }
            "bool" => match token.as_str() {
                "true" => values.push(serde_json::json!(true)),
                "false" => values.push(serde_json::json!(false)),
                _ => {
                    return (
                        vec![],
                        Some(format!("第{index}个元素 bool 必须是 true 或 false")),
                    )
                }
            },
            name if integer_scalar_range(name).is_some() => {
                let (low, high) = integer_scalar_range(name).unwrap();
                if !token
                    .chars()
                    .enumerate()
                    .all(|(i, c)| c.is_ascii_digit() || (i == 0 && (c == '+' || c == '-')))
                {
                    return (vec![], Some(format!("第{index}个元素期望 {name} 类型")));
                }
                let Ok(value) = token.parse::<i128>() else {
                    return (vec![], Some(format!("第{index}个元素期望 {name} 类型")));
                };
                if !(low..=high).contains(&value) {
                    return (
                        vec![],
                        Some(format!("第{index}个元素 {token} 超出 {name} 值域")),
                    );
                }
                if value >= 0 && value > i64::MAX as i128 {
                    values.push(serde_json::Value::from(value as u64));
                } else {
                    values.push(serde_json::Value::from(value as i64));
                }
            }
            "float" | "double" => {
                let Ok(value) = token.parse::<f64>() else {
                    return (
                        vec![],
                        Some(format!("第{index}个元素期望 {element_text} 类型")),
                    );
                };
                values.push(serde_json::json!(value));
            }
            _ => {
                // Enum 标识符
                let valid = !token.is_empty()
                    && token
                        .chars()
                        .next()
                        .is_some_and(|c| c.is_alphabetic() || c == '_')
                    && token.chars().all(|c| c.is_alphanumeric() || c == '_');
                if !valid {
                    return (vec![], Some(format!("第{index}个元素 Enum 标识符无效")));
                }
                values.push(serde_json::Value::String(token.clone()));
            }
        }
    }
    (values, None)
}

/// 解析结果。
pub struct CanonicalParsedRows {
    pub rows: Vec<serde_json::Map<String, serde_json::Value>>,
    pub excel_rows: Vec<u32>,
    pub issues: Vec<ValidationIssue>,
}

struct RowReader<'a> {
    layout: &'a Layout,
    table: &'a TableResource,
    records: &'a HashMap<String, RecordResource>,
    enums: &'a HashMap<String, EnumResource>,
    excel_row: u32,
    row_index: u32,
    issues: Vec<ValidationIssue>,
    value_by_path: HashMap<String, RawValue>,
}

impl RowReader<'_> {
    fn is_record(&self, named: &ct_domain::types::NamedRef) -> bool {
        self.records.contains_key(named.name())
    }

    fn column(&self, path: &str) -> Option<&Column> {
        self.layout.columns.iter().find(|c| c.stable_path == path)
    }

    fn coerce(&mut self, column: &Column, raw: &RawValue) -> serde_json::Value {
        let (value, ok) = coerce_scalar(&column.type_text, raw);
        if !ok {
            self.issues.push(ValidationIssue {
                table: self.table.table.clone(),
                code: IssueCode::Type,
                message: format!("期望 {} 类型", column.type_text),
                row_index: Some(self.row_index),
                excel_row: Some(self.excel_row),
                column: Some(column.index - 1),
                field: column.stable_path.clone(),
                value: Some(raw.to_json()),
            });
        }
        value
    }

    fn default_for(&mut self, expr: &TypeExpr) -> serde_json::Value {
        match expr {
            TypeExpr::Scalar(name) => scalar_default_json(name),
            TypeExpr::Vector(_) => serde_json::json!([]),
            TypeExpr::Named(named) => match named.expected_kind() {
                Some(NamedKind::Enum) => {
                    let first = self
                        .enums
                        .get(named.name())
                        .and_then(|e| e.values.first())
                        .map(|v| v.name.clone())
                        .unwrap_or_default();
                    serde_json::Value::String(first)
                }
                _ => {
                    if let Some(record) = self.records.get(named.name()) {
                        self.read_record_defaults(record)
                    } else {
                        serde_json::json!({})
                    }
                }
            },
        }
    }

    fn read_record_defaults(&mut self, record: &RecordResource) -> serde_json::Value {
        let mut result = serde_json::Map::new();
        let fields = record.fields.clone();
        for field in &fields {
            let v = self.default_for(&field.type_expr);
            result.insert(field.name.clone(), v);
        }
        serde_json::Value::Object(result)
    }

    fn read_record_group(
        &mut self,
        record_name: &str,
        top: &str,
        group: Option<u32>,
    ) -> Option<serde_json::Value> {
        let columns: Vec<&Column> = self
            .layout
            .columns
            .iter()
            .filter(|c| {
                c.stable_path.starts_with(top) && (group.is_none() || c.group_index == group)
            })
            .collect();
        if columns.is_empty() {
            return None;
        }
        if columns.iter().all(|c| {
            self.value_by_path
                .get(&c.stable_path)
                .is_none_or(RawValue::is_blank)
        }) {
            return None; // 全空组
        }
        let record = self.records.get(record_name)?.clone();
        let group_top = match group {
            Some(g) => format!("{top}[{g}]"),
            None => top.to_string(),
        };
        Some(self.read_record_fields(&record, &group_top, group))
    }

    fn read_record_fields(
        &mut self,
        record: &RecordResource,
        top: &str,
        _group: Option<u32>,
    ) -> serde_json::Value {
        let mut result = serde_json::Map::new();
        let fields = record.fields.clone();
        for field in &fields {
            let path = format!("{top}/{}", field.name);
            match &field.type_expr {
                TypeExpr::Named(named) if self.is_record(named) => {
                    let nested = self.records.get(named.name()).cloned();
                    if let Some(nested) = nested {
                        let v = self.read_record_fields(&nested, &path, _group);
                        result.insert(field.name.clone(), v);
                    }
                }
                TypeExpr::Vector(_) => {
                    // 记录内 vector：单格 [...] 文法
                    let column = self.column(&path).cloned();
                    let raw = self
                        .value_by_path
                        .get(&path)
                        .cloned()
                        .unwrap_or(RawValue::Empty);
                    if let Some(column) = column {
                        let v = self.split_vector(&field.type_expr, &column, &raw);
                        result.insert(field.name.clone(), v);
                    } else {
                        result.insert(field.name.clone(), serde_json::json!([]));
                    }
                }
                _ => {
                    let column = self.column(&path).cloned();
                    match column {
                        Some(column) => {
                            let raw = self
                                .value_by_path
                                .get(&column.stable_path)
                                .cloned()
                                .unwrap_or(RawValue::Empty);
                            let v = if raw.is_blank() {
                                self.default_for(&field.type_expr)
                            } else {
                                self.coerce(&column, &raw)
                            };
                            result.insert(field.name.clone(), v);
                        }
                        None => {
                            let v = self.default_for(&field.type_expr);
                            result.insert(field.name.clone(), v);
                        }
                    }
                }
            }
        }
        serde_json::Value::Object(result)
    }

    fn split_vector(
        &mut self,
        vector: &TypeExpr,
        column: &Column,
        raw: &RawValue,
    ) -> serde_json::Value {
        if raw.is_blank() {
            return serde_json::json!([]);
        }
        let TypeExpr::Vector(element) = vector else {
            return serde_json::json!([]);
        };
        let (values, error) = parse_vector_cell(&raw.as_text(), &element.display_name());
        if let Some(message) = error {
            self.issues.push(ValidationIssue {
                table: self.table.table.clone(),
                code: IssueCode::Type,
                message,
                row_index: Some(self.row_index),
                excel_row: Some(self.excel_row),
                column: Some(column.index - 1),
                field: column.stable_path.clone(),
                value: Some(raw.to_json()),
            });
        }
        serde_json::Value::Array(values)
    }

    fn read_field(&mut self, field: &ct_domain::schema::FieldDef) -> Option<serde_json::Value> {
        let owner = self.table.resource_id();
        let top = format!("{owner}/{}", field.name);

        // vector<Record> 定长展开组
        if let TypeExpr::Vector(element) = &field.type_expr {
            if let TypeExpr::Named(named) = element.as_ref() {
                if self.is_record(named) && field.excel_columns.unwrap_or(0) > 0 {
                    let group_count = field.excel_columns.unwrap_or(0);
                    let mut last_filled = 0;
                    for g in 1..=group_count {
                        if self
                            .read_record_group(named.name(), &top, Some(g))
                            .is_some()
                        {
                            last_filled = g;
                        }
                    }
                    let mut groups = Vec::new();
                    for g in 1..=last_filled {
                        let value = self
                            .read_record_group(named.name(), &top, Some(g))
                            .unwrap_or_else(|| self.default_for(element));
                        groups.push(value);
                    }
                    return Some(serde_json::Value::Array(groups));
                }
            }
        }

        // 标量/枚举定长展开组
        if let TypeExpr::Vector(element) = &field.type_expr {
            if field.excel_columns.unwrap_or(0) > 0 {
                let mut last_filled = 0;
                for g in 1..=field.excel_columns.unwrap_or(0) {
                    let path = format!("{top}[{g}]");
                    let raw = self
                        .value_by_path
                        .get(&path)
                        .cloned()
                        .unwrap_or(RawValue::Empty);
                    if !raw.is_blank() {
                        last_filled = g;
                    }
                }
                let mut values = Vec::new();
                for g in 1..=last_filled {
                    let path = format!("{top}[{g}]");
                    let raw = self
                        .value_by_path
                        .get(&path)
                        .cloned()
                        .unwrap_or(RawValue::Empty);
                    let value = if raw.is_blank() {
                        self.default_for(element)
                    } else if let Some(column) = self.column(&path).cloned() {
                        self.coerce(&column, &raw)
                    } else {
                        self.default_for(element)
                    };
                    values.push(value);
                }
                return Some(serde_json::Value::Array(values));
            }
            // 单格 [...] 文法
            let column = self.column(&top)?.clone();
            let raw = self
                .value_by_path
                .get(&top)
                .cloned()
                .unwrap_or(RawValue::Empty);
            return Some(self.split_vector(&field.type_expr, &column, &raw));
        }

        if let TypeExpr::Named(named) = &field.type_expr {
            if self.is_record(named) {
                let record = self.records.get(named.name())?.clone();
                return Some(self.read_record_fields(&record, &top, None));
            }
        }

        let column = self.column(&top)?.clone();
        let raw = self
            .value_by_path
            .get(&top)
            .cloned()
            .unwrap_or(RawValue::Empty);
        Some(self.coerce(&column, &raw))
    }

    fn read(&mut self, cells: &[RawValue]) -> Option<serde_json::Map<String, serde_json::Value>> {
        if cells.iter().all(|c| c.is_blank()) {
            return None;
        }
        for column in &self.layout.columns {
            let raw = cells
                .get((column.index - 1) as usize)
                .cloned()
                .unwrap_or(RawValue::Empty);
            self.value_by_path.insert(column.stable_path.clone(), raw);
        }
        let mut result = serde_json::Map::new();
        let fields = self.table.fields.clone();
        for field in &fields {
            if let Some(value) = self.read_field(field) {
                // 空标量（None）不进入结果（Python: `if field_value is not None`）
                if !value.is_null() {
                    result.insert(field.name.clone(), value);
                }
            }
        }
        Some(result)
    }
}

/// 把探针报告按行聚合为 (excel_row, 单元格向量)（缺失列为 Empty）。
pub fn rows_from_probe(report: &crate::reader::ProbeReport) -> BTreeMap<u32, Vec<RawValue>> {
    let mut rows: BTreeMap<u32, Vec<RawValue>> = BTreeMap::new();
    for cell in &report.cells {
        let raw = RawValue::from(&cell.value);
        let row = rows.entry(cell.row).or_default();
        let idx = (cell.col - 1) as usize;
        if row.len() <= idx {
            row.resize(idx + 1, RawValue::Empty);
        }
        row[idx] = raw;
    }
    rows
}

/// 读取规范行：`rows` 是 (excel_row, 单元格向量)（1-based 列）。
pub fn read_canonical_rows(
    layout: &Layout,
    table: &TableResource,
    records: &HashMap<String, RecordResource>,
    enums: &HashMap<String, EnumResource>,
    rows: &BTreeMap<u32, Vec<RawValue>>,
) -> CanonicalParsedRows {
    let mut out_rows = Vec::new();
    let mut excel_rows = Vec::new();
    let mut issues = Vec::new();
    for (excel_row, cells) in rows {
        if *excel_row <= layout.header_rows {
            continue;
        }
        let mut reader = RowReader {
            layout,
            table,
            records,
            enums,
            excel_row: *excel_row,
            row_index: (out_rows.len() + 1) as u32,
            issues: Vec::new(),
            value_by_path: HashMap::new(),
        };
        if let Some(parsed) = reader.read(cells) {
            out_rows.push(parsed);
            excel_rows.push(*excel_row);
        }
        issues.append(&mut reader.issues);
    }
    CanonicalParsedRows {
        rows: out_rows,
        excel_rows,
        issues,
    }
}
