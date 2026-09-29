//! 候选计算：基线 + commands + cursor → 候选资源与 candidateHash
//! （对应 Python `app/schema_workspace/candidate.py`）。

use std::collections::BTreeMap;

use crate::commands::DraftState;
use crate::graph::resource_topological_order;
use crate::hashing::{python_json_dumps, resource_to_data, sha256_hex};
use crate::indexes::validate_indexes;
use crate::name_validation::generated_name_conflicts;
use crate::repository::Resource;
use crate::schema::{FieldDef, QueryIndex};
use crate::types::{NamedKind, NamedRef, TypeExpr};

pub const CANDIDATE_FORMAT: &str = "workspace-candidate/1";

/// 候选校验问题（blocker 才会阻止保存）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CandidateIssue {
    pub message: String,
    /// 资源 ID 或规范字段路径
    pub location: String,
    pub kind: String,
}

impl CandidateIssue {
    pub fn blocker(message: impl Into<String>, location: impl Into<String>) -> Self {
        CandidateIssue {
            message: message.into(),
            location: location.into(),
            kind: "blocker".to_string(),
        }
    }

    pub fn render(&self) -> String {
        if self.location.is_empty() {
            self.message.clone()
        } else {
            format!("{}（{}）", self.message, self.location)
        }
    }
}

/// 把草稿索引并进 Table 资源（持久化/加载/导出走同一条数据通路）。
pub fn merge_indexes(
    resources: &[Resource],
    indexes: &BTreeMap<String, Vec<QueryIndex>>,
) -> Vec<Resource> {
    resources
        .iter()
        .map(|resource| match resource {
            Resource::Table(table) => {
                let mut merged = table.clone();
                merged.indexes = indexes
                    .get(&table.resource_id())
                    .cloned()
                    .unwrap_or_default();
                Resource::Table(merged)
            }
            other => other.clone(),
        })
        .collect()
}

/// 候选的确定性身份，用于乐观并发守卫。
///
/// 由规范持久化表示（资源按 ID 排序）计算：命令顺序与对象键序不影响结果，
/// 任何结构性变化必然改变它。
pub fn candidate_hash(
    resources: &[Resource],
    indexes: &BTreeMap<String, Vec<QueryIndex>>,
) -> String {
    let merged = merge_indexes(resources, indexes);
    let mut sorted = merged;
    sorted.sort_by_key(|r| r.resource_id());
    let payload = serde_json::json!({
        "format": CANDIDATE_FORMAT,
        "resources": sorted.iter().map(resource_to_data).collect::<Vec<_>>(),
    });
    sha256_hex(python_json_dumps(&payload).as_bytes())
}

fn resolve_named(expr: &TypeExpr, by_name: &BTreeMap<String, &Resource>) -> TypeExpr {
    match expr {
        TypeExpr::Named(named) => {
            if named.resolved() {
                return expr.clone();
            }
            let Some(target) = by_name.get(named.name()) else {
                return expr.clone();
            };
            let kind = match target {
                Resource::Record(_) => NamedKind::Record,
                _ => NamedKind::Enum,
            };
            TypeExpr::Named(named.resolve(kind))
        }
        TypeExpr::Vector(element) => TypeExpr::Vector(Box::new(resolve_named(element, by_name))),
        TypeExpr::Scalar(_) => expr.clone(),
    }
}

/// 用候选集合解析裸名引用（候选内部一致性校验用）。
pub fn resolve_candidate_resources(resources: &[Resource]) -> Vec<Resource> {
    let by_name: BTreeMap<String, &Resource> = resources
        .iter()
        .map(|r| (r.name().to_string(), r))
        .collect();
    resources
        .iter()
        .map(|resource| match resource {
            Resource::Table(table) => {
                let mut updated = table.clone();
                for field in &mut updated.fields {
                    field.type_expr = resolve_named(&field.type_expr, &by_name);
                }
                Resource::Table(updated)
            }
            Resource::Record(record) => {
                let mut updated = record.clone();
                for field in &mut updated.fields {
                    field.type_expr = resolve_named(&field.type_expr, &by_name);
                }
                Resource::Record(updated)
            }
            other => other.clone(),
        })
        .collect()
}

fn named_references_of(expr: &TypeExpr) -> Vec<&NamedRef> {
    match expr {
        TypeExpr::Named(named) => vec![named],
        TypeExpr::Vector(element) => named_references_of(element),
        TypeExpr::Scalar(_) => Vec::new(),
    }
}

