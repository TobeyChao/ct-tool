//! YAML 资源模型：Table/Record/Enum（`ct/schema/resources.py`）。
//!
//! 校验规则与 Python 一致：命名、主键 int32、excel_columns/ref/i18n/
//! server_only 约束、索引声明、uniform 声明式布局。

use serde::{Deserialize, Serialize};

use crate::naming::validate_name;
use crate::types::{NamedRef, TypeExpr, PRIMARY_KEY_TYPE};

/// CodeName 索引固定指向的字段名（`QueryIndex.kind == "codename"`）。
pub const CODENAME_FIELD: &str = "CodeName";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SchemaError(pub String);

impl std::fmt::Display for SchemaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for SchemaError {}

fn require_resource_name(name: &str, label: &str) -> Result<(), SchemaError> {
    match validate_name(name) {
        Some(error) => Err(SchemaError(format!("{label} {name}: {error}"))),
        None => Ok(()),
    }
}

fn validate_fields(fields: &[FieldDef], owner: &str) -> Result<(), SchemaError> {
    if fields.is_empty() {
        return Err(SchemaError(format!("{owner}: fields 不能为空")));
    }
    let mut seen = std::collections::HashSet::new();
    for field in fields {
        if !seen.insert(field.name.as_str()) {
            return Err(SchemaError(format!(
                "{owner}: 字段名 '{}' 重复",
                field.name
            )));
        }
    }
    Ok(())
}

/// 字段定义。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FieldDef {
    pub name: String,
    #[serde(rename = "type")]
    pub type_expr: TypeExpr,
    #[serde(default)]
    pub i18n: bool,
    #[serde(default, rename = "ref")]
    pub ref_: Option<String>,
    #[serde(default)]
    pub server_only: bool,
    #[serde(default)]
    pub comment: String,
    #[serde(default)]
    pub excel_columns: Option<u32>,
}

impl FieldDef {
    pub fn validate(&self) -> Result<(), SchemaError> {
        require_resource_name(&self.name, "字段")?;
        if self.i18n && self.server_only {
            return Err(SchemaError(format!(
                "字段 {} 不能同时标记 i18n 和 server_only",
                self.name
            )));
        }
        if self.i18n && !matches!(&self.type_expr, TypeExpr::Scalar(s) if s == "string") {
            return Err(SchemaError(format!(
                "字段 {}: 只有 string 类型可以标记 i18n",
                self.name
            )));
        }
        if self.excel_columns.is_some() && !matches!(self.type_expr, TypeExpr::Vector(_)) {
            return Err(SchemaError(format!(
                "字段 {}: excel_columns（展开组数）仅适用于 vector<T>（定长展开列），当前类型 {}",
                self.name,
                self.type_text()
            )));
        }
        if let Some(0) = self.excel_columns {
            return Err(SchemaError(format!(
                "字段 {}: excel_columns 必须 >= 1",
                self.name
            )));
        }
        Ok(())
    }

    pub fn type_text(&self) -> String {
        self.type_expr.to_text()
    }
}

/// 表级查询索引（当前仅 codename，固定指向 CodeName 字段）。
/// 线格式两种都收：`- codename`（夹具简写）与 `- kind: codename`（YAML）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QueryIndex;

impl serde::Serialize for QueryIndex {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str("codename")
    }
}

impl<'de> serde::Deserialize<'de> for QueryIndex {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = serde_json::Value::deserialize(deserializer)?;
        let kind = match &value {
            serde_json::Value::String(s) => s.clone(),
            serde_json::Value::Object(map) => map
                .get("kind")
                .and_then(|k| k.as_str())
                .unwrap_or("")
                .to_string(),
            _ => String::new(),
        };
        match kind.as_str() {
            "codename" => Ok(QueryIndex),
            other => Err(serde::de::Error::custom(format!(
                "未知索引 kind: {other}（当前仅支持 codename）"
            ))),
        }
    }
}

