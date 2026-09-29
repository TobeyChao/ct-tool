//! Schema 编辑命令与重放（对应 Python `schema/commands.py` +
//! `app/schema_workspace/commands_reducer.py`）。
//!
//! 命令是对基线资源元组的纯函数；`DraftLog` 用 cursor 实现 undo/redo，
//! 重放 `commands[..cursor]` 永远得到当前草稿。

use std::collections::BTreeMap;

use crate::indexes::parse_indexes;
use crate::naming::validate_name;
use crate::repository::Resource;
use crate::schema::{EnumItem, EnumResource, FieldDef, QueryIndex, RecordResource, TableResource};
use crate::types::{NamedRef, TypeExpr};

/// 草稿状态：资源元组 + 表级索引声明（索引随草稿，不落盘直到保存）。
#[derive(Debug, Clone, PartialEq, Default)]
pub struct DraftState {
    pub resources: Vec<Resource>,
    pub indexes: BTreeMap<String, Vec<QueryIndex>>,
}

/// 一条编辑命令（结构化 JSON payload；kind 词表由内核拥有）。
#[derive(Debug, Clone, PartialEq)]
pub struct Command {
    pub kind: String,
    pub payload: serde_json::Value,
}

impl Command {
    pub fn new(kind: &str, payload: serde_json::Value) -> Self {
        Command {
            kind: kind.to_string(),
            payload,
        }
    }

    fn str_arg(&self, key: &str) -> Result<String, String> {
        self.payload
            .get(key)
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .ok_or_else(|| format!("命令 {} 缺少字符串参数 {key}", self.kind))
    }
}

/// 改名结果：新资源元组 + 旧规范路径 → 新规范路径映射。
#[derive(Debug, Clone)]
pub struct RenameResult {
    pub resources: Vec<Resource>,
    pub mapping: BTreeMap<String, String>,
}

impl RenameResult {
    pub fn reverse_mapping(&self) -> BTreeMap<String, String> {
        self.mapping
            .iter()
            .map(|(old, new)| (new.clone(), old.clone()))
            .collect()
    }
}

fn remap_named_references(expr: &TypeExpr, name_map: &BTreeMap<String, String>) -> TypeExpr {
    match expr {
        TypeExpr::Named(named) => {
            let Some(new_name) = name_map.get(named.name()) else {
                return expr.clone();
            };
            if new_name == named.name() {
                return expr.clone();
            }
            let id = match named.expected_kind() {
                Some(kind) => format!("{}:{new_name}", kind.as_str()),
                None => new_name.clone(),
            };
            TypeExpr::Named(NamedRef::parse(&id).expect("改名目标已通过命名校验"))
        }
        TypeExpr::Vector(element) => {
            TypeExpr::Vector(Box::new(remap_named_references(element, name_map)))
        }
        TypeExpr::Scalar(_) => expr.clone(),
    }
}

fn remap_resource(
    resource: &Resource,
    renamed: &BTreeMap<String, String>,
    ref_table_map: &BTreeMap<String, String>,
) -> Resource {
    let remap_fields = |fields: &[FieldDef]| -> Vec<FieldDef> {
        fields
            .iter()
            .map(|f| {
                crate::schema::replace_field_type(f, remap_named_references(&f.type_expr, renamed))
            })
            .collect()
    };
    match resource {
        Resource::Table(table) => {
            let mut new_fields = remap_fields(&table.fields);
            // 跨表 ref：仅当 Table 改名时改写 "OldTable.Field" 前缀
            if !ref_table_map.is_empty() {
                for field in &mut new_fields {
                    if let Some(ref_) = &field.ref_ {
                        let head = ref_.split('.').next().unwrap_or("");
                        if let Some(new_table) = ref_table_map.get(head) {
                            field.ref_ =
                                Some(format!("{new_table}{rest}", rest = &ref_[head.len()..]));
                        }
                    }
                }
            }
            let mut updated = table.clone();
            updated.fields = new_fields;
            if let Some(new_name) = renamed.get(&table.table) {
                updated.table = new_name.clone();
            }
            Resource::Table(updated)
        }
        Resource::Record(record) => {
            let mut updated = record.clone();
            updated.fields = remap_fields(&record.fields);
            if let Some(new_name) = renamed.get(&record.name) {
                updated.name = new_name.clone();
            }
            Resource::Record(updated)
        }
        Resource::Enum(enum_) => {
            let mut updated = enum_.clone();
            if let Some(new_name) = renamed.get(&enum_.name) {
                updated.name = new_name.clone();
            }
            Resource::Enum(updated)
        }
    }
}

