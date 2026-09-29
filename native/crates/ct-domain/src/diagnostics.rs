//! 诊断契约（`ct/diagnostics/errors.py`）：问题码与行级定位。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IssueCode {
    Type,
    Ref,
    DuplicatePk,
    DuplicateCodename,
    Schema,
    Template,
    Workspace,
}

impl IssueCode {
    pub fn as_str(&self) -> &'static str {
        match self {
            IssueCode::Type => "type",
            IssueCode::Ref => "ref",
            IssueCode::DuplicatePk => "duplicate_pk",
            IssueCode::DuplicateCodename => "duplicate_codename",
            IssueCode::Schema => "schema",
            IssueCode::Template => "template",
            IssueCode::Workspace => "workspace",
        }
    }
}

/// 行级校验问题（携带 Excel 定位信息）。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ValidationIssue {
    pub table: String,
    pub code: IssueCode,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub row_index: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excel_row: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>,
    #[serde(default)]
    pub field: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub value: Option<serde_json::Value>,
}

/// 列号 → Excel 列字母（1-based）。
pub fn column_letter(index: u32) -> String {
    let mut n = index;
    let mut out = String::new();
    while n > 0 {
        n -= 1;
        out.insert(0, (b'A' + (n % 26) as u8) as char);
        n /= 26;
    }
    out
}

impl ValidationIssue {
    pub fn new(table: &str, code: IssueCode, message: impl Into<String>) -> Self {
        ValidationIssue {
            table: table.to_string(),
            code,
            message: message.into(),
            row_index: None,
            excel_row: None,
            column: None,
            field: String::new(),
            value: None,
        }
    }

    /// 与 Python `render()` 相同的展示文本。
    pub fn render(&self) -> String {
        if let (Some(row), Some(col)) = (self.excel_row, self.column) {
            let letter = column_letter(col + 1);
            let value = self
                .value
                .as_ref()
                .map(|v| v.to_string())
                .unwrap_or_else(|| "null".into());
            return format!(
                "[{}.xlsx] Excel 第{}行 · 列{} ({}) · 当前值 {} → {}",
                self.table, row, letter, self.field, value, self.message
            );
        }
        match self.row_index {
            None => format!("[{}.xlsx] {}", self.table, self.message),
            Some(row) => format!(
                "[{}.xlsx] 第{}行 {}：{}",
                self.table, row, self.field, self.message
            ),
        }
    }
}