/// 表资源。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TableResource {
    #[serde(alias = "name")]
    pub table: String,
    #[serde(default)]
    pub primary: String,
    pub fields: Vec<FieldDef>,
    #[serde(default)]
    pub json_key: Option<String>,
    #[serde(default)]
    pub excel_file: Option<String>,
    #[serde(default)]
    pub indexes: Vec<QueryIndex>,
    /// 行内布局：true（缺省）= 定宽；false = 变长。声明式，不由填充率判定。
    #[serde(default = "default_uniform")]
    pub uniform: bool,
}

fn default_uniform() -> bool {
    true
}

impl TableResource {
    pub fn validate(&self) -> Result<(), SchemaError> {
        require_resource_name(&self.table, "表")?;
        validate_fields(&self.fields, &format!("表 {}", self.table))?;
        for field in &self.fields {
            field.validate()?;
        }
        let Some(primary) = self.fields.iter().find(|f| f.name == self.primary) else {
            return Err(SchemaError(format!(
                "表 {}: 主键 '{}' 不在字段列表中",
                self.table, self.primary
            )));
        };
        if !matches!(&primary.type_expr, TypeExpr::Scalar(s) if s == PRIMARY_KEY_TYPE) {
            return Err(SchemaError(format!(
                "表 {}: 主键字段 '{}' 类型必须为 {}（当前: {}）\
                 ——主键在索引向量、idHash 与生成的 ByID(int) 上均以 32 位承载",
                self.table,
                self.primary,
                PRIMARY_KEY_TYPE,
                primary.type_text()
            )));
        }
        if primary.server_only {
            return Err(SchemaError(format!(
                "表 {}: 主键字段 '{}' 不能标记 server_only\
                 （主键是客户端与次语言 bundle 的主键，server_only 字段不进入客户端 Binary）",
                self.table, self.primary
            )));
        }
        Ok(())
    }

    pub fn name(&self) -> &str {
        &self.table
    }

    pub fn resource_id(&self) -> String {
        format!("table:{}", self.table)
    }

    pub fn client_fields(&self) -> impl Iterator<Item = &FieldDef> {
        self.fields.iter().filter(|f| !f.server_only)
    }

    pub fn primary_key(&self) -> Option<&str> {
        if self.primary.is_empty() {
            None
        } else {
            Some(&self.primary)
        }
    }

    pub fn has_codename_index(&self) -> bool {
        !self.indexes.is_empty()
    }

    pub fn i18n_fields(&self) -> impl Iterator<Item = &FieldDef> {
        self.fields.iter().filter(|f| f.i18n)
    }

    pub fn resolved_json_key(&self) -> String {
        self.json_key
            .clone()
            .unwrap_or_else(|| format!("{}s", self.table))
    }

    pub fn resolved_excel_file(&self) -> String {
        self.excel_file
            .clone()
            .unwrap_or_else(|| format!("{}.xlsx", self.table))
    }
}

/// Record 资源。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordResource {
    #[serde(default = "default_record_kind")]
    pub kind: String,
    pub name: String,
    pub fields: Vec<FieldDef>,
    #[serde(default)]
    pub comment: String,
}

fn default_record_kind() -> String {
    "record".to_string()
}

impl RecordResource {
    pub fn validate(&self) -> Result<(), SchemaError> {
        require_resource_name(&self.name, "Record")?;
        validate_fields(&self.fields, &format!("Record {}", self.name))?;
        for field in &self.fields {
            field.validate()?;
            if field.i18n {
                return Err(SchemaError(format!(
                    "record:{}/{}: 首版 i18n 仅允许 Table 顶层 string 字段",
                    self.name, field.name
                )));
            }
            if field.server_only {
                return Err(SchemaError(format!(
                    "record:{}/{}: 首版 server_only 仅允许 Table 顶层字段",
                    self.name, field.name
                )));
            }
        }
        Ok(())
    }

    pub fn resource_id(&self) -> String {
        format!("record:{}", self.name)
    }
}

/// Enum 项：列表位置即 wire ordinal。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "EnumItemWire", into = "EnumItemWire")]
pub struct EnumItem {
    pub name: String,
    #[serde(default)]
    pub comment: String,
}

#[derive(Serialize, Deserialize)]
#[serde(untagged)]
enum EnumItemWire {
    Name(String),
    Full {
        name: String,
        #[serde(default)]
        comment: String,
    },
}

