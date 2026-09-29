//! 类型表达式：文本括号文法 + 领域节点（`ct/schema/type_expression.py`）。
//!
//! 文本形态（YAML/Excel 表头）：`int32`、`ItemRarity`、`vector<DropReward>`；
//! 领域节点：scalar / named / vector。具名引用加载后可未解析（裸名），
//! 仓库解析后绑定 `record:`/`enum:` 前缀。

use serde::{Deserialize, Serialize};

use crate::naming::validate_name;

pub const SCALAR_TYPE_NAMES: &[&str] = &[
    "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64", "float", "double",
    "bool", "string",
];

pub const INTEGER_SCALAR_NAMES: &[&str] = &[
    "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64",
];

/// 各整数标量的值域。
pub fn integer_scalar_range(name: &str) -> Option<(i128, i128)> {
    Some(match name {
        "int8" => (i8::MIN as i128, i8::MAX as i128),
        "uint8" => (0, u8::MAX as i128),
        "int16" => (i16::MIN as i128, i16::MAX as i128),
        "uint16" => (0, u16::MAX as i128),
        "int32" => (i32::MIN as i128, i32::MAX as i128),
        "uint32" => (0, u32::MAX as i128),
        "int64" => (i64::MIN as i128, i64::MAX as i128),
        "uint64" => (0, u64::MAX as i128),
        _ => return None,
    })
}

/// 主键唯一允许的类型。
pub const PRIMARY_KEY_TYPE: &str = "int32";

pub fn scalar_default_json(name: &str) -> serde_json::Value {
    match name {
        "string" => serde_json::Value::String(String::new()),
        "bool" => serde_json::Value::Bool(false),
        "float" | "double" => serde_json::Value::from(0.0),
        _ => serde_json::Value::from(0),
    }
}

pub fn is_reserved_type_name(name: &str) -> bool {
    SCALAR_TYPE_NAMES.contains(&name) || matches!(name, "vector" | "table" | "record" | "enum")
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NamedKind {
    Record,
    Enum,
}

impl NamedKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            NamedKind::Record => "record",
            NamedKind::Enum => "enum",
        }
    }
}

/// 具名引用：裸名（未解析）或 `record:X` / `enum:X`（已解析）。
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct NamedRef {
    resource_id: String,
}

impl NamedRef {
    pub fn parse(text: &str) -> Result<Self, String> {
        let text = text.trim();
        if text.is_empty() {
            return Err("named type resource_id 不能为空".to_string());
        }
        let mut kind = None;
        let mut name = text;
        if let Some((prefix, rest)) = text.split_once(':') {
            match prefix {
                "record" | "enum" => {
                    if rest.contains(':') {
                        return Err(
                            "named type resource_id 必须为 record:<Name> 或 enum:<Name>".into()
                        );
                    }
                    kind = Some(prefix);
                    name = rest;
                }
                _ => {
                    return Err("named type resource_id 必须为 record:<Name> 或 enum:<Name>".into())
                }
            }
        }
        if is_reserved_type_name(name) {
            return Err(format!("'{name}' 是保留类型名，不能作为具名资源"));
        }
        if let Some(error) = validate_name(name) {
            return Err(format!("具名类型 {name}: {error}"));
        }
        Ok(NamedRef {
            resource_id: match kind {
                Some(k) => format!("{k}:{name}"),
                None => name.to_string(),
            },
        })
    }

    /// 裸名（无前缀）。
    pub fn name(&self) -> &str {
        match self.resource_id.split_once(':') {
            Some((_, name)) => name,
            None => &self.resource_id,
        }
    }

    /// 解析后的资源 ID（可能未解析）。
    pub fn resource_id(&self) -> &str {
        &self.resource_id
    }

    pub fn expected_kind(&self) -> Option<NamedKind> {
        self.resource_id
            .split_once(':')
            .and_then(|(prefix, _)| match prefix {
                "record" => Some(NamedKind::Record),
                "enum" => Some(NamedKind::Enum),
                _ => None,
            })
    }

    pub fn resolved(&self) -> bool {
        self.expected_kind().is_some()
    }

    /// 绑定到具体类别。
    pub fn resolve(&self, kind: NamedKind) -> NamedRef {
        NamedRef {
            resource_id: format!("{}:{}", kind.as_str(), self.name()),
        }
    }
}

impl TryFrom<String> for NamedRef {
    type Error = String;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        NamedRef::parse(&value)
    }
}

impl From<NamedRef> for String {
    fn from(value: NamedRef) -> Self {
        value.resource_id
    }
}

impl std::fmt::Display for NamedRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.resource_id)
    }
}

