//! schema.candidate / schema.save：候选、净差异与双守卫保存。

use std::path::Path;

use ct_app::schema::{save_workspace, SchemaSession};
use ct_domain::commands::Command;
use ct_protocol::dto::schema::{
    FieldRef, NetDiff, ResourceRef, SchemaCandidateResult, SchemaCommand, SchemaSaveParams,
    SchemaSaveResult,
};
use ct_protocol::error::ErrorCode;
use ct_protocol::event::Issue;
use serde_json::Value;

use crate::dispatcher::{Emitter, Failure, HandlerResult};

fn parse_commands(commands: &[SchemaCommand]) -> Vec<Command> {
    commands
        .iter()
        .map(|c| Command {
            kind: c.kind.clone(),
            payload: c.payload.clone(),
        })
        .collect()
}

fn parse_cursor(cursor: &str) -> usize {
    cursor.trim().parse::<usize>().unwrap_or(usize::MAX)
}

fn issue_of(message: impl Into<String>, location: impl Into<String>) -> Issue {
    let location = location.into();
    Issue {
        code: "schema-issue".to_string(),
        message: message.into(),
        resource: (!location.is_empty()).then_some(location.clone()),
        field_path: None,
        excel_row: None,
        file: None,
    }
}

pub fn candidate(root: &Path, params: &Value) -> HandlerResult {
    let parsed: ct_protocol::dto::schema::SchemaCandidateParams =
        serde_json::from_value(params.clone()).map_err(|e| {
            Failure::new(
                ErrorCode::Internal,
                format!("schema.candidate 参数非法: {e}"),
            )
        })?;
    let session =
        SchemaSession::open(root).map_err(|e| Failure::new(ErrorCode::Internal, e.message))?;
    let commands = parse_commands(&parsed.commands);
    let cursor = parse_cursor(&parsed.cursor);
    let view = session.candidate(&commands, cursor).map_err(|e| {
        Failure::with_issues(
            e.message.clone(),
            if e.details.issues.is_empty() {
                vec![issue_of(&e.message, "")]
            } else {
                e.details
                    .issues
                    .iter()
                    .map(|i| issue_of(&i.message, &i.location))
                    .collect()
            },
        )
    })?;
    let mut problems: Vec<Issue> = view
        .issues
        .iter()
        .map(|i| issue_of(&i.message, &i.location))
        .collect();
    // 客户端基线落后于磁盘：显式提示，避免用过期草稿继续编辑
    if session.revision.revision != parsed.schema_revision {
        problems.push(issue_of(
            "草稿基线已过期：工作区 schema 源文件已被外部修改，请重载后再保存",
            "schemaRevision",
        ));
    }
    let result = SchemaCandidateResult {
        candidate_hash: view.hash,
        draft_generation: parsed.draft_generation,
        net_diff: net_diff_of(&view.net_diff),
        problems,
    };
    serde_json::to_value(result).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}

fn net_diff_of(diff: &ct_domain::netdiff::NetDiff) -> NetDiff {
    let mut out = NetDiff::default();
    for change in &diff.changes {
        let reference = ResourceRef {
            kind: change.kind.clone(),
            name: change.name.clone(),
            change: Some(change.change.clone()),
            old_name: change.old_name.clone().filter(|old| *old != change.name),
            fields: change
                .fields
                .iter()
                .map(|field| FieldRef {
                    name: field.name.clone(),
                    change: field.change.clone(),
                    old_name: field.old_name.clone().filter(|old| *old != field.name),
                    details: field.details.clone(),
                })
                .collect(),
        };
        match change.change.as_str() {
            ct_domain::netdiff::ADDED => out.added.push(reference),
            ct_domain::netdiff::REMOVED => out.removed.push(reference),
            _ => out.changed.push(reference),
        }
    }
    out
}

