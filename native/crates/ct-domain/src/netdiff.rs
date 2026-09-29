//! 净差异：候选相对基线的最小变更集（对应 Python `app/schema_workspace/netdiff.py`）。
//!
//! 草稿保留诚实的命令历史（含已撤销的点击），状态栏与保存摘要只描述净效果：
//! 资源按规范身份（kind:Name）匹配；显式改名命令连接新旧身份，
//! `A→B→C` 报告一次改名，`A→B→A` 报告无变化；删除+新增不猜成改名。

use std::collections::BTreeMap;

use crate::commands::{apply_command, rename_field, rename_resource, Command, DraftState};
use crate::hashing::{field_to_data, resource_to_data};
use crate::repository::Resource;

pub const NET_DIFF_FORMAT: &str = "net-diff/1";

pub const ADDED: &str = "added";
pub const REMOVED: &str = "removed";
pub const MODIFIED: &str = "modified";
pub const RENAMED: &str = "renamed";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldDiff {
    pub name: String,
    pub change: String,
    pub old_name: Option<String>,
    pub details: Vec<String>,
}

impl FieldDiff {
    pub fn to_payload(&self) -> serde_json::Value {
        let mut payload = serde_json::json!({"name": self.name, "change": self.change});
        if let Some(old) = &self.old_name {
            if *old != self.name {
                payload["oldName"] = old.clone().into();
            }
        }
        if !self.details.is_empty() {
            payload["details"] = self.details.clone().into();
        }
        payload
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceDiff {
    pub kind: String,
    pub name: String,
    pub change: String,
    pub old_name: Option<String>,
    pub fields: Vec<FieldDiff>,
}

impl ResourceDiff {
    pub fn resource_id(&self) -> String {
        format!("{}:{}", self.kind, self.name)
    }

    pub fn to_payload(&self) -> serde_json::Value {
        let mut payload = serde_json::json!({
            "resourceId": self.resource_id(),
            "kind": self.kind,
            "name": self.name,
            "change": self.change,
        });
        if let Some(old) = &self.old_name {
            if *old != self.name {
                payload["oldName"] = old.clone().into();
            }
        }
        if !self.fields.is_empty() {
            payload["fields"] = self.fields.iter().map(|f| f.to_payload()).collect();
        }
        payload
    }

    pub fn render(&self) -> String {
        let label = match self.change.as_str() {
            ADDED => "新增",
            REMOVED => "删除",
            MODIFIED => "修改",
            RENAMED => "重命名",
            other => other,
        };
        if self.change == RENAMED {
            if let Some(old) = &self.old_name {
                return format!("{} {} → {}", self.kind, old, self.name);
            }
        }
        format!("{label} {} {}", self.kind, self.name)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct NetDiff {
    pub changes: Vec<ResourceDiff>,
}

impl NetDiff {
    pub fn changed_resources(&self) -> usize {
        self.changes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.changes.is_empty()
    }

    pub fn to_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "format": NET_DIFF_FORMAT,
            "changedResources": self.changed_resources(),
            "isNoOp": self.is_empty(),
            "resources": self.changes.iter().map(|c| c.to_payload()).collect::<Vec<_>>(),
        })
    }

    pub fn summary(&self) -> String {
        self.changes
            .iter()
            .map(|c| c.render())
            .collect::<Vec<_>>()
            .join("；")
    }
}

fn resource_paths(state: &DraftState) -> Vec<String> {
    let mut paths = Vec::new();
    for resource in &state.resources {
        let owner = resource.resource_id();
        paths.push(owner.clone());
        match resource {
            Resource::Table(t) => {
                paths.extend(t.fields.iter().map(|f| format!("{owner}/{}", f.name)))
            }
            Resource::Record(r) => {
                paths.extend(r.fields.iter().map(|f| format!("{owner}/{}", f.name)))
            }
            Resource::Enum(e) => {
                paths.extend(e.values.iter().map(|v| format!("{owner}/{}", v.name)))
            }
        }
    }
    paths
}

/// 基线规范路径 → 当前路径（仅显式改名命令连接身份，不猜名字）。
pub fn rename_identity(
    base: &DraftState,
    commands: &[Command],
    cursor: Option<usize>,
) -> BTreeMap<String, String> {
    let command_list: &[Command] = match cursor {
        Some(c) => &commands[..c.min(commands.len())],
        None => commands,
    };

    let mut forward: BTreeMap<String, String> = resource_paths(base)
        .into_iter()
        .map(|path| (path.clone(), path))
        .collect();
    let mut state = base.clone();
    for command in command_list {
        let mapping: BTreeMap<String, String> = match command.kind.as_str() {
            "rename_resource" => command
                .payload
                .get("old")
                .and_then(|v| v.as_str())
                .zip(command.payload.get("new").and_then(|v| v.as_str()))
                .and_then(|(old, new)| rename_resource(&state.resources, old, new).ok())
                .map(|result| result.mapping)
                .unwrap_or_default(),
            "rename_enum_item" => {
                match (
                    command.payload.get("name").and_then(|v| v.as_str()),
                    command.payload.get("oldName").and_then(|v| v.as_str()),
                    command.payload.get("newName").and_then(|v| v.as_str()),
                ) {
                    (Some(owner), Some(old), Some(new)) => {
                        [(format!("{owner}/{old}"), format!("{owner}/{new}"))]
                            .into_iter()
                            .collect()
                    }
                    _ => BTreeMap::new(),
                }
            }
            "rename_field" => match (
                command.payload.get("owner").and_then(|v| v.as_str()),
                command.payload.get("old").and_then(|v| v.as_str()),
                command.payload.get("new").and_then(|v| v.as_str()),
            ) {
                (Some(owner), Some(old), Some(new)) => {
                    rename_field(&state.resources, owner, old, new)
                        .map(|result| result.mapping)
                        .unwrap_or_default()
                }
                _ => BTreeMap::new(),
            },
            _ => BTreeMap::new(),
        };
        if !mapping.is_empty() {
            for (old, new) in &mapping {
                for current in forward.values_mut() {
                    if current == old || current.starts_with(&format!("{old}/")) {
                        *current = format!("{new}{}", &current[old.len()..]);
                    }
                }
            }
        }
        // 历史是 best effort：坏尾巴不阻断差异，结构比较仍是权威
        match apply_command(&state, command) {
            Ok(next) => state = next,
            Err(_) => break,
        }
    }
    forward
        .into_iter()
        .filter(|(origin, current)| origin != current)
        .collect()
}

fn normalized_resource(resource: &Resource) -> serde_json::Value {
    let mut data = resource_to_data(resource);
    if let Some(map) = data.as_object_mut() {
        map.remove("name");
        map.remove("table");
    }
    data
}

fn field_payload(field: &crate::schema::FieldDef) -> serde_json::Value {
    let mut data = field_to_data(field);
    if let Some(map) = data.as_object_mut() {
        map.remove("name");
    }
    data
}

fn field_details(before: &crate::schema::FieldDef, after: &crate::schema::FieldDef) -> Vec<String> {
    let old = field_payload(before);
    let new = field_payload(after);
    let mut keys: Vec<String> = Vec::new();
    if let (Some(old_map), Some(new_map)) = (old.as_object(), new.as_object()) {
        let all: std::collections::BTreeSet<&String> =
            old_map.keys().chain(new_map.keys()).collect();
        for key in all {
            if old_map.get(key) != new_map.get(key) {
                keys.push(key.clone());
            }
        }
    }
    keys
}

fn kind_of(resource: &Resource) -> String {
    resource
        .resource_id()
        .split(':')
        .next()
        .unwrap_or("")
        .to_string()
}

fn field_diffs(
    owner_after: &str,
    before: &Resource,
    after: &Resource,
    identity: &BTreeMap<String, String>,
) -> Vec<FieldDiff> {
    if let (Resource::Enum(before_enum), Resource::Enum(after_enum)) = (before, after) {
        let old_values: BTreeMap<&str, (usize, &crate::schema::EnumItem)> = before_enum
            .values
            .iter()
            .enumerate()
            .map(|(i, item)| (item.name.as_str(), (i, item)))
            .collect();
        let new_values: BTreeMap<&str, (usize, &crate::schema::EnumItem)> = after_enum
            .values
            .iter()
            .enumerate()
            .map(|(i, item)| (item.name.as_str(), (i, item)))
            .collect();
        let mut result = Vec::new();
        let mut matched = std::collections::BTreeSet::new();
        // 保持基线顺序（Python 为 dict 插入序）
        for (name, (old_ordinal, item)) in &before_enum
            .values
            .iter()
            .enumerate()
            .map(|(i, item)| (item.name.clone(), (i, item)))
            .collect::<Vec<_>>()
        {
            let path = identity
                .get(&format!("{}/{name}", before_enum.resource_id()))
                .cloned()
                .unwrap_or_else(|| format!("{owner_after}/{name}"));
            let final_name = path.rsplit('/').next().unwrap_or(name).to_string();
            let Some((ordinal, new_item)) = new_values.get(final_name.as_str()) else {
                result.push(FieldDiff {
                    name: name.clone(),
                    change: REMOVED.to_string(),
                    old_name: None,
                    details: vec![format!("ordinal {old_ordinal} → 删除 · wire 风险")],
                });
                continue;
            };
            let _ = item;
            matched.insert(final_name.clone());
            let mut details = Vec::new();
            if *ordinal != *old_ordinal {
                details.push(format!("ordinal {old_ordinal} → {ordinal} · wire 风险"));
            } else if *name != final_name {
                details.push(format!("ordinal {ordinal} 不变 · API 名称变化"));
            }
            let old_item = &before_enum.values[*old_ordinal];
            if old_item.comment != new_item.comment {
                details.push("comment".to_string());
            }
            if *name != final_name || !details.is_empty() {
                result.push(FieldDiff {
                    name: final_name.clone(),
                    change: if *name != final_name {
                        RENAMED.to_string()
                    } else {
                        MODIFIED.to_string()
                    },
                    old_name: Some(name.clone()),
                    details,
                });
            }
        }
        for (ordinal, item) in after_enum.values.iter().enumerate() {
            if !matched.contains(&item.name) {
                result.push(FieldDiff {
                    name: item.name.clone(),
                    change: ADDED.to_string(),
                    old_name: None,
                    details: vec![format!("新增 ordinal {ordinal}")],
                });
            }
        }
        let _ = old_values;
        return result;
    }

    let before_fields: Vec<&crate::schema::FieldDef> = match before {
        Resource::Table(t) => t.fields.iter().collect(),
        Resource::Record(r) => r.fields.iter().collect(),
        Resource::Enum(_) => Vec::new(),
    };
    let after_fields: Vec<&crate::schema::FieldDef> = match after {
        Resource::Table(t) => t.fields.iter().collect(),
        Resource::Record(r) => r.fields.iter().collect(),
        Resource::Enum(_) => Vec::new(),
    };
    let after_by_name: BTreeMap<&str, &crate::schema::FieldDef> =
        after_fields.iter().map(|f| (f.name.as_str(), *f)).collect();
    let before_names: std::collections::BTreeSet<&str> =
        before_fields.iter().map(|f| f.name.as_str()).collect();
    let before_owner = before.resource_id();

    let mut diffs = Vec::new();
    let mut matched: std::collections::BTreeSet<&str> = std::collections::BTreeSet::new();
    for field in &before_fields {
        let default_path = format!("{before_owner}/{}", field.name);
        let target_path = identity.get(&default_path).cloned().unwrap_or(default_path);
        let (target_owner, target_name) = target_path
            .rsplit_once('/')
            .unwrap_or(("", target_path.as_str()));
        let target = if target_owner == owner_after {
            after_by_name.get(target_name).copied()
        } else {
            None
        };
        let Some(target) = target else {
            diffs.push(FieldDiff {
                name: field.name.clone(),
                change: REMOVED.to_string(),
                old_name: None,
                details: Vec::new(),
            });
            continue;
        };
        matched.insert(target.name.as_str());
        if target.name != field.name {
            diffs.push(FieldDiff {
                name: target.name.clone(),
                change: RENAMED.to_string(),
                old_name: Some(field.name.clone()),
                details: field_details(field, target),
            });
            continue;
        }
        let details = field_details(field, target);
        if !details.is_empty() {
            diffs.push(FieldDiff {
                name: field.name.clone(),
                change: MODIFIED.to_string(),
                old_name: None,
                details,
            });
        }
    }
    for field in &after_fields {
        if !matched.contains(field.name.as_str()) && !before_names.contains(field.name.as_str()) {
            diffs.push(FieldDiff {
                name: field.name.clone(),
                change: ADDED.to_string(),
                old_name: None,
                details: Vec::new(),
            });
        }
    }
    let order: BTreeMap<&str, usize> = after_fields
        .iter()
        .enumerate()
        .map(|(i, f)| (f.name.as_str(), i))
        .collect();
    diffs.sort_by(|a, b| {
        (
            a.change == ADDED,
            order.get(a.name.as_str()).copied().unwrap_or(usize::MAX),
            &a.name,
        )
            .cmp(&(
                b.change == ADDED,
                order.get(b.name.as_str()).copied().unwrap_or(usize::MAX),
                &b.name,
            ))
    });
    diffs
}

/// 基线 → 候选的完整有序净差异。
pub fn compute_net_diff(
    base: &DraftState,
    candidate: &DraftState,
    commands: &[Command],
    cursor: Option<usize>,
) -> NetDiff {
    let identity = rename_identity(base, commands, cursor);
    let base_resources: BTreeMap<String, &Resource> = base
        .resources
        .iter()
        .map(|r| (r.resource_id(), r))
        .collect();
    let candidate_resources: BTreeMap<String, &Resource> = candidate
        .resources
        .iter()
        .map(|r| (r.resource_id(), r))
        .collect();

    let mut changes = Vec::new();
    let mut claimed = std::collections::BTreeSet::new();

    for (base_id, before) in &base_resources {
        let final_id = identity
            .get(base_id)
            .cloned()
            .unwrap_or_else(|| base_id.clone());
        let Some(after) = candidate_resources.get(&final_id) else {
            changes.push(ResourceDiff {
                kind: kind_of(before),
                name: before.name().to_string(),
                change: REMOVED.to_string(),
                old_name: None,
                fields: Vec::new(),
            });
            continue;
        };
        claimed.insert(final_id.clone());
        let fields = field_diffs(&final_id, before, after, &identity);
        if final_id != *base_id {
            changes.push(ResourceDiff {
                kind: kind_of(after),
                name: after.name().to_string(),
                change: RENAMED.to_string(),
                old_name: Some(before.name().to_string()),
                fields,
            });
            continue;
        }
        if normalized_resource(before) != normalized_resource(after) {
            changes.push(ResourceDiff {
                kind: kind_of(after),
                name: after.name().to_string(),
                change: MODIFIED.to_string(),
                old_name: None,
                fields,
            });
        }
    }

    for (candidate_id, after) in &candidate_resources {
        if claimed.contains(candidate_id) {
            continue;
        }
        changes.push(ResourceDiff {
            kind: kind_of(after),
            name: after.name().to_string(),
            change: ADDED.to_string(),
            old_name: None,
            fields: Vec::new(),
        });
    }

    changes.sort_by(|a, b| (a.resource_id(), &a.change).cmp(&(b.resource_id(), &b.change)));
    NetDiff { changes }
}
