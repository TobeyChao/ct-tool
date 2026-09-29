//! Browser-facing application views. HTTP owns only transport and task presentation.
use crate::{
    schema::{SaveRejection, SchemaSession},
    workspace::Workspace,
};
use ct_domain::{commands::Command, repository::Resource};
use serde_json::{json, Value};
use std::{collections::BTreeMap, path::Path};

#[derive(Debug)]
pub struct PanelError {
    pub status: u16,
    pub payload: Value,
}
impl PanelError {
    pub fn new(status: u16, message: impl ToString) -> Self {
        Self {
            status,
            payload: json!({"ok":false,"error":message.to_string()}),
        }
    }
    fn malformed_command(location: String, message: impl ToString) -> Self {
        let message = message.to_string();
        let mut error = Self::new(400, &message);
        error.payload["issues"] = json!([{"kind":"blocker","location":location,"message":message}]);
        error
    }
}
impl From<SaveRejection> for PanelError {
    fn from(e: SaveRejection) -> Self {
        let status = match e.kind.as_str() {
            "busy" | "recovery" | "schema-revision" | "candidate-hash" | "target" => 409,
            "publication" => 500,
            _ => 400,
        };
        let mut result = Self::new(status, &e.message);
        result.payload["issues"] = e
            .details
            .issues
            .iter()
            .map(|i| json!({"message":i.message,"location":i.location,"kind":i.kind}))
            .collect();
        if e.kind == "busy" {
            result.payload["busy"] = true.into();
        } else if status == 409 {
            result.payload["conflict"] = json!({"kind":e.kind,"schemaRevision":e.details.revision.map(|r|r.to_payload()),"changedMembers":e.details.changed_members});
        }
        result
    }
}
impl From<ct_domain::schema::SchemaError> for PanelError {
    fn from(e: ct_domain::schema::SchemaError) -> Self {
        Self::new(400, e)
    }
}
impl From<ct_storage::workspace::TransactionError> for PanelError {
    fn from(e: ct_storage::workspace::TransactionError) -> Self {
        let busy = matches!(e, ct_storage::workspace::TransactionError::Busy(_));
        let mut error = Self::new(409, e);
        error.payload["busy"] = busy.into();
        error
    }
}
pub type Result<T> = std::result::Result<T, PanelError>;