/// 原子改名资源并改写所有引用。
pub fn rename_resource(
    resources: &[Resource],
    old_name: &str,
    new_name: &str,
) -> Result<RenameResult, String> {
    if let Some(error) = validate_name(new_name) {
        return Err(format!("新资源名 {new_name}: {error}"));
    }
    let names: Vec<&str> = resources.iter().map(|r| r.name()).collect();
    if !names.contains(&old_name) {
        return Err(format!("资源 '{old_name}' 不存在"));
    }
    if names.contains(&new_name) && new_name != old_name {
        return Err(format!("资源名 '{new_name}' 已存在"));
    }
    let renamed: BTreeMap<String, String> = [(old_name.to_string(), new_name.to_string())]
        .into_iter()
        .collect();
    let old_resource = resources
        .iter()
        .find(|r| r.name() == old_name)
        .expect("已确认存在");
    // 跨表 ref 只指向 Table；Record/Enum 改名不改写 ref
    let ref_table_map: BTreeMap<String, String> = if matches!(old_resource, Resource::Table(_)) {
        renamed.clone()
    } else {
        BTreeMap::new()
    };
    let new_resources = resources
        .iter()
        .map(|r| remap_resource(r, &renamed, &ref_table_map))
        .collect();
    let kind = old_resource
        .resource_id()
        .split(':')
        .next()
        .unwrap()
        .to_string();
    Ok(RenameResult {
        resources: new_resources,
        mapping: [(old_resource.resource_id(), format!("{kind}:{new_name}"))]
            .into_iter()
            .collect(),
    })
}

/// 改名字段（Table 主键不可改）。其他表只改写指向 owner 的 ref，不改字段名。
pub fn rename_field(
    resources: &[Resource],
    owner_id: &str,
    old_field: &str,
    new_field: &str,
) -> Result<RenameResult, String> {
    if let Some(error) = validate_name(new_field) {
        return Err(format!("新字段名 {new_field}: {error}"));
    }
    let owner_index = resources
        .iter()
        .position(|r| r.resource_id() == owner_id)
        .ok_or_else(|| format!("资源 {owner_id} 不存在"))?;
    let owner = &resources[owner_index];
    let owner_fields: &[FieldDef] = match owner {
        Resource::Table(t) => &t.fields,
        Resource::Record(r) => &r.fields,
        Resource::Enum(_) => {
            return Err(format!("{owner_id} 是 Enum，字段改名请用 rename_enum_item"));
        }
    };
    if !owner_fields.iter().any(|f| f.name == old_field) {
        return Err(format!("{owner_id}/{old_field} 不存在"));
    }
    if let Resource::Table(t) = owner {
        if t.primary == old_field {
            return Err(format!("{owner_id}/{old_field}: 主键字段不可改名"));
        }
    }
    if owner_fields.iter().any(|f| f.name == new_field) && new_field != old_field {
        return Err(format!("{owner_id}/{new_field} 已存在"));
    }
    let owner_table = owner_id.split(':').nth(1).unwrap_or("").to_string();

    let remap_ref = |field: &FieldDef| -> FieldDef {
        // 改写指向 owner 表旧字段的 ref（历史兼容：ref 现已收窄为主键外键）
        if let Some(ref_) = &field.ref_ {
            if *ref_ == format!("{owner_table}.{old_field}") {
                let mut updated = field.clone();
                updated.ref_ = Some(format!("{owner_table}.{new_field}"));
                return updated;
            }
        }
        field.clone()
    };

    let mut new_resources = Vec::with_capacity(resources.len());
    for resource in resources {
        if resource.resource_id() == owner_id {
            let fields = owner_fields
                .iter()
                .map(|f| {
                    let mut f = if f.name == old_field {
                        let mut renamed = f.clone();
                        renamed.name = new_field.to_string();
                        renamed
                    } else {
                        f.clone()
                    };
                    f = remap_ref(&f);
                    f
                })
                .collect();
            new_resources.push(match resource {
                Resource::Table(t) => {
                    let mut updated = t.clone();
                    updated.fields = fields;
                    Resource::Table(updated)
                }
                Resource::Record(r) => {
                    let mut updated = r.clone();
                    updated.fields = fields;
                    Resource::Record(updated)
                }
                other => other.clone(),
            });
        } else if let Resource::Table(t) = resource {
            let mut updated = t.clone();
            updated.fields = t.fields.iter().map(remap_ref).collect();
            new_resources.push(Resource::Table(updated));
        } else {
            new_resources.push(resource.clone());
        }
    }
    Ok(RenameResult {
        resources: new_resources,
        mapping: [(
            format!("{owner_id}/{old_field}"),
            format!("{owner_id}/{new_field}"),
        )]
        .into_iter()
        .collect(),
    })
}

