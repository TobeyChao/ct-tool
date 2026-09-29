//! C#/Lua 共用的 Accessor 模型（`ct/export/canonical_accessor_model.py`）。
//!
//! 两个生成器消费同一模型：客户端字段按槽位序、主键、i18n 字段、
//! CodeName 索引契约；生成器不再解析类型表达式或重推索引规则。

use std::collections::HashMap;

use ct_domain::schema::{FieldDef, RecordResource, TableResource, CODENAME_FIELD};
use ct_domain::types::TypeExpr;

/// C# 标量类型映射（唯一来源）。
pub fn csharp_scalar_type(type_text: &str) -> Option<&'static str> {
    Some(match type_text {
        "int8" => "sbyte",
        "uint8" => "byte",
        "int16" => "short",
        "uint16" => "ushort",
        "int32" => "int",
        "uint32" => "uint",
        "int64" => "long",
        "uint64" => "ulong",
        "float" => "float",
        "double" => "double",
        "bool" => "bool",
        _ => return None,
    })
}

/// 访问器字段。
#[derive(Debug, Clone)]
pub struct AccessorField {
    pub name: String,
    /// 客户端字段（或 record 字段）中的 0-based 槽位。
    pub slot: usize,
    /// scalar | enum | record | vector | string
    pub kind: &'static str,
    pub type_text: String,
    pub i18n: bool,
    /// 嵌套 record（kind=record 或 vector<record>）。
    pub record: Option<RecordResource>,
    /// vector 元素类别：scalar | enum | record | string
    pub element_kind: Option<&'static str>,
    pub element_type: String,
    /// 跨表 ref 目标表名（ref 只能是「目标表.主键」）。
    pub ref_table: Option<String>,
}

impl AccessorField {
    pub fn record_name(&self) -> Option<&str> {
        self.record.as_ref().map(|r| r.name.as_str())
    }

    /// ref 风格单值容器类型文本。
    pub fn container_text(&self) -> Option<String> {
        if self.kind != "vector" {
            return None;
        }
        match self.element_kind {
            Some("record") => self.record_name().map(|n| format!("NStructArray<{n}>")),
            Some("string") => Some("NStructArray<NString>".to_string()),
            Some("enum") => Some(format!("NArray<{}>", self.element_type)),
            _ => csharp_scalar_type(&self.element_type).map(|t| format!("NArray<{t}>")),
        }
    }
}

/// 访问器索引（当前仅 codename）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AccessorIndex {
    pub kind: &'static str,
    pub slot: usize,
}

/// 完整访问器模型。
#[derive(Debug, Clone)]
pub struct AccessorModel {
    pub table: TableResource,
    pub client_fields: Vec<AccessorField>,
    pub primary: AccessorField,
    pub i18n_fields: Vec<AccessorField>,
    pub indexes: Vec<AccessorIndex>,
    /// 定宽布局的 slot→行内偏移表级常量（None = 变长表）。
    pub uniform_offsets: Option<HashMap<u32, u32>>,
    /// 稀疏 i18n 表名（`{Table}_i18n`）。
    pub i18n_table: Option<String>,
    /// 稀疏 i18n 表自己的定宽偏移（vtable 字节偏移 → 行内偏移）。
    pub i18n_uniform_offsets: Option<HashMap<u32, u32>>,
}

impl AccessorModel {
    pub fn has_i18n(&self) -> bool {
        !self.i18n_fields.is_empty()
    }

    pub fn is_uniform(&self) -> bool {
        self.uniform_offsets.is_some()
    }
}

fn ref_table(field: &FieldDef) -> Option<String> {
    field
        .ref_
        .as_deref()
        .and_then(|r| r.split('.').next())
        .filter(|s| !s.is_empty())
        .map(String::from)
}

