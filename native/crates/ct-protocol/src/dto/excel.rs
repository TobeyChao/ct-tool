//! table.preview 与 template.plan/generate DTO。

use serde::{Deserialize, Serialize};

use crate::event::Issue;
use crate::pagination::PageRequest;

/// `table.preview` 参数。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TablePreviewParams {
    pub table: String,
    #[serde(default)]
    pub page: PageRequest,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewColumn {
    pub name: String,
    /// 类型表达式原文（如 `vector<Record.Item,4>`）。
    pub type_expr: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
    /// 字段属性：编辑器回显用，缺省即 false/未声明，不写入线格式。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub i18n: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_only: Option<bool>,
    /// `comment` 原文（空串省略）。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub comment: Option<String>,
    /// 声明的 ref 目标（未声明省略）。
    #[serde(default, rename = "ref", skip_serializing_if = "Option::is_none")]
    pub ref_: Option<String>,
    /// vector 展开组数（仅声明时给出）。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excel_columns: Option<u32>,
}

/// `table.preview` 结果。单元格中的超范围整数按 bigint 规则编码。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TablePreviewResult {
    pub revision: u64,
    pub columns: Vec<PreviewColumn>,
    /// 行数组与列对齐；空单元格为 null。
    pub rows: Vec<Vec<serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

/// `template.plan` 参数/结果：迁移预检，不写文件。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemplatePlanParams {
    pub table: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemplatePlanResult {
    pub can_generate: bool,
    /// 将执行的动作描述（重建表头、按稳定列路径迁移数据等）。
    #[serde(default)]
    pub actions: Vec<String>,
    /// 非阻塞告警（如 Enum 下拉超 255 字符降级）。
    #[serde(default)]
    pub warnings: Vec<Issue>,
    /// 阻塞问题（缺 manifest、不可迁移数据等）。
    #[serde(default)]
    pub problems: Vec<Issue>,
}

/// `template.generate` 参数/结果：显式触发，失败不覆盖原工作簿。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemplateGenerateParams {
    pub table: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TemplateGenerateResult {
    pub migrated_rows: u32,
    #[serde(default)]
    pub warnings: Vec<Issue>,
}