// ---------------------------------------------------------------------------
// reducer
// ---------------------------------------------------------------------------

const ALLOWED_PROPERTIES: &[&str] = &["comment", "i18n", "server_only", "excel_columns", "ref"];

fn resource_index(resources: &[Resource], resource_id: &str) -> Result<usize, String> {
    resources
        .iter()
        .position(|r| r.resource_id() == resource_id)
        .ok_or_else(|| format!("资源 {resource_id} 不存在"))
}

fn fields_of(resource: &Resource) -> Result<&[FieldDef], String> {
    match resource {
        Resource::Table(t) => Ok(&t.fields),
        Resource::Record(r) => Ok(&r.fields),
        Resource::Enum(_) => Err(format!("{} 没有字段列表", resource.resource_id())),
    }
}

fn with_fields(resource: &Resource, fields: Vec<FieldDef>) -> Resource {
    match resource {
        Resource::Table(t) => {
            let mut updated = t.clone();
            updated.fields = fields;
            Resource::Table(updated)
        }
        Resource::Record(r) => {
            let mut updated = r.clone();
            updated.fields = fields;
            Resource::Record(updated)
        }
        other => other.clone(),
    }
}

fn field_index(fields: &[FieldDef], name: &str) -> Result<usize, String> {
    fields
        .iter()
        .position(|f| f.name == name)
        .ok_or_else(|| format!("字段 {name} 不存在"))
}

/// 结构化创建资源解码（对应 Python `decode_resource_payload`）。
pub fn decode_resource_payload(kind: &str, data: &serde_json::Value) -> Result<Resource, String> {
    decode_resource_detailed(kind, data).map_err(|error| error.message)
}

/// Structured command locations are produced with the domain decoder; HTTP
/// and worker callers must not infer field paths from translated error text.
pub struct CommandPayloadError {
    pub location: String,
    pub message: String,
}
impl CommandPayloadError {
    fn new(location: &str, message: impl ToString) -> Self {
        Self {
            location: location.into(),
            message: message.to_string(),
        }
    }
}

fn decode_json_resource<T: serde::de::DeserializeOwned>(
    data: serde_json::Value,
) -> Result<T, CommandPayloadError> {
    serde_path_to_error::deserialize(data).map_err(|error| {
        let path = error.path().to_string();
        let location = if path.is_empty() || path == "." {
            "payload.resource".into()
        } else {
            format!("payload.resource.{path}")
        };
        CommandPayloadError::new(&location, error.inner())
    })
}

fn decode_resource_detailed(
    kind: &str,
    data: &serde_json::Value,
) -> Result<Resource, CommandPayloadError> {
    if !matches!(kind, "table" | "record" | "enum") {
        return Err(CommandPayloadError::new(
            "payload.kind",
            format!("未知的资源类别 {kind:?}；只支持 table、record、enum"),
        ));
    }
    if !data.is_object() {
        return Err(CommandPayloadError::new(
            "payload.resource",
            "resource 必须是对象",
        ));
    }
    if let Some(declared) = data.get("kind").and_then(|k| k.as_str()) {
        if declared != kind {
            return Err(CommandPayloadError::new(
                "payload.resource.kind",
                format!("resource.kind={declared:?} 与命令类别 {kind:?} 不一致"),
            ));
        }
    }
    if kind == "table" {
        if data.get("name").is_some() {
            return Err(CommandPayloadError::new(
                "payload.resource.name",
                "Table 使用 table/primary/fields，不接受 name",
            ));
        }
        if data.get("table").is_none() {
            return Err(CommandPayloadError::new(
                "payload.resource.table",
                "Table 缺少 table",
            ));
        }
    } else if data.get("name").is_none() {
        return Err(CommandPayloadError::new(
            "payload.resource.name",
            format!("{kind} 缺少 name"),
        ));
    }
    if let Some(message) = crate::schema::old_shape_message(data) {
        return Err(CommandPayloadError::new("payload.resource", message));
    }
    // YAML accepts shorthand enum items; editing commands use explicit objects
    // so comments and future properties cannot be silently discarded.
    if kind == "enum"
        && data
            .get("values")
            .and_then(|v| v.as_array())
            .is_some_and(|values| values.iter().any(|v| !v.is_object()))
    {
        return Err(CommandPayloadError::new(
            "payload.resource",
            "Enum values 必须为具名对象列表",
        ));
    }
    match kind {
        "table" => {
            let table: TableResource = decode_json_resource(data.clone())?;
            table
                .validate()
                .map_err(|e| CommandPayloadError::new("payload.resource", e))?;
            Ok(Resource::Table(table))
        }
        "record" => {
            let mut data = data.clone();
            data.as_object_mut()
                .expect("已检查对象")
                .entry("kind")
                .or_insert_with(|| serde_json::Value::String("record".into()));
            let record: RecordResource = decode_json_resource(data)?;
            record
                .validate()
                .map_err(|e| CommandPayloadError::new("payload.resource", e))?;
            Ok(Resource::Record(record))
        }
        _ => {
            let mut data = data.clone();
            data.as_object_mut()
                .expect("已检查对象")
                .entry("kind")
                .or_insert_with(|| serde_json::Value::String("enum".into()));
            let enum_: EnumResource = decode_json_resource(data)?;
            enum_
                .validate()
                .map_err(|e| CommandPayloadError::new("payload.resource", e))?;
            Ok(Resource::Enum(enum_))
        }
    }
}

