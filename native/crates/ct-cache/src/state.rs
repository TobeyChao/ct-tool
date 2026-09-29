//! 成功账本（`ct/cache/canonical_state.py`）：cache/state.json，
//! 导出或模板生成成功后推进相应记录；版本不符/损坏/缺字段一律安全落 None（重建）。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub const CACHE_STATE_VERSION: &str = "canonical-cache/1";

pub use crate::fingerprint::ArtifactFingerprints;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CanonicalCacheState {
    pub tables: BTreeMap<String, ArtifactFingerprints>,
    /// lang → bundle 指纹
    pub bundles: BTreeMap<String, String>,
    /// table → 导出/模板生成时 Excel 内容 sha256（status 的「待导出」判定依据）
    pub excel_hashes: BTreeMap<String, String>,
}

fn state_path(cache_dir: &Path) -> PathBuf {
    cache_dir.join("state.json")
}

/// 读账本；任何不符（版本/缺字段/损坏）返回 None，调用方按「无缓存」处理。
pub fn load_state(cache_dir: &Path) -> Option<CanonicalCacheState> {
    let path = state_path(cache_dir);
    let text = std::fs::read_to_string(path).ok()?;
    let data: serde_json::Value = serde_json::from_str(&text).ok()?;
    if !data.is_object() || data.get("format")?.as_str()? != CACHE_STATE_VERSION {
        return None;
    }
    let tables = data.get("tables")?.as_object()?;
    let bundles = data.get("bundles")?.as_object()?;
    let excel = data.get("excel_hashes")?.as_object()?;
    let mut state = CanonicalCacheState::default();
    for (name, item) in tables {
        let fps: ArtifactFingerprints = serde_json::from_value(item.clone()).ok()?;
        state.tables.insert(name.clone(), fps);
    }
    for (lang, fp) in bundles {
        state.bundles.insert(lang.clone(), fp.as_str()?.to_string());
    }
    for (table, hash) in excel {
        state
            .excel_hashes
            .insert(table.clone(), hash.as_str()?.to_string());
    }
    Some(state)
}

/// 写账本（sort_keys + UTF-8，与 Python 同形态）。
pub fn save_state(cache_dir: &Path, state: &CanonicalCacheState) -> Result<PathBuf, String> {
    let path = state_path(cache_dir);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("创建缓存目录失败: {e}"))?;
    }
    let bytes = state_bytes(state)?;
    std::fs::write(&path, bytes).map_err(|e| format!("账本写入失败 {}: {e}", path.display()))?;
    Ok(path)
}

/// 可与模板/产物一起经工作区发布器原子提交的账本字节。
pub fn state_bytes(state: &CanonicalCacheState) -> Result<Vec<u8>, String> {
    let payload = serde_json::json!({
        "format": CACHE_STATE_VERSION,
        "tables": state.tables,
        "bundles": state.bundles,
        "excel_hashes": state.excel_hashes,
    });
    // sort_keys：serde_json preserve_order 下手动排序
    let sorted = ct_domain::hashing::sort_keys(&payload);
    serde_json::to_vec(&sorted).map_err(|e| format!("账本序列化失败: {e}"))
}

/// 记录各表导出时的 Excel 内容 hash（不存在的表保留旧记录）。
pub fn record_excel_hashes(
    mut state: CanonicalCacheState,
    hashes: &BTreeMap<String, String>,
) -> CanonicalCacheState {
    for (table, hash) in hashes {
        state.excel_hashes.insert(table.clone(), hash.clone());
    }
    state
}

/// 合并 bundle 指纹。
pub fn upsert_bundles(
    mut state: CanonicalCacheState,
    bundles: &BTreeMap<String, String>,
) -> CanonicalCacheState {
    for (lang, fp) in bundles {
        state.bundles.insert(lang.clone(), fp.clone());
    }
    state
}
