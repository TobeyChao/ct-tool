//! i18n.query/save/sync/status/compact DTO。

use serde::{Deserialize, Serialize};

use crate::pagination::PageRequest;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum I18nStatus {
    Translated,
    Missing,
    Stale,
    Orphan,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nQueryParams {
    pub table: String,
    pub lang: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<I18nStatus>,
    #[serde(default)]
    pub page: PageRequest,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nEntry {
    pub key: String,
    pub source: String,
    pub text: String,
    pub confirmed: bool,
    pub status: I18nStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nQueryResult {
    pub revision: u64,
    pub entries: Vec<I18nEntry>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}

/// `i18n.save`：保存单条译文，遵守 text/confirmed/status 规则。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nSaveParams {
    pub table: String,
    pub lang: String,
    pub key: String,
    pub text: String,
    pub confirmed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nSaveResult {
    pub status: I18nStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nSyncParams {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub table: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nSyncResult {
    pub tables: u32,
    pub inserted: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LangProgress {
    pub lang: String,
    pub translated: u32,
    pub missing: u32,
    pub stale: u32,
    pub orphan: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nStatusResult {
    #[serde(default)]
    pub langs: Vec<LangProgress>,
}

/// `i18n.compact`：清理 orphan；`dry_run` 时只返回将删除的条目。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nCompactParams {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub table: Option<String>,
    #[serde(default)]
    pub dry_run: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct I18nCompactResult {
    pub dry_run: bool,
    /// dry-run 时为将删除的条目键；执行后为空。
    #[serde(default)]
    pub entries: Vec<String>,
    pub removed: u32,
}