fn decode_add_resource(command: &Command) -> Result<Resource, String> {
    decode_add_resource_detailed(command).map_err(|error| error.message)
}

pub fn command_payload_error(command: &Command) -> Option<CommandPayloadError> {
    match command.kind.as_str() {
        "add_resource" => decode_add_resource_detailed(command).err(),
        _ => None,
    }
}

fn decode_add_resource_detailed(command: &Command) -> Result<Resource, CommandPayloadError> {
    let resource = command.payload.get("resource").ok_or_else(|| {
        CommandPayloadError::new("payload.resource", "add_resource 缺少 resource")
    })?;
    let kind = command
        .payload
        .get("kind")
        .and_then(|k| k.as_str())
        .map(|s| s.to_string())
        .or_else(|| {
            if resource.get("table").is_some() {
                Some("table".to_string())
            } else {
                resource
                    .get("kind")
                    .and_then(|k| k.as_str())
                    .map(|s| s.to_string())
            }
        })
        .ok_or_else(|| CommandPayloadError::new("payload.kind", "add_resource 缺少 kind"))?;
    decode_resource_detailed(&kind, resource)
}

/// 应用单条命令（纯函数）。
pub fn apply_command(state: &DraftState, command: &Command) -> Result<DraftState, String> {
    let resources = &state.resources;
    let indexes = &state.indexes;
    match command.kind.as_str() {
        "add_resource" => {
            let resource = decode_add_resource(command)?;
            if resources
                .iter()
                .any(|existing| existing.resource_id() == resource.resource_id())
            {
                return Err(format!("资源 {} 已存在", resource.resource_id()));
            }
            let mut new_indexes = indexes.clone();
            if let Resource::Table(table) = &resource {
                // Table 的索引声明随资源一起创建，避免 merge 时被抹掉
                new_indexes.insert(resource.resource_id(), table.indexes.clone());
            }
            let mut new_resources = resources.clone();
            new_resources.push(resource);
            Ok(DraftState {
                resources: new_resources,
                indexes: new_indexes,
            })
        }
        "delete_resource" => {
            let name = command.str_arg("name")?;
            let index = resource_index(resources, &name)?;
            let mut new_resources = resources.clone();
            let removed = new_resources.remove(index);
            let mut new_indexes = indexes.clone();
            new_indexes.remove(&removed.resource_id());
            Ok(DraftState {
                resources: new_resources,
                indexes: new_indexes,
            })
        }
        "rename_resource" => {
            let result = rename_resource(
                resources,
                &command.str_arg("old")?,
                &command.str_arg("new")?,
            )?;
            let new_indexes = indexes
                .iter()
                .map(|(id, declared)| {
                    (
                        result
                            .mapping
                            .get(id)
                            .cloned()
                            .unwrap_or_else(|| id.clone()),
                        declared.clone(),
                    )
                })
                .collect();
            Ok(DraftState {
                resources: result.resources,
                indexes: new_indexes,
            })
        }
        "rename_field" => {
            let result = rename_field(
                resources,
                &command.str_arg("owner")?,
                &command.str_arg("old")?,
                &command.str_arg("new")?,
            )?;
            Ok(DraftState {
                resources: result.resources,
                indexes: indexes.clone(),
            })
        }
        "add_field" => {
            let owner_id = command.str_arg("owner")?;
            let field: FieldDef = serde_json::from_value(
                command
                    .payload
                    .get("field")
                    .cloned()
                    .ok_or_else(|| "add_field 缺少 field".to_string())?,
            )
            .map_err(|e| format!("add_field 字段非法: {e}"))?;
            field.validate().map_err(|e| e.0)?;
            let owner_index = resource_index(resources, &owner_id)?;
            let mut fields = fields_of(&resources[owner_index])?.to_vec();
            fields.push(field);
            let mut new_resources = resources.clone();
            new_resources[owner_index] = with_fields(&resources[owner_index], fields);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "delete_field" => {
            let owner_id = command.str_arg("owner")?;
            let name = command.str_arg("name")?;
            let owner_index = resource_index(resources, &owner_id)?;
            let owner = &resources[owner_index];
            if let Resource::Table(table) = owner {
                if table.primary == name {
                    return Err(format!("主键字段 '{name}' 不可删除"));
                }
            }
            let fields: Vec<FieldDef> = fields_of(owner)?
                .iter()
                .filter(|f| f.name != name)
                .cloned()
                .collect();
            let mut new_resources = resources.clone();
            new_resources[owner_index] = with_fields(owner, fields);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "move_field" => {
            let owner_id = command.str_arg("owner")?;
            let name = command.str_arg("name")?;
            let to_index = command
                .payload
                .get("to")
                .and_then(|v| v.as_u64())
                .ok_or_else(|| "move_field 缺少 to".to_string())?
                as usize;
            let owner_index = resource_index(resources, &owner_id)?;
            let owner = &resources[owner_index];
            if let Resource::Table(table) = owner {
                if table.primary == name {
                    return Err(format!("主键字段 '{name}' 不可调整顺序"));
                }
            }
            let mut fields = fields_of(owner)?.to_vec();
            let from_index = field_index(&fields, &name)?;
            let field = fields.remove(from_index);
            fields.insert(to_index.min(fields.len()), field);
            let mut new_resources = resources.clone();
            new_resources[owner_index] = with_fields(owner, fields);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "set_property" => {
            let owner_id = command.str_arg("owner")?;
            let name = command.str_arg("name")?;
            let property = command.str_arg("property")?;
            if !ALLOWED_PROPERTIES.contains(&property.as_str()) {
                return Err(format!("不允许的属性: {property}"));
            }
            let value = command
                .payload
                .get("value")
                .cloned()
                .ok_or_else(|| "set_property 缺少 value".to_string())?;
            let owner_index = resource_index(resources, &owner_id)?;
            let owner = &resources[owner_index];
            let mut fields = fields_of(owner)?.to_vec();
            let index = field_index(&fields, &name)?;
            let field = &mut fields[index];
            match property.as_str() {
                "comment" => {
                    field.comment = value.as_str().unwrap_or_default().to_string();
                }
                "i18n" => {
                    field.i18n = value
                        .as_bool()
                        .ok_or_else(|| "i18n 必须是 bool".to_string())?;
                }
                "server_only" => {
                    field.server_only = value
                        .as_bool()
                        .ok_or_else(|| "server_only 必须是 bool".to_string())?;
                }
                "excel_columns" => {
                    field.excel_columns = match &value {
                        serde_json::Value::Null => None,
                        serde_json::Value::Number(n) => Some(
                            n.as_u64()
                                .ok_or_else(|| "excel_columns 必须是正整数".to_string())?
                                as u32,
                        ),
                        _ => return Err("excel_columns 必须是正整数或 null".to_string()),
                    };
                }
                "ref" => {
                    field.ref_ = match &value {
                        serde_json::Value::Null => None,
                        serde_json::Value::String(s) => {
                            if s.is_empty() {
                                None
                            } else {
                                Some(s.clone())
                            }
                        }
                        _ => return Err("ref 必须是字符串或 null".to_string()),
                    };
                }
                _ => unreachable!("已检查白名单"),
            }
            let mut new_resources = resources.clone();
            new_resources[owner_index] = with_fields(owner, fields);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "set_type" => {
            let owner_id = command.str_arg("owner")?;
            let name = command.str_arg("name")?;
            let type_text = command.str_arg("type_text")?;
            let type_expr =
                TypeExpr::parse(&type_text).map_err(|e| format!("无效类型表达式: {e}"))?;
            let owner_index = resource_index(resources, &owner_id)?;
            let owner = &resources[owner_index];
            let mut fields = fields_of(owner)?.to_vec();
            let index = field_index(&fields, &name)?;
            fields[index] = crate::schema::replace_field_type(&fields[index], type_expr);
            let mut new_resources = resources.clone();
            new_resources[owner_index] = with_fields(owner, fields);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "set_enum_values" => {
            let name = command.str_arg("name")?;
            let values: Vec<EnumItem> = serde_json::from_value(
                command
                    .payload
                    .get("values")
                    .cloned()
                    .ok_or_else(|| "set_enum_values 缺少 values".to_string())?,
            )
            .map_err(|e| format!("set_enum_values values 非法: {e}"))?;
            let index = resource_index(resources, &name)?;
            let Resource::Enum(enum_) = &resources[index] else {
                return Err(format!("{name} 不是 Enum"));
            };
            let mut updated = enum_.clone();
            updated.values = values;
            let mut new_resources = resources.clone();
            new_resources[index] = Resource::Enum(updated);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "rename_enum_item" => {
            let name = command.str_arg("name")?;
            let old_name = command.str_arg("oldName")?;
            let new_name = command.str_arg("newName")?;
            let ordinal = command
                .payload
                .get("originalOrdinal")
                .and_then(|v| v.as_i64())
                .ok_or_else(|| "rename_enum_item 缺少 originalOrdinal".to_string())?;
            let index = resource_index(resources, &name)?;
            let Resource::Enum(enum_) = &resources[index] else {
                return Err(format!("{name} 不是 Enum"));
            };
            if ordinal < 0 || ordinal as usize >= enum_.values.len() {
                return Err(format!("Enum {name}: ordinal {ordinal} 不存在"));
            }
            let item = &enum_.values[ordinal as usize];
            if item.name != old_name {
                return Err(format!(
                    "Enum {name}: ordinal {ordinal} 当前为 {}，不是 {old_name}",
                    item.name
                ));
            }
            if enum_.values.iter().any(|v| v.name == new_name) {
                return Err(format!("Enum {name}: 值 '{new_name}' 已存在"));
            }
            let mut updated = enum_.clone();
            updated.values[ordinal as usize].name = new_name;
            let mut new_resources = resources.clone();
            new_resources[index] = Resource::Enum(updated);
            Ok(DraftState {
                resources: new_resources,
                indexes: indexes.clone(),
            })
        }
        "set_indexes" => {
            let table = command.str_arg("table")?;
            let raw = command
                .payload
                .get("indexes")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            let parsed = parse_indexes(&raw)?;
            let mut new_indexes = indexes.clone();
            new_indexes.insert(table, parsed);
            Ok(DraftState {
                resources: resources.clone(),
                indexes: new_indexes,
            })
        }
        other => Err(format!("未知命令类型: {other}")),
    }
}

pub fn apply_commands(state: &DraftState, commands: &[Command]) -> Result<DraftState, String> {
    let mut result = state.clone();
    for command in commands {
        result = apply_command(&result, command)?;
    }
    Ok(result)
}

/// 命令日志 + undo/redo 游标（基线不可变）。
#[derive(Debug, Clone)]
pub struct DraftLog {
    pub base: DraftState,
    pub commands: Vec<Command>,
    pub cursor: usize,
}

impl DraftLog {
    pub fn new(base: DraftState) -> Self {
        DraftLog {
            base,
            commands: Vec::new(),
            cursor: 0,
        }
    }

    /// 当前草稿 = 基线重放 commands[..cursor]。
    pub fn current(&self) -> Result<DraftState, String> {
        apply_commands(&self.base, &self.commands[..self.cursor])
    }

    /// 执行新命令：截断游标后的重做分支。
    pub fn execute(&mut self, command: Command) -> Result<(), String> {
        // 先验证命令可应用，再截断重做分支（失败命令不得吞掉 redo 历史）
        let candidate = self.current()?;
        apply_command(&candidate, &command)?;
        self.commands.truncate(self.cursor);
        self.commands.push(command);
        self.cursor += 1;
        Ok(())
    }

    pub fn undo(&mut self) -> bool {
        if self.cursor > 0 {
            self.cursor -= 1;
            true
        } else {
            false
        }
    }

    pub fn redo(&mut self) -> bool {
        if self.cursor < self.commands.len() {
            self.cursor += 1;
            true
        } else {
            false
        }
    }
}
