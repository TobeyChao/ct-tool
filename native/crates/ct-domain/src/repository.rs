//! YAML 资源仓库（`ct/schema/resource_repository.py`）：
//! 目录/捕获内容加载、旧格式拒绝、重名与大小写冲突、具名类型解析。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::schema::{
    old_shape_message, replace_field_type, EnumResource, FieldDef, RecordResource, SchemaError,
    TableResource,
};
use crate::types::{NamedKind, TypeExpr};

/// 资源工作区：全部资源 + 名字/ID 索引 + 来源文件。
#[derive(Debug, Clone)]
pub struct ResourceWorkspace {
    pub tables: Vec<TableResource>,
    pub records: Vec<RecordResource>,
    pub enums: Vec<EnumResource>,
    pub by_name: HashMap<String, Resource>,
    pub by_id: HashMap<String, Resource>,
    pub sources: HashMap<String, PathBuf>,
}

/// 资源并集。
#[derive(PartialEq, Debug, Clone)]
pub enum Resource {
    Table(TableResource),
    Record(RecordResource),
    Enum(EnumResource),
}

impl Resource {
    pub fn name(&self) -> &str {
        match self {
            Resource::Table(t) => &t.table,
            Resource::Record(r) => &r.name,
            Resource::Enum(e) => &e.name,
        }
    }

    pub fn resource_id(&self) -> String {
        match self {
            Resource::Table(t) => t.resource_id(),
            Resource::Record(r) => r.resource_id(),
            Resource::Enum(e) => e.resource_id(),
        }
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Resource::Table(_) => "table",
            Resource::Record(_) => "record",
            Resource::Enum(_) => "enum",
        }
    }
}

impl ResourceWorkspace {
    pub fn records_map(&self) -> HashMap<String, RecordResource> {
        self.records
            .iter()
            .map(|r| (r.name.clone(), r.clone()))
            .collect()
    }

    pub fn enums_map(&self) -> HashMap<String, EnumResource> {
        self.enums
            .iter()
            .map(|e| (e.name.clone(), e.clone()))
            .collect()
    }
}

/// 内容来源：真实目录或捕获字节（导出期捕获模式）。
pub enum ContentSource<'a> {
    Disk,
    Captured(&'a HashMap<PathBuf, Vec<u8>>),
}

pub struct YamlResourceRepository {
    schemas_dir: PathBuf,
    types_dir: PathBuf,
}

impl YamlResourceRepository {
    pub fn new(schemas_dir: PathBuf, types_dir: PathBuf) -> Self {
        Self {
            schemas_dir,
            types_dir,
        }
    }

    /// 从目录加载。
    pub fn load(&self) -> Result<ResourceWorkspace, SchemaError> {
        self.load_with(ContentSource::Disk)
    }

    /// 从捕获内容加载（导出期：资源集合与复核字节完全一致）。
    pub fn load_captured(
        &self,
        contents: &HashMap<PathBuf, Vec<u8>>,
    ) -> Result<ResourceWorkspace, SchemaError> {
        self.load_with(ContentSource::Captured(contents))
    }

    fn list_yaml(
        &self,
        dir: &Path,
        source: &ContentSource<'_>,
    ) -> Result<Vec<(PathBuf, Vec<u8>)>, SchemaError> {
        match source {
            ContentSource::Disk => {
                if !dir.exists() {
                    return Ok(Vec::new());
                }
                let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
                    .map_err(|e| SchemaError(format!("读取目录失败 {}: {e}", dir.display())))?
                    .filter_map(|e| e.ok().map(|e| e.path()))
                    .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
                    .collect();
                files.sort();
                let mut out = Vec::new();
                for path in files {
                    let bytes = std::fs::read(&path)
                        .map_err(|e| SchemaError(format!("读取失败 {}: {e}", path.display())))?;
                    out.push((path, bytes));
                }
                Ok(out)
            }
            ContentSource::Captured(contents) => {
                let mut files: Vec<(&PathBuf, &Vec<u8>)> = contents
                    .iter()
                    .filter(|(p, _)| {
                        p.parent() == Some(dir) && p.extension().is_some_and(|e| e == "yaml")
                    })
                    .collect();
                files.sort_by(|a, b| a.0.cmp(b.0));
                Ok(files
                    .into_iter()
                    .map(|(p, b)| (p.clone(), b.clone()))
                    .collect())
            }
        }
    }

