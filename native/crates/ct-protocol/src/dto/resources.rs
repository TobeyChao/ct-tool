//! resources.list DTO。

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceKind {
    Table,
    Record,
    Enum,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourceEntry {
    pub name: String,
    pub kind: ResourceKind,
    /// YAML 来源路径（相对 workspace 根；文件名可与资源名不同）。
    pub source_path: String,
    /// 仅 Table：认领的 Excel 路径。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excel_file: Option<String>,
    /// 仅 Table：已声明的查询索引 kind（词汇与 `set_indexes` 一致，当前只有 codename）。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub indexes: Vec<String>,
    /// 仅 Table：JSON 输出键。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub json_key: Option<String>,
    /// schema 文档里的字段定义（table/record）：与 YAML 持久化形态同词表。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fields: Option<Vec<serde_json::Value>>,
    /// schema 文档里的枚举成员（enum）：列表顺序即 ordinal。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub values: Option<Vec<serde_json::Value>>,
    /// 表主键名：界面用它标出主键行，不自己猜第一个字段。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub primary: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourcesListResult {
    pub revision: u64,
    pub resources: Vec<ResourceEntry>,
    /// schema 基线摘要（sha256）：编辑草稿的 `schema.candidate` 与保存守卫都以它为准；
    /// 打不开 schema 目录时为空串。
    #[serde(default)]
    pub schema_revision: String,
}