pub fn save(root: &Path, params: &Value, emitter: &Emitter) -> HandlerResult {
    let parsed: SchemaSaveParams = serde_json::from_value(params.clone())
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("schema.save 参数非法: {e}")))?;
    // 保存命令由客户端随请求重放（草稿日志的权威在内核）
    let commands_value = params
        .get("commands")
        .cloned()
        .unwrap_or(Value::Array(vec![]));
    let commands: Vec<SchemaCommand> = serde_json::from_value(commands_value)
        .map_err(|e| Failure::new(ErrorCode::Internal, format!("commands 非法: {e}")))?;
    let cursor = params
        .get("cursor")
        .and_then(|v| v.as_str())
        .map(parse_cursor)
        .unwrap_or(usize::MAX);
    let commands = parse_commands(&commands);
    let outcome = save_workspace(
        root,
        &parsed.schema_revision,
        &parsed.candidate_hash,
        &commands,
        cursor,
    )
    .map_err(|rejection| {
        let code = match rejection.kind.as_str() {
            "busy" => ErrorCode::Busy,
            "recovery" => ErrorCode::RecoveryNeeded,
            "schema-revision" | "candidate-hash" => ErrorCode::Busy,
            _ => ErrorCode::Internal,
        };
        Failure {
            code,
            message: rejection.message.clone(),
            issues: {
                let mapped: Vec<Issue> = rejection
                    .details
                    .issues
                    .iter()
                    .map(|i| issue_of(&i.message, &i.location))
                    .collect();
                // 命令级拒绝只有文本时补一条明细，客户端仍可跳转/展示，无需解析日志
                if mapped.is_empty() {
                    vec![issue_of(&rejection.message, rejection.kind.as_str())]
                } else {
                    mapped
                }
            },
        }
    })?;
    let (result, recovery) = outcome;
    if let Some(note) = &recovery {
        emitter.log("schema", &format!("[发布恢复] {note}"));
    }
    emitter.log(
        "schema",
        &format!(
            "YAML 保存完成：写入 {}，删除 {}",
            result.written.len(),
            result.deleted.len()
        ),
    );
    let payload = SchemaSaveResult {
        schema_revision: result.revision.revision,
    };
    serde_json::to_value(payload).map_err(|e| Failure::new(ErrorCode::Internal, e.to_string()))
}

#[cfg(test)]
mod tests {
    use ct_domain::netdiff::{FieldDiff, NetDiff, ResourceDiff, MODIFIED, RENAMED};
    use ct_protocol::dto::schema::NetDiff as NetDto;

    use super::net_diff_of;

    /// 净差异必须原样透传改名身份与 ordinal/wire 风险明细：
    /// 界面靠它区分「改名」与「删除+新增」，不能自己猜。
    #[test]
    fn net_diff_payload_keeps_rename_details() {
        let domain = NetDiff {
            changes: vec![
                ResourceDiff {
                    kind: "enum".to_string(),
                    name: "Quality".to_string(),
                    change: MODIFIED.to_string(),
                    old_name: None,
                    fields: vec![FieldDiff {
                        name: "Legendary".to_string(),
                        change: RENAMED.to_string(),
                        old_name: Some("Mythic".to_string()),
                        details: vec!["ordinal 1 → 3 · wire 风险".to_string()],
                    }],
                },
                ResourceDiff {
                    kind: "table".to_string(),
                    name: "Item".to_string(),
                    change: RENAMED.to_string(),
                    old_name: Some("Goods".to_string()),
                    fields: vec![],
                },
            ],
        };
        let dto: NetDto =
            serde_json::from_value(serde_json::to_value(net_diff_of(&domain)).unwrap()).unwrap();
        assert_eq!(dto.changed.len(), 2, "{dto:?}");
        let enum_ref = &dto.changed[0];
        assert_eq!(enum_ref.change.as_deref(), Some(MODIFIED));
        assert_eq!(enum_ref.fields.len(), 1, "{enum_ref:?}");
        assert_eq!(enum_ref.fields[0].old_name.as_deref(), Some("Mythic"));
        assert_eq!(
            enum_ref.fields[0].details,
            vec!["ordinal 1 → 3 · wire 风险".to_string()]
        );
        assert_eq!(
            enum_ref.fields[0].change, RENAMED,
            "枚举成员改名不能被压成修改"
        );
        // 资源级改名：旧名随响应回来，界面才能显示 A → B
        assert_eq!(dto.changed[1].old_name.as_deref(), Some("Goods"));
    }
}