/// 候选全量校验：名称冲突、生成符号、字段/资源不变量、具名引用、循环、索引。
pub fn validate_candidate(
    resources: &[Resource],
    indexes: &BTreeMap<String, Vec<QueryIndex>>,
) -> Vec<CandidateIssue> {
    let mut issues = Vec::new();

    let mut by_name: BTreeMap<String, &Resource> = BTreeMap::new();
    for resource in resources {
        if let Some(previous) = by_name.get(resource.name()) {
            issues.push(CandidateIssue::blocker(
                format!("资源名 '{}' 重复", resource.name()),
                format!("{} ↔ {}", previous.resource_id(), resource.resource_id()),
            ));
        }
        by_name.insert(resource.name().to_string(), resource);
    }

    let resolved_resources = resolve_candidate_resources(resources);

    for conflict in generated_name_conflicts(&resolved_resources) {
        issues.push(CandidateIssue::blocker(
            conflict.render(),
            conflict.locations.join(", "),
        ));
    }

    for resource in &resolved_resources {
        let owner = resource.resource_id();
        let fields: &[FieldDef] = match resource {
            Resource::Table(t) => &t.fields,
            Resource::Record(r) => &r.fields,
            Resource::Enum(_) => &[],
        };
        // 逐字段先验：一个坏字段不掩盖同资源其他问题
        for field in fields {
            if let Err(error) = field.validate() {
                issues.push(CandidateIssue::blocker(
                    error.0,
                    format!("{owner}/{}", field.name),
                ));
            }
        }
        if let Resource::Table(table) = resource {
            if let Some(primary) = table.fields.iter().find(|f| f.name == table.primary) {
                if primary.server_only {
                    issues.push(CandidateIssue::blocker(
                        format!(
                            "表 {}: 主键字段 '{}' 不能标记 server_only",
                            table.table, table.primary
                        ),
                        format!("{owner}/{}", table.primary),
                    ));
                }
            }
        }
        // 资源级不变量（草稿用纯函数绕过常规校验，候选必须重跑）。
        // 与 Python 一致：Enum 不在候选阶段重跑模型校验
        // （空 values 等问题在落盘/加载边界拒绝）。
        let resource_result = match resource {
            Resource::Table(t) => t.validate(),
            Resource::Record(r) => r.validate(),
            Resource::Enum(_) => Ok(()),
        };
        if let Err(error) = resource_result {
            issues.push(CandidateIssue::blocker(error.0, owner.clone()));
        }
        for field in fields {
            for reference in named_references_of(&field.type_expr) {
                let target = by_name.get(reference.name());
                match target {
                    None => issues.push(CandidateIssue::blocker(
                        format!("具名类型 '{}' 不存在", reference.name()),
                        format!("{owner}/{}", field.name),
                    )),
                    Some(Resource::Table(table)) => issues.push(CandidateIssue::blocker(
                        format!("字段类型不能直接引用 Table '{}'", table.table),
                        format!("{owner}/{}", field.name),
                    )),
                    Some(target) => {
                        if let Some(expected) = reference.expected_kind() {
                            let actual = match target {
                                Resource::Record(_) => NamedKind::Record,
                                _ => NamedKind::Enum,
                            };
                            if expected != actual {
                                issues.push(CandidateIssue::blocker(
                                    format!(
                                        "期望 {}，实际为 {}",
                                        expected.as_str(),
                                        actual.as_str()
                                    ),
                                    format!("{owner}/{}", field.name),
                                ));
                            }
                        }
                    }
                }
            }
        }
    }

    // 依赖环（基于解析后的资源图；内部自建 named + ref 图）
    if !resolved_resources.is_empty() {
        if let Err(error) = resource_topological_order(&resolved_resources) {
            issues.push(CandidateIssue::blocker(error.0, ""));
        }
    }

    // 每张表的索引校验
    for resource in resources {
        if let Resource::Table(table) = resource {
            let table_indexes = indexes
                .get(&table.resource_id())
                .cloned()
                .unwrap_or_default();
            if let Err(error) = validate_indexes(table, &table_indexes) {
                issues.push(CandidateIssue::blocker(error, table.resource_id()));
            }
        }
    }

    issues
}

/// 从草稿状态计算候选视图。
pub fn compute_candidate(state: &DraftState) -> CandidateView {
    let merged = merge_indexes(&state.resources, &state.indexes);
    let issues = validate_candidate(&merged, &state.indexes);
    CandidateView {
        hash: candidate_hash(&state.resources, &state.indexes),
        issues,
        resources: merged,
    }
}

/// 候选视图：哈希 + 问题 + 并进索引后的资源。
#[derive(Debug, Clone)]
pub struct CandidateView {
    pub hash: String,
    pub issues: Vec<CandidateIssue>,
    pub resources: Vec<Resource>,
}
