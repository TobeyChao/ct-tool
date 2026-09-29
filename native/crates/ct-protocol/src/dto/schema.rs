//! schema.candidate/save DTO：revision/candidateHash 守卫与草稿代次。

use serde::{Deserialize, Serialize};

use crate::event::Issue;

/// 单条 Schema 编辑命令。
///
/// `kind` 词表由内核拥有并做服务端校验（如 `table.create`、`field.add`、
/// `enum.item.rename`）；客户端原样记录与回放，`payload` 为命令参数。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaCommand {
    pub kind: String,
    #[serde(default)]
    pub payload: serde_json::Value,
}

/// `schema.candidate` 参数。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaCandidateParams {
    /// 草稿基线：schema 源文件（config/global.yaml + schemas/types 成员）
    /// 的 sha256 摘要十六进制串。字符串而非计数器，才能检测外部改动。
    pub schema_revision: String,
    #[serde(default)]
    pub commands: Vec<SchemaCommand>,
    /// 撤销游标（不透明 token：内核用命令序号的十进制字符串，客户端不得解析）。
    pub cursor: String,
    /// 客户端单调递增的编辑代次；响应回显，丢弃乱序旧响应。
    pub draft_generation: u64,
}

/// `schema.candidate` 结果。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaCandidateResult {
    pub candidate_hash: String,
    pub draft_generation: u64,
    pub net_diff: NetDiff,
    /// 候选校验问题；存在阻塞问题时客户端禁用保存。
    #[serde(default)]
    pub problems: Vec<Issue>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NetDiff {
    #[serde(default)]
    pub added: Vec<ResourceRef>,
    #[serde(default)]
    pub removed: Vec<ResourceRef>,
    #[serde(default)]
    pub changed: Vec<ResourceRef>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ResourceRef {
    pub kind: String,
    pub name: String,
    /// 变更类型（added / removed / modified / renamed），取自内核净差异。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub change: Option<String>,
    /// 显式改名命令给出的旧名；内核只按改名命令连接身份，不按名字猜。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_name: Option<String>,
    /// 字段/枚举成员明细（含 ordinal 与 wire 风险提示），界面逐条展示。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub fields: Vec<FieldRef>,
}

/// 净差异里的单个字段或枚举成员（`details` 由内核生成，客户端不得改写）。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FieldRef {
    pub name: String,
    #[serde(default)]
    pub change: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_name: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub details: Vec<String>,
}

/// `schema.save` 参数：双守卫缺一不可。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaSaveParams {
    /// 同 [`SchemaCandidateParams::schema_revision`]。
    pub schema_revision: String,
    pub candidate_hash: String,
}

/// `schema.save` 结果：仅写 YAML，不动 Excel/翻译/产物/账本。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaSaveResult {
    /// 保存成功后的新基线摘要。
    pub schema_revision: String,
}