    fn read_resource_yaml(
        path: &Path,
        bytes: &[u8],
    ) -> Result<Option<serde_json::Value>, SchemaError> {
        let text = std::str::from_utf8(bytes)
            .map_err(|e| SchemaError(format!("加载 Schema 资源失败 [{}]: {e}", path.display())))?;
        let data: Option<serde_json::Value> = serde_yaml_ng::from_str(text)
            .map_err(|e| SchemaError(format!("加载 Schema 资源失败 [{}]: {e}", path.display())))?;
        match data {
            None => Ok(None),
            Some(v) if v.is_object() => Ok(Some(v)),
            Some(_) => Err(SchemaError(format!(
                "加载 Schema 资源失败 [{}]: 根节点必须是 mapping",
                path.display()
            ))),
        }
    }

    pub fn load_with(&self, source: ContentSource<'_>) -> Result<ResourceWorkspace, SchemaError> {
        let mut tables = Vec::new();
        let mut records = Vec::new();
        let mut enums = Vec::new();
        let mut sources: HashMap<String, PathBuf> = HashMap::new();
        // 同名冲突诊断需要各自的真实来源（resource_id 相同会被覆盖）
        let mut load_paths: Vec<(String, PathBuf)> = Vec::new();

        // schemas_dir：Table
        for (path, bytes) in self.list_yaml(&self.schemas_dir, &source)? {
            let Some(data) = Self::read_resource_yaml(&path, &bytes)? else {
                continue;
            };
            reject_old_shape(&data, &path)?;
            let table: TableResource = serde_json::from_value(data)
                .map_err(|e| SchemaError(format!("加载 Table 失败 [{}]: {e}", file_name(&path))))?;
            table
                .validate()
                .map_err(|e| SchemaError(format!("加载 Table 失败 [{}]: {e}", file_name(&path))))?;
            sources.insert(table.resource_id(), path.clone());
            load_paths.push((table.resource_id(), path));
            tables.push(table);
        }

        // types_dir：Record / Enum
        for (path, bytes) in self.list_yaml(&self.types_dir, &source)? {
            let Some(data) = Self::read_resource_yaml(&path, &bytes)? else {
                continue;
            };
            reject_old_shape(&data, &path)?;
            let kind = data.get("kind").and_then(|k| k.as_str()).unwrap_or("");
            match kind {
                "record" => {
                    let record: RecordResource = serde_json::from_value(data).map_err(|e| {
                        SchemaError(format!("加载具名类型失败 [{}]: {e}", file_name(&path)))
                    })?;
                    record.validate().map_err(|e| {
                        SchemaError(format!("加载具名类型失败 [{}]: {e}", file_name(&path)))
                    })?;
                    sources.insert(record.resource_id(), path.clone());
                    load_paths.push((record.resource_id(), path));
                    records.push(record);
                }
                "enum" => {
                    let enum_: EnumResource = serde_json::from_value(data).map_err(|e| {
                        SchemaError(format!("加载具名类型失败 [{}]: {e}", file_name(&path)))
                    })?;
                    enum_.validate().map_err(|e| {
                        SchemaError(format!("加载具名类型失败 [{}]: {e}", file_name(&path)))
                    })?;
                    sources.insert(enum_.resource_id(), path.clone());
                    load_paths.push((enum_.resource_id(), path));
                    enums.push(enum_);
                }
                _ => {
                    return Err(SchemaError(format!(
                        "加载具名类型失败 [{}]: kind 必须为 record 或 enum",
                        file_name(&path)
                    )))
                }
            }
        }

        // 重名 + 跨平台大小写冲突
        let mut by_name: HashMap<String, Resource> = HashMap::new();
        let mut by_folded: HashMap<String, (String, usize)> = HashMap::new();
        let all: Vec<Resource> = tables
            .iter()
            .cloned()
            .map(Resource::Table)
            .chain(records.iter().cloned().map(Resource::Record))
            .chain(enums.iter().cloned().map(Resource::Enum))
            .collect();
        for (position, resource) in all.iter().enumerate() {
            let name = resource.name().to_string();
            if let Some(previous) = by_name.get(&name) {
                let prev_pos = all
                    .iter()
                    .position(|r| r.resource_id() == previous.resource_id())
                    .unwrap();
                return Err(SchemaError(format!(
                    "资源名 '{}' 重复: {} 和 {}",
                    name,
                    file_name(&load_paths[prev_pos].1),
                    file_name(&load_paths[position].1)
                )));
            }
            let folded = name.to_lowercase();
            if let Some((other_name, other_pos)) = by_folded.get(&folded).cloned() {
                if other_name != name {
                    return Err(SchemaError(format!(
                        "资源名 '{}' 与 '{}' 仅大小写不同，跨平台行为不可确定: {} 和 {}",
                        name,
                        other_name,
                        file_name(&load_paths[other_pos].1),
                        file_name(&load_paths[position].1)
                    )));
                }
            } else {
                by_folded.insert(folded, (name.clone(), position));
            }
            by_name.insert(name, resource.clone());
        }
        let by_id: HashMap<String, Resource> =
            all.into_iter().map(|r| (r.resource_id(), r)).collect();

        // 具名类型解析：裸名 → record:/enum: 绑定
        let resolved_tables = tables
            .iter()
            .map(|t| {
                Ok(TableResource {
                    fields: resolve_fields(&t.fields, &by_name, &t.resource_id())?,
                    ..t.clone()
                })
            })
            .collect::<Result<Vec<_>, SchemaError>>()?;
        let resolved_records = records
            .iter()
            .map(|r| {
                Ok(RecordResource {
                    fields: resolve_fields(&r.fields, &by_name, &r.resource_id())?,
                    ..r.clone()
                })
            })
            .collect::<Result<Vec<_>, SchemaError>>()?;

        let workspace = ResourceWorkspace {
            tables: resolved_tables,
            records: resolved_records,
            enums,
            by_name,
            by_id,
            sources,
        };
        // 生成符号冲突（对齐 Python `require_valid_generated_names`）：
        // 资源名/生成容器名/字段名共享 FlatBuffers 符号空间
        let all: Vec<Resource> = workspace
            .tables
            .iter()
            .cloned()
            .map(Resource::Table)
            .chain(workspace.records.iter().cloned().map(Resource::Record))
            .chain(workspace.enums.iter().cloned().map(Resource::Enum))
            .collect();
        let conflicts = crate::name_validation::generated_name_conflicts(&all);
        if !conflicts.is_empty() {
            return Err(SchemaError(
                conflicts
                    .iter()
                    .map(|c| c.render())
                    .collect::<Vec<_>>()
                    .join("; "),
            ));
        }
        Ok(workspace)
    }
}