/// 类型表达式。
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum TypeExpr {
    Scalar(String),
    Named(NamedRef),
    Vector(Box<TypeExpr>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeExprError(pub String);

impl std::fmt::Display for TypeExprError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for TypeExprError {}

impl TypeExpr {
    /// 文本括号文法解析。
    pub fn parse(source: &str) -> Result<TypeExpr, TypeExprError> {
        let mut parser = TextParser {
            chars: source.chars().collect(),
            position: 0,
            source,
        };
        parser.parse_root()
    }

    /// 序列化为文本形态。
    pub fn to_text(&self) -> String {
        match self {
            TypeExpr::Scalar(name) => name.clone(),
            TypeExpr::Named(named) => named.name().to_string(),
            TypeExpr::Vector(element) => format!("vector<{}>", element.to_text()),
        }
    }

    /// 展示名（具名引用显示裸名）。
    pub fn display_name(&self) -> String {
        match self {
            TypeExpr::Scalar(name) => name.clone(),
            TypeExpr::Named(named) => named.name().to_string(),
            TypeExpr::Vector(_) => self.to_text(),
        }
    }
}

struct TextParser<'a> {
    chars: Vec<char>,
    position: usize,
    source: &'a str,
}

impl TextParser<'_> {
    fn error(&self, message: impl Into<String>) -> TypeExprError {
        TypeExprError(format!(
            "类型表达式 {:?} 无效: {}",
            self.source,
            message.into()
        ))
    }

    fn parse_root(&mut self) -> Result<TypeExpr, TypeExprError> {
        self.skip_whitespace();
        if self.position == self.chars.len() {
            return Err(self.error("类型表达式为空"));
        }
        let expr = self.parse_expression()?;
        self.skip_whitespace();
        if self.position != self.chars.len() {
            let rest: String = self.chars[self.position..].iter().collect();
            return Err(self.error(format!("存在多余内容 {rest:?}")));
        }
        Ok(expr)
    }

    fn parse_expression(&mut self) -> Result<TypeExpr, TypeExprError> {
        let identifier = self.parse_identifier()?;
        if identifier == "vector" {
            self.skip_whitespace();
            self.expect('<', "vector 后缺少 '<'")?;
            self.skip_whitespace();
            if self.peek() == Some('>') {
                return Err(self.error("vector 元素类型不能为空"));
            }
            let element = self.parse_expression()?;
            self.skip_whitespace();
            self.expect('>', "vector 缺少配对的 '>'")?;
            if matches!(element, TypeExpr::Vector(_)) {
                return Err(self.error("首版不支持 vector<vector<T>>；请使用具名 Record 包装结构"));
            }
            return Ok(TypeExpr::Vector(Box::new(element)));
        }
        if SCALAR_TYPE_NAMES.contains(&identifier.as_str()) {
            return Ok(TypeExpr::Scalar(identifier));
        }
        NamedRef::parse(&identifier)
            .map(TypeExpr::Named)
            .map_err(|e| self.error(e))
    }

    fn parse_identifier(&mut self) -> Result<String, TypeExprError> {
        let start = self.position;
        while self.position < self.chars.len() {
            let ch = self.chars[self.position];
            if ch.is_whitespace() || matches!(ch, '<' | '>' | ',') {
                break;
            }
            self.position += 1;
        }
        if self.position == start {
            return Err(self.error("此处需要类型名"));
        }
        Ok(self.chars[start..self.position].iter().collect())
    }

    fn expect(&mut self, expected: char, message: &str) -> Result<(), TypeExprError> {
        if self.peek() != Some(expected) {
            return Err(self.error(message));
        }
        self.position += 1;
        Ok(())
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.position).copied()
    }

    fn skip_whitespace(&mut self) {
        while self.position < self.chars.len() && self.chars[self.position].is_whitespace() {
            self.position += 1;
        }
    }
}

// ---- serde：文本形态（YAML）与对象形态（测试夹具）双支持 ----

impl Serialize for TypeExpr {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_text())
    }
}

impl<'de> Deserialize<'de> for TypeExpr {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = serde_json::Value::deserialize(deserializer)?;
        type_from_json(&value).map_err(serde::de::Error::custom)
    }
}

fn type_from_json(value: &serde_json::Value) -> Result<TypeExpr, String> {
    match value {
        serde_json::Value::String(text) => TypeExpr::parse(text).map_err(|e| e.to_string()),
        serde_json::Value::Object(map) => {
            if let Some(v) = map.get("scalar") {
                let name = v.as_str().ok_or("scalar 必须是字符串")?;
                if !SCALAR_TYPE_NAMES.contains(&name) {
                    return Err(format!("未知标量类型 {name}"));
                }
                return Ok(TypeExpr::Scalar(name.to_string()));
            }
            if let Some(v) = map.get("named") {
                return Ok(TypeExpr::Named(NamedRef::parse(
                    v.as_str().ok_or("named 必须是字符串")?,
                )?));
            }
            if let Some(v) = map.get("vector") {
                let element = v.get("element").ok_or("vector 缺少 element")?;
                return Ok(TypeExpr::Vector(Box::new(type_from_json(element)?)));
            }
            Err(format!("未知类型表达式: {value}"))
        }
        _ => Err(format!("类型表达式必须是字符串或对象: {value}")),
    }
}