impl TryFrom<EnumItemWire> for EnumItem {
    type Error = String;
    fn try_from(wire: EnumItemWire) -> Result<Self, Self::Error> {
        let item = match wire {
            EnumItemWire::Name(name) => EnumItem {
                name,
                comment: String::new(),
            },
            EnumItemWire::Full { name, comment } => EnumItem { name, comment },
        };
        if item.name.is_empty() || !is_plain_identifier(&item.name) {
            return Err(format!("'{}' 不是合法标识符", item.name));
        }
        Ok(item)
    }
}

impl From<EnumItem> for EnumItemWire {
    fn from(item: EnumItem) -> Self {
        EnumItemWire::Full {
            name: item.name,
            comment: item.comment,
        }
    }
}

fn is_plain_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (unicode_ident::is_xid_start(first) || first == '_')
        && chars.all(|c| unicode_ident::is_xid_continue(c) || c == '_')
}

/// Enum 资源。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnumResource {
    #[serde(default = "default_enum_kind")]
    pub kind: String,
    pub name: String,
    pub values: Vec<EnumItem>,
    #[serde(default)]
    pub comment: String,
}

fn default_enum_kind() -> String {
    "enum".to_string()
}

impl EnumResource {
    pub fn validate(&self) -> Result<(), SchemaError> {
        require_resource_name(&self.name, "Enum")?;
        if self.values.is_empty() {
            return Err(SchemaError(format!("Enum {}: values 不能为空", self.name)));
        }
        let mut seen = std::collections::HashSet::new();
        for item in &self.values {
            if !seen.insert(item.name.as_str()) {
                return Err(SchemaError(format!(
                    "Enum {}: 值 '{}' 重复",
                    self.name, item.name
                )));
            }
        }
        Ok(())
    }

    pub fn value_names(&self) -> Vec<&str> {
        self.values.iter().map(|v| v.name.as_str()).collect()
    }

    pub fn resource_id(&self) -> String {
        format!("enum:{}", self.name)
    }
}

/// 旧格式检测（纯函数）：返回诊断文本，或 None 表示形态合法。
pub fn old_shape_message(data: &serde_json::Value) -> Option<String> {
    const OLD_FIELD_KEYS: &[&str] = &["values", "fields", "element", "element_values"];
    const OLD_TYPE_NAMES: &[&str] = &["enum", "struct", "array"];
    if let Some(fields) = data.get("fields").and_then(|f| f.as_array()) {
        for (index, field) in fields.iter().enumerate() {
            let Some(field) = field.as_object() else {
                continue;
            };
            let old_keys: Vec<&str> = OLD_FIELD_KEYS
                .iter()
                .filter(|k| field.contains_key(**k))
                .copied()
                .collect();
            let old_type = field
                .get("type")
                .and_then(|t| t.as_str())
                .is_some_and(|t| OLD_TYPE_NAMES.contains(&t));
            if !old_keys.is_empty() || old_type {
                let name = field
                    .get("name")
                    .and_then(|n| n.as_str())
                    .map(String::from)
                    .unwrap_or_else(|| format!("#{}", index + 1));
                return Some(format!(
                    "字段 {name} 使用旧格式；请改为具名 Enum/Record 与 vector<T>，\
                     产品不会自动迁移或写回"
                ));
            }
        }
    }
    if data.get("kind").and_then(|k| k.as_str()) == Some("enum")
        && data
            .get("values")
            .and_then(|v| v.as_array())
            .is_some_and(|values| values.iter().any(|v| v.is_string()))
    {
        return Some("Enum values 必须是 {name, comment} 结构，产品不会自动迁移".into());
    }
    None
}

/// 替换字段类型（保持其他字段）。
pub fn replace_field_type(field: &FieldDef, type_expr: TypeExpr) -> FieldDef {
    FieldDef {
        type_expr,
        ..field.clone()
    }
}

/// NamedRef 构造的便捷入口（加载期裸名）。
pub fn named(name: &str) -> Result<TypeExpr, String> {
    Ok(TypeExpr::Named(NamedRef::parse(name)?))
}