fn readable(root: &Path) -> Result<ct_storage::lock::WorkspaceLock> {
    let lock = ct_storage::lock::WorkspaceLock::acquire(root).map_err(|e| {
        let mut e = PanelError::new(409, e);
        e.payload["busy"] = true.into();
        e
    })?;
    if let Some(note) = crate::workspace::recovery_needed(root) {
        let mut e = PanelError::new(409, note);
        e.payload["conflict"] = json!({"kind":"recovery"});
        return Err(e);
    }
    Ok(lock)
}
pub fn resource_payload(r: &Resource) -> Value {
    fn omit_null(value: &mut Value) {
        match value {
            Value::Object(map) => {
                map.retain(|_, value| !value.is_null());
                for value in map.values_mut() {
                    omit_null(value);
                }
            }
            Value::Array(items) => {
                for item in items {
                    omit_null(item);
                }
            }
            _ => {}
        }
    }
    // Browser DTOs include explicit defaults like i18n:false and uniform:true.
    // The sparse resource_to_data representation remains reserved for hashes/YAML.
    let mut data = match r {
        Resource::Table(table) => {
            let mut data = serde_json::to_value(table).expect("table serialization");
            data["indexes"] = json!(table
                .indexes
                .iter()
                .map(|_| json!({"kind":"codename"}))
                .collect::<Vec<_>>());
            data
        }
        Resource::Record(record) => serde_json::to_value(record).expect("record serialization"),
        Resource::Enum(enum_) => serde_json::to_value(enum_).expect("enum serialization"),
    };
    omit_null(&mut data);
    data["resourceId"] = r.resource_id().into();
    data["kind"] = r.kind().into();
    data["name"] = r.name().into();
    data
}
fn snapshot_of(s: &SchemaSession) -> Value {
    let reverse: BTreeMap<_, _> = ct_domain::graph::reverse_references(&s.resources)
        .into_iter()
        .map(|(id, refs)| {
            (
                id,
                refs.into_iter()
                    .map(|r| json!({"owner":r.owner,"field":r.field_path,"kind":r.kind}))
                    .collect::<Vec<_>>(),
            )
        })
        .collect();
    json!({"revision":s.revision.revision,"schemaRevision":s.revision.revision,"resources":s.resources.iter().map(resource_payload).collect::<Vec<_>>(),"reverseRefs":reverse,"changed":[]})
}
pub fn snapshot(root: &Path) -> Result<Value> {
    let _lock = readable(root)?;
    let session = SchemaSession::open(root)?;
    let mut value = snapshot_of(&session);
    value["revision"] = crate::snapshot::revision(&session)
        .map_err(|e| PanelError::new(400, e))?
        .into();
    Ok(value)
}
pub fn overview(root: &Path) -> Result<Value> {
    let _lock = readable(root)?;
    let ws = Workspace::open(root)?;
    let report = crate::status::canonical_status(&ws);
    Ok(
        json!({"root":root,"config":{"primary_lang":ws.config.primary_lang,"secondary_langs":ws.config.secondary_langs,"schema_format":"yaml","deploy":{"enabled":ws.config.deploy.enabled,"unity_project":ws.config.deploy.unity_project,"targets":[]}},"status":{"missing":report.missing,"changed":report.changed,"drifted":report.drifted}}),
    )
}
fn commands(data: &Value) -> Result<(Vec<Command>, usize)> {
    let items = data
        .get("commands")
        .and_then(Value::as_array)
        .ok_or_else(|| PanelError::malformed_command("commands".into(), "commands 必须是数组"))?;
    let cmds = items
        .iter()
        .enumerate()
        .map(|(i, c)| {
            if !c.is_object() {
                return Err(PanelError::malformed_command(
                    format!("commands[{i}]"),
                    "命令必须是对象",
                ));
            }
            let kind = c.get("type").and_then(Value::as_str).ok_or_else(|| {
                PanelError::malformed_command(format!("commands[{i}]"), "命令缺少 type")
            })?;
            Ok(Command {
                kind: kind.into(),
                payload: c.get("payload").cloned().unwrap_or(json!({})),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let cursor = match data.get("cursor") {
        None => cmds.len(),
        Some(v) => v
            .as_u64()
            .and_then(|v| usize::try_from(v).ok())
            .filter(|v| *v <= cmds.len())
            .ok_or_else(|| PanelError::malformed_command("cursor".into(), "cursor 超出命令历史"))?,
    };
    Ok((cmds, cursor))
}
fn required<'a>(data: &'a Value, key: &str) -> Result<&'a str> {
    data.get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| PanelError::new(400, format!("缺少 {key}")))
}
pub fn candidate(root: &Path, data: &Value, validate: bool) -> Result<Value> {
    let _lock = readable(root)?;
    let s = SchemaSession::open(root)?;
    let expected = required(data, "schemaRevision")?;
    if expected != s.revision.revision {
        let mut e = PanelError::new(409, "Schema 基线已变化，草稿保留；请核对后重新加载。");
        e.payload["conflict"] =
            json!({"kind":"schema-revision","schemaRevision":s.revision.to_payload()});
        return Err(e);
    }
    let attempt = commands(data)
        .and_then(|(cmds, cursor)| s.candidate(&cmds, cursor).map_err(PanelError::from));
    let view = match attempt {
        Ok(view) => view,
        Err(error) if validate && error.status == 400 => {
            let issues = error.payload.get("issues").filter(|v|v.as_array().is_some_and(|a|!a.is_empty())).cloned()
                .unwrap_or_else(|| json!([{"kind":"blocker","location":"commands","message":error.payload["error"]}]));
            return Ok(
                json!({"valid":false,"issues":issues,"netDiff":null,"schemaRevision":s.revision.to_payload(),"draftGeneration":data.get("draftGeneration")}),
            );
        }
        Err(error) => return Err(error),
    };
    let mut result = json!({"resources":view.resources.iter().map(resource_payload).collect::<Vec<_>>(),"issues":view.issues.iter().map(|i|json!({"message":i.message,"location":i.location,"kind":i.kind})).collect::<Vec<_>>(),"netDiff":view.net_diff.to_payload(),"candidateHash":view.hash,"schemaRevision":view.revision.to_payload(),"draftGeneration":data.get("draftGeneration")});
    if validate {
        result["valid"] = view.issues.is_empty().into();
    }
    Ok(result)
}
pub fn save(root: &Path, data: &Value) -> Result<Value> {
    let expected = required(data, "schemaRevision")?;
    let hash = required(data, "candidateHash")?;
    let (cmds, cursor) = commands(data)?;
    // Keep the fresh snapshot inside the same transaction as the save.
    let transaction = ct_storage::workspace::WorkspaceTransaction::begin(root)?;
    let s = SchemaSession::open(root)?;
    let result = s.save(expected, hash, &cmds, cursor)?;
    let fresh = SchemaSession::open(root)?;
    let mut value = snapshot_of(&fresh);
    value["isNoOp"] = result.is_no_op.into();
    value["notes"] = json!(result.notes);
    value["written"] = json!(result.written);
    value["deleted"] = json!(result.deleted);
    value["unchanged"] = json!(result.unchanged);
    value["changedResources"] = result.changed_resources.into();
    value["netDiff"] = ct_domain::netdiff::NetDiff::default().to_payload();
    value["recovery"] = json!(transaction.recovery);
    Ok(value)
}
pub fn generate_template(root: &Path, data: &Value) -> Result<Value> {
    let table = required(data, "table")?;
    let _transaction = ct_storage::workspace::WorkspaceTransaction::begin(root)?;
    let ws = Workspace::open(root)?;
    if !ws.resources.tables.iter().any(|t| t.table == table) {
        return Err(PanelError::new(404, format!("未找到表: {table}")));
    }
    Ok(json!({"messages":crate::template::gen_template(&ws,Some(table),false)?}))
}
pub fn translations(root: &Path, action: &str, data: &Value) -> Result<Value> {
    let write = matches!(action, "entry" | "sync" | "compact");
    let _transaction = if write {
        Some(ct_storage::workspace::WorkspaceTransaction::begin(root)?)
    } else {
        None
    };
    let _read = if !write { Some(readable(root)?) } else { None };
    let ws = Workspace::open(root)?;
    let table = data.get("table").and_then(Value::as_str);
    if let Some(table) = table {
        if !ws
            .resources
            .tables
            .iter()
            .any(|t| t.table == table && t.fields.iter().any(|f| f.i18n))
        {
            return Err(PanelError::new(
                400,
                format!("表 '{table}' 不存在或没有 i18n 字段"),
            ));
        }
    }
    let lang = data.get("lang").and_then(Value::as_str);
    if let Some(lang) = lang {
        if !ws.config.secondary_langs.iter().any(|l| l == lang) {
            return Err(PanelError::new(400, "语言不在 secondary_langs 中"));
        }
    }
    match action {
        "tables"=>Ok(json!(ws.resources.tables.iter().map(|t|json!({"table":t.table,"field_count":t.fields.len(),"i18n_count":t.fields.iter().filter(|f|f.i18n).count(),"has_i18n":t.fields.iter().any(|f|f.i18n)})).collect::<Vec<_>>())),
        "status"=>Ok(json!(crate::i18n::i18n_status(&ws))),
        "entries"=>Ok(json!(crate::i18n::i18n_rows(&ws,required(data,"table")?,required(data,"lang")?).iter().map(|r|{let (id,field)=r.key.split_once('.').unwrap_or((&r.key,""));json!({"key":r.key,"id":id,"field":field,"source":r.source,"text":r.text,"confirmed":r.confirmed,"status":r.status.as_str()})}).collect::<Vec<_>>())),
        "sync"=>Ok(json!({"synced":crate::i18n::i18n_sync(&ws,table,lang)?})),
        "compact"=>Ok(crate::i18n::i18n_compact(&ws,table,lang,data["dry_run"].as_bool().unwrap_or(false))?),
        "entry"=>{let table=required(data,"table")?;let lang=required(data,"lang")?;let key=required(data,"key")?;let text=data["text"].as_str().ok_or_else(||PanelError::new(400,"text 必须是字符串"))?;let confirmed=data["confirmed"].as_bool().unwrap_or(false);
            if !crate::i18n::i18n_entry_exists(&ws,table,lang,key){return Err(PanelError::new(400,"条目不存在，请先同步骨架"));}
            let status=crate::i18n::i18n_save_entry(&ws,lang,table,key,text,confirmed)?;Ok(json!({"text":text,"confirmed":confirmed,"status":status.as_str()}))},
        _=>Err(PanelError::new(404,"未知翻译操作"))
    }
}
