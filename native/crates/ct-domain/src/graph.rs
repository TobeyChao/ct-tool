//! 资源依赖图（`ct/schema/resource_graph.py`）：
//! 具名类型边、跨表 ref 边、拓扑序、反向引用、循环检测、删除守卫。

use std::collections::{BTreeMap, BTreeSet};

use crate::repository::Resource;
use crate::schema::{FieldDef, SchemaError, TableResource};
use crate::types::TypeExpr;

/// 一处引用。
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Reference {
    /// 持有方资源 id，如 `table:Item`。
    pub owner: String,
    /// 规范字段路径，如 `table:Item/Rewards`。
    pub field_path: String,
    /// "named" | "ref"
    pub kind: String,
}

/// 类型表达式里的具名引用（递归穿过 vector）。
pub fn named_references(expr: &TypeExpr) -> Vec<String> {
    match expr {
        TypeExpr::Named(named) => vec![named.resource_id().to_string()],
        TypeExpr::Vector(element) => named_references(element),
        TypeExpr::Scalar(_) => Vec::new(),
    }
}

/// 资源 id → 它引用的 record/enum id（排序去重）。
pub fn named_dependency_edges(resources: &[Resource]) -> BTreeMap<String, Vec<String>> {
    let mut graph = BTreeMap::new();
    for resource in resources {
        let fields: &[FieldDef] = match resource {
            Resource::Table(t) => &t.fields,
            Resource::Record(r) => &r.fields,
            Resource::Enum(_) => &[],
        };
        let mut deps = BTreeSet::new();
        for field in fields {
            for reference in named_references(&field.type_expr) {
                deps.insert(reference);
            }
        }
        graph.insert(resource.resource_id(), deps.into_iter().collect());
    }
    graph
}

/// 校验 ref 目标并返回目标表（`Target.Primary` 两段都检查）。
fn validated_ref_target<'a>(
    tables: &BTreeMap<String, &'a TableResource>,
    owner: &str,
    field: &FieldDef,
) -> Result<&'a TableResource, SchemaError> {
    let ref_text = field.ref_.as_deref().unwrap_or("");
    let (target_table, target_field) = ref_text.split_once('.').unwrap_or((ref_text, ""));
    let Some(target) = tables.get(&format!("table:{target_table}")).copied() else {
        return Err(SchemaError(format!(
            "{owner}/{}: 引用的表 '{target_table}' 不存在",
            field.name
        )));
    };
    if target_field != target.primary {
        return Err(SchemaError(format!(
            "{owner}/{}: ref 目标必须是目标表主键 '{}.{}'（当前 '{ref_text}'）",
            field.name, target_table, target.primary
        )));
    }
    Ok(target)
}

/// 表资源 id → 它 ref 的目标表 id（排序去重）。
pub fn cross_table_ref_edges(
    resources: &[Resource],
) -> Result<BTreeMap<String, Vec<String>>, SchemaError> {
    let tables: BTreeMap<String, &TableResource> = resources
        .iter()
        .filter_map(|r| match r {
            Resource::Table(t) => Some((t.resource_id(), t)),
            _ => None,
        })
        .collect();
    let mut edges = BTreeMap::new();
    for resource in resources {
        let Resource::Table(table) = resource else {
            continue;
        };
        let mut targets = BTreeSet::new();
        for field in &table.fields {
            if field.ref_.is_none() {
                continue;
            }
            targets
                .insert(validated_ref_target(&tables, &table.resource_id(), field)?.resource_id());
        }
        edges.insert(table.resource_id(), targets.into_iter().collect());
    }
    Ok(edges)
}

/// 资源 id → 引用它的所有位置（排序确定）。
pub fn reverse_references(resources: &[Resource]) -> BTreeMap<String, Vec<Reference>> {
    let mut references: BTreeMap<String, Vec<Reference>> = BTreeMap::new();
    for resource in resources {
        let owner = resource.resource_id();
        let fields: &[FieldDef] = match resource {
            Resource::Table(t) => &t.fields,
            Resource::Record(r) => &r.fields,
            Resource::Enum(_) => &[],
        };
        for field in fields {
            let field_path = format!("{owner}/{}", field.name);
            for reference in named_references(&field.type_expr) {
                references.entry(reference).or_default().push(Reference {
                    owner: owner.clone(),
                    field_path: field_path.clone(),
                    kind: "named".to_string(),
                });
            }
        }
        if let Resource::Table(table) = resource {
            for field in &table.fields {
                let Some(ref_text) = &field.ref_ else {
                    continue;
                };
                let (target_table, target_field) =
                    ref_text.split_once('.').unwrap_or((ref_text.as_str(), ""));
                let field_path = format!("{owner}/{}", field.name);
                references
                    .entry(format!("table:{target_table}"))
                    .or_default()
                    .push(Reference {
                        owner: owner.clone(),
                        field_path: field_path.clone(),
                        kind: "ref".to_string(),
                    });
                if !target_field.is_empty() {
                    references
                        .entry(format!("table:{target_table}/{target_field}"))
                        .or_default()
                        .push(Reference {
                            owner: owner.clone(),
                            field_path,
                            kind: "ref".to_string(),
                        });
                }
            }
        }
    }
    for refs in references.values_mut() {
        refs.sort();
    }
    references
}