fn build_field(
    field: &FieldDef,
    slot: usize,
    records: Option<&HashMap<String, RecordResource>>,
) -> AccessorField {
    let lookup = |name: &str| records.and_then(|r| r.get(name).cloned());
    match &field.type_expr {
        TypeExpr::Vector(element) => {
            let base = AccessorField {
                name: field.name.clone(),
                slot,
                kind: "vector",
                type_text: field.type_text(),
                i18n: field.i18n,
                record: None,
                element_kind: None,
                element_type: String::new(),
                ref_table: ref_table(field),
            };
            match element.as_ref() {
                TypeExpr::Named(named) => {
                    let record = lookup(named.name());
                    AccessorField {
                        element_kind: Some(if record.is_some() { "record" } else { "enum" }),
                        element_type: named.name().to_string(),
                        record,
                        ..base
                    }
                }
                TypeExpr::Scalar(name) => AccessorField {
                    element_kind: Some(if name == "string" { "string" } else { "scalar" }),
                    element_type: name.clone(),
                    ..base
                },
                TypeExpr::Vector(_) => AccessorField {
                    element_kind: Some("scalar"),
                    ..base
                },
            }
        }
        TypeExpr::Named(named) => {
            let record = lookup(named.name());
            AccessorField {
                name: field.name.clone(),
                slot,
                kind: if record.is_some() { "record" } else { "enum" },
                type_text: named.name().to_string(),
                i18n: field.i18n,
                record,
                element_kind: None,
                element_type: String::new(),
                ref_table: ref_table(field),
            }
        }
        TypeExpr::Scalar(name) => AccessorField {
            name: field.name.clone(),
            slot,
            kind: if name == "string" { "string" } else { "scalar" },
            type_text: name.clone(),
            i18n: field.i18n,
            record: None,
            element_kind: None,
            element_type: String::new(),
            ref_table: ref_table(field),
        },
    }
}

/// Record 的字段 → AccessorField（槽位 = 字段序）。
pub fn record_accessor_fields(
    record: &RecordResource,
    records: Option<&HashMap<String, RecordResource>>,
) -> Vec<AccessorField> {
    record
        .fields
        .iter()
        .enumerate()
        .map(|(index, field)| build_field(field, index, records))
        .collect()
}

/// 表引用的全部 record（传递闭包，前序确定序，父先于子）。
pub fn referenced_records(
    model: &AccessorModel,
    records: &HashMap<String, RecordResource>,
) -> Vec<RecordResource> {
    let mut result = Vec::new();
    let mut seen = std::collections::HashSet::new();

    fn visit(
        record: &RecordResource,
        records: &HashMap<String, RecordResource>,
        seen: &mut std::collections::HashSet<String>,
        result: &mut Vec<RecordResource>,
    ) {
        if !seen.insert(record.name.clone()) {
            return;
        }
        result.push(record.clone());
        for sub in record_accessor_fields(record, Some(records)) {
            if let Some(nested) = sub.record {
                visit(&nested, records, seen, result);
            }
        }
    }

    for field in &model.client_fields {
        if let Some(record) = &field.record {
            visit(record, records, &mut seen, &mut result);
        }
    }
    result
}

/// 构建访问器模型。
pub fn build_accessor_model(
    table: &TableResource,
    indexes: &[ct_domain::schema::QueryIndex],
    records: Option<&HashMap<String, RecordResource>>,
    uniform_offsets: Option<HashMap<u32, u32>>,
    i18n_table: Option<String>,
    i18n_uniform_offsets: Option<HashMap<u32, u32>>,
) -> AccessorModel {
    let client: Vec<&FieldDef> = table.client_fields().collect();
    let slots: HashMap<&str, usize> = client
        .iter()
        .enumerate()
        .map(|(i, f)| (f.name.as_str(), i))
        .collect();
    let fields: Vec<AccessorField> = client
        .iter()
        .map(|f| build_field(f, slots[f.name.as_str()], records))
        .collect();
    let primary = fields
        .iter()
        .find(|f| f.name == table.primary)
        .expect("主键字段必须存在")
        .clone();
    let i18n_fields: Vec<AccessorField> = fields.iter().filter(|f| f.i18n).cloned().collect();

    let i18n_table = i18n_table.or_else(|| {
        if i18n_fields.is_empty() {
            None
        } else {
            Some(format!("{}_i18n", table.table))
        }
    });
    let accessor_indexes = indexes
        .iter()
        .map(|_| AccessorIndex {
            kind: "codename",
            slot: slots[CODENAME_FIELD],
        })
        .collect();

    AccessorModel {
        table: table.clone(),
        client_fields: fields,
        primary,
        i18n_fields,
        indexes: accessor_indexes,
        uniform_offsets,
        i18n_table,
        i18n_uniform_offsets,
    }
}