fn file_name(path: &Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.display().to_string())
}

fn reject_old_shape(data: &serde_json::Value, path: &Path) -> Result<(), SchemaError> {
    if let Some(message) = old_shape_message(data) {
        return Err(SchemaError(format!(
            "加载 Schema 资源失败 [{}]: {message}",
            path.display()
        )));
    }
    Ok(())
}

fn resolve_type(
    type_expr: &TypeExpr,
    by_name: &HashMap<String, Resource>,
    owner_path: &str,
) -> Result<TypeExpr, SchemaError> {
    match type_expr {
        TypeExpr::Vector(element) => Ok(TypeExpr::Vector(Box::new(resolve_type(
            element, by_name, owner_path,
        )?))),
        TypeExpr::Scalar(_) => Ok(type_expr.clone()),
        TypeExpr::Named(named) => {
            let Some(target) = by_name.get(named.name()) else {
                return Err(SchemaError(format!(
                    "{owner_path}: 具名类型 '{}' 不存在",
                    named.name()
                )));
            };
            if matches!(target, Resource::Table(_)) {
                return Err(SchemaError(format!(
                    "{owner_path}: 字段类型不能直接引用 Table '{}'",
                    target.name()
                )));
            }
            let kind = match target {
                Resource::Record(_) => NamedKind::Record,
                Resource::Enum(_) => NamedKind::Enum,
                Resource::Table(_) => unreachable!(),
            };
            if let Some(expected) = named.expected_kind() {
                if expected != kind {
                    return Err(SchemaError(format!(
                        "{owner_path}: 期望 {}，但 '{}' 实际为 {}",
                        expected.as_str(),
                        named.name(),
                        kind.as_str()
                    )));
                }
            }
            Ok(TypeExpr::Named(named.resolve(kind)))
        }
    }
}

fn resolve_fields(
    fields: &[FieldDef],
    by_name: &HashMap<String, Resource>,
    owner_id: &str,
) -> Result<Vec<FieldDef>, SchemaError> {
    fields
        .iter()
        .map(|field| {
            let owner_path = format!("{owner_id}/{}", field.name);
            let resolved = resolve_type(&field.type_expr, by_name, &owner_path)?;
            if field.excel_columns.is_some() && !matches!(resolved, TypeExpr::Vector(_)) {
                return Err(SchemaError(format!(
                    "{owner_path}: excel_columns（展开组数）仅适用于 vector<T>（定长展开列），当前类型 {}",
                    field.type_text()
                )));
            }
            if let TypeExpr::Vector(element) = &resolved {
                if field.ref_.is_some() {
                    return Err(SchemaError(format!(
                        "{owner_path}: ref 字段不能声明 vector"
                    )));
                }
                if let TypeExpr::Named(named) = element.as_ref() {
                    if named.expected_kind() == Some(NamedKind::Record)
                        && field.excel_columns.is_none()
                    {
                        return Err(SchemaError(format!(
                            "{owner_path}: vector<Record> 必须配置 excel_columns 展开槽位"
                        )));
                    }
                }
            }
            Ok(replace_field_type(field, resolved))
        })
        .collect()
}