/// 确定性 Kahn 拓扑序；环时报出环路径。
fn topological_order(
    graph: &BTreeMap<String, Vec<String>>,
    nodes: &[String],
) -> Result<Vec<String>, SchemaError> {
    let mut in_degree: BTreeMap<&str, usize> = nodes.iter().map(|n| (n.as_str(), 0)).collect();
    let mut dependents: BTreeMap<&str, Vec<&str>> =
        nodes.iter().map(|n| (n.as_str(), Vec::new())).collect();
    for node in nodes {
        for dependency in graph.get(node).cloned().unwrap_or_default() {
            if !in_degree.contains_key(dependency.as_str()) {
                return Err(SchemaError(format!(
                    "依赖目标 '{dependency}' 不在资源图中（{node}）"
                )));
            }
            *in_degree.get_mut(node.as_str()).unwrap() += 1;
            dependents
                .get_mut(dependency.as_str())
                .unwrap()
                .push(node.as_str());
        }
    }

    let mut ready: Vec<&str> = nodes
        .iter()
        .filter(|n| in_degree[n.as_str()] == 0)
        .map(|n| n.as_str())
        .collect();
    ready.sort();
    let mut result: Vec<String> = Vec::new();
    while let Some(node) = (!ready.is_empty()).then(|| ready.remove(0)) {
        result.push(node.to_string());
        let mut promoted = Vec::new();
        for dependent in &dependents[node] {
            let entry = in_degree.get_mut(dependent).unwrap();
            *entry -= 1;
            if *entry == 0 {
                promoted.push(*dependent);
            }
        }
        ready.extend(promoted);
        ready.sort();
    }

    if result.len() != nodes.len() {
        let remaining: Vec<&str> = nodes
            .iter()
            .map(|n| n.as_str())
            .filter(|n| !result.contains(&n.to_string()))
            .collect();
        return Err(SchemaError(format!(
            "检测到循环依赖: {}",
            remaining.join(" → ")
        )));
    }
    Ok(result)
}

/// 发射顺序：具名资源先于引用它们的 Table；Table 之间按 ref 拓扑。
pub fn resource_topological_order(resources: &[Resource]) -> Result<Vec<String>, SchemaError> {
    let named_graph = named_dependency_edges(resources);
    let nodes: Vec<String> = resources.iter().map(|r| r.resource_id()).collect();
    let named_order = topological_order(&named_graph, &nodes)?;

    let ref_graph = cross_table_ref_edges(resources)?;
    let table_nodes: Vec<String> = resources
        .iter()
        .filter_map(|r| match r {
            Resource::Table(t) => Some(t.resource_id()),
            _ => None,
        })
        .collect();
    let table_order = topological_order(&ref_graph, &table_nodes)?;

    let named_ids: BTreeSet<String> = resources
        .iter()
        .filter(|r| !matches!(r, Resource::Table(_)))
        .map(|r| r.resource_id())
        .collect();
    let ordered_named: Vec<String> = named_order
        .into_iter()
        .filter(|n| named_ids.contains(n))
        .collect();
    Ok([ordered_named, table_order].concat())
}

/// 删除守卫：目标仍被引用时给出全部引用位置。
pub fn require_deletable(
    target: &str,
    reverse: &BTreeMap<String, Vec<Reference>>,
) -> Result<(), SchemaError> {
    if let Some(references) = reverse.get(target) {
        if !references.is_empty() {
            let use_sites: Vec<&str> = references.iter().map(|r| r.field_path.as_str()).collect();
            return Err(SchemaError(format!(
                "无法删除 {target}（仍被引用）: {}",
                use_sites.join(", ")
            )));
        }
    }
    Ok(())
}
