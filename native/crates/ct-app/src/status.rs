//! 只读状态概览（`canonical_status` + pending 发布报告）。
//!
//! 不写缓存、不恢复事务：只比较 hash/manifest/列数并读取 journal。

use std::collections::HashMap;
use std::path::Path;

use ct_domain::hashing::compute_schema_hash;
use ct_domain::repository::Resource;
use ct_excel::layout::build_layout;
use ct_excel::manifest::LayoutManifest;
use ct_excel::reader::probe_xlsx;
use sha2::{Digest, Sha256};

use crate::workspace::Workspace;

#[derive(Debug, Default, PartialEq, Eq)]
pub struct StatusReport {
    pub missing: Vec<String>,
    pub changed: Vec<String>,
    pub drifted: Vec<String>,
    pub publication: Option<String>,
}

fn file_sha256(path: &Path) -> Option<String> {
    let bytes = std::fs::read(path).ok()?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Some(format!("{:x}", hasher.finalize()))
}

/// cache/state.json 的 excel_hashes 台账（只读；格式不明就当没有记录）。
fn excel_hashes_ledger(cache_dir: &Path) -> HashMap<String, String> {
    let Ok(text) = std::fs::read_to_string(cache_dir.join("state.json")) else {
        return HashMap::new();
    };
    let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) else {
        return HashMap::new();
    };
    if data.get("format").and_then(|f| f.as_str()) != Some("canonical-cache/1") {
        return HashMap::new();
    }
    data.get("excel_hashes")
        .and_then(|v| v.as_object())
        .map(|m| {
            m.iter()
                .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                .collect()
        })
        .unwrap_or_default()
}

/// 逐表数据变更 + 模板漂移状态。
pub fn canonical_status(workspace: &Workspace) -> StatusReport {
    let records = workspace.resources.records_map();
    let dep_resources: Vec<Resource> = workspace
        .resources
        .records
        .iter()
        .cloned()
        .map(Resource::Record)
        .chain(
            workspace
                .resources
                .enums
                .iter()
                .cloned()
                .map(Resource::Enum),
        )
        .collect();
    let cache_dir = workspace.config.resolve("cache_dir");
    let ledger = excel_hashes_ledger(&cache_dir);
    let manifest_dir = workspace.manifest_dir();

    let mut report = StatusReport::default();
    for table in &workspace.resources.tables {
        let excel_path = workspace.excel_dir().join(table.resolved_excel_file());
        if !excel_path.exists() {
            report.missing.push(table.table.clone());
            continue;
        }
        let Some(current_hash) = file_sha256(&excel_path) else {
            report.missing.push(table.table.clone());
            continue;
        };
        let schema_hash = compute_schema_hash(table, &dep_resources);
        let layout = build_layout(table, &schema_hash, &records);

        let manifest = std::fs::read_to_string(manifest_dir.join(format!("{}.json", table.table)))
            .ok()
            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
            .and_then(|value| LayoutManifest::parse(&value));
        let workbook_column_count = probe_xlsx(&excel_path)
            .ok()
            .map(|r| r.cells.iter().map(|c| c.col).max().unwrap_or(0) as usize);

        if manifest
            .as_ref()
            .is_none_or(|m| m.schema_hash != schema_hash)
            || workbook_column_count != Some(layout.column_count())
        {
            report.drifted.push(table.table.clone());
        }
        if ledger.get(&table.table) != Some(&current_hash) {
            report.changed.push(table.table.clone());
        }
    }
    report.missing.sort();
    report.missing.dedup();
    report.changed.sort();
    report.drifted.sort();
    report.drifted.dedup();
    report.publication = ct_storage::journal::pending_publication_note(&workspace.root);
    report
}
