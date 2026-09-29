//! 分层指纹：解析器版本+Excel 字节+布局；校验版本+行数据+Schema；
//! ref 校验+外键投影+目标主键；产物+生成器版本+有效输入。

/// bundle 指纹（`fingerprints.bundle_fingerprint`）：lang + 容器版本 + 表字节 hash 集合。
pub const BUNDLE_FMT_VERSION: &str = "bundle-fp/1";
pub const BUNDLE_CONTAINER_VERSION: &str = "bundle-container/1";

pub fn bundle_fingerprint(lang: &str, table_bytes_hashes: &[(String, String)]) -> String {
    let mut sorted = table_bytes_hashes.to_vec();
    sorted.sort();
    let payload = serde_json::json!({
        "format": BUNDLE_FMT_VERSION,
        "lang": lang,
        "container": BUNDLE_CONTAINER_VERSION,
        "tables": sorted,
    });
    ct_domain::hashing::stable_sha256(&payload)
}

// ---------------------------------------------------------------------------
// 分层产物指纹（对应 Python `ct/cache/fingerprints.py`）
// ---------------------------------------------------------------------------

pub const SCHEMA_FMT_VERSION: &str = "schema-fp/1";
pub const DATA_FMT_VERSION: &str = "data-fp/1";
pub const I18N_FMT_VERSION: &str = "i18n-fp/1";
pub const MERGE_POLICY_VERSION: &str = "merge-v1";

fn stable(data: &serde_json::Value) -> String {
    ct_domain::hashing::stable_sha256(data)
}

/// FBS + Accessor 级指纹：表 schema + 传递依赖 + 索引 + 生成器版本。
pub fn schema_fingerprint(
    table: &serde_json::Value,
    transitive_dependencies: &[serde_json::Value],
    indexes: &[serde_json::Value],
    codegen_version: &str,
) -> String {
    let mut deps = transitive_dependencies.to_vec();
    // Python sorted(key=str)：按 JSON 文本排序
    deps.sort_by_key(|v| serde_json::to_string(v).unwrap_or_default());
    stable(&serde_json::json!({
        "format": SCHEMA_FMT_VERSION,
        "codegen": codegen_version,
        "table": table,
        "dependencies": deps,
        "indexes": indexes,
    }))
}

/// 主语言 JSON + 主表 bytes 级指纹。
pub fn data_fingerprint(
    schema_fingerprint: &str,
    excel_hash: &str,
    parsing_inputs: &serde_json::Value,
) -> String {
    stable(&serde_json::json!({
        "format": DATA_FMT_VERSION,
        "schema": schema_fingerprint,
        "excel": excel_hash,
        "parsing": parsing_inputs,
    }))
}

/// 有效翻译语义：仅有效 key 的 text + confirmed（派生 status/source 不参与）。
pub fn effective_translation_semantics(
    entries: &std::collections::BTreeMap<String, serde_json::Value>,
    valid_keys: &std::collections::BTreeSet<String>,
) -> Vec<(String, String, bool)> {
    valid_keys
        .iter()
        .filter_map(|key| {
            let entry = entries.get(key)?;
            Some((
                key.clone(),
                entry
                    .get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                entry
                    .get("confirmed")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false),
            ))
        })
        .collect()
}

/// 单语言 JSON + i18n bytes 级指纹。
pub fn i18n_fingerprint(
    data_fingerprint: &str,
    lang: &str,
    primary_lang: &str,
    enabled_langs: &[String],
    valid_keys: &std::collections::BTreeSet<String>,
    entries: &std::collections::BTreeMap<String, serde_json::Value>,
) -> String {
    let mut langs = enabled_langs.to_vec();
    langs.sort();
    stable(&serde_json::json!({
        "format": I18N_FMT_VERSION,
        "data": data_fingerprint,
        "lang": lang,
        "primary_lang": primary_lang,
        "enabled_langs": langs,
        "merge_policy": MERGE_POLICY_VERSION,
        "semantics": effective_translation_semantics(entries, valid_keys),
    }))
}

/// 表级指纹集（state.json 中的存储形态）。
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ArtifactFingerprints {
    #[serde(default)]
    pub schema: String,
    #[serde(default)]
    pub data: String,
    #[serde(default)]
    pub i18n: std::collections::BTreeMap<String, String>,
}

/// 复用判定：schema 指纹控制 FBS/Accessor，data 控制主语言产物，
/// i18n 逐语言（要求 data 也可复用）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReuseDecision {
    pub schema_reusable: bool,
    pub data_reusable: bool,
    pub i18n_reusable: std::collections::BTreeMap<String, bool>,
}

pub fn decide_artifact_reuse(
    previous: Option<&ArtifactFingerprints>,
    current: &ArtifactFingerprints,
    langs: &[String],
) -> ReuseDecision {
    let Some(previous) = previous else {
        return ReuseDecision {
            schema_reusable: false,
            data_reusable: false,
            i18n_reusable: langs.iter().map(|l| (l.clone(), false)).collect(),
        };
    };
    let schema_reusable = previous.schema == current.schema;
    let data_reusable = previous.data == current.data;
    let i18n_reusable = langs
        .iter()
        .map(|lang| {
            let ok = data_reusable
                && previous.i18n.contains_key(lang)
                && previous.i18n.get(lang) == current.i18n.get(lang);
            (lang.clone(), ok)
        })
        .collect();
    ReuseDecision {
        schema_reusable,
        data_reusable,
        i18n_reusable,
    }
}
