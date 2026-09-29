//! Read-only workspace fingerprint used by the browser overview. This is
//! separate from the Schema-only save guard: Excel/translation edits change
//! this revision, but must not invalidate an unrelated YAML draft.
use crate::schema::SchemaSession;
use ct_domain::{
    hashing::{python_json_dumps, resource_to_data, sha256_hex},
    repository::Resource,
};
use serde_json::{json, Value};
use std::{collections::BTreeMap, fs, path::Path};

fn hash_json(value: &Value) -> String {
    sha256_hex(python_json_dumps(value).as_bytes())
}
fn hash_file(path: &Path) -> Result<String, String> {
    match fs::read(path) {
        Ok(bytes) => Ok(sha256_hex(&bytes)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(error) => Err(format!("读取快照输入 {} 失败: {error}", path.display())),
    }
}

pub fn revision(session: &SchemaSession) -> Result<String, String> {
    let config = &session.config;
    let mut secondary_langs = config.secondary_langs.clone();
    secondary_langs.sort();
    let config_hash = hash_json(&json!({
        "primary_lang":config.primary_lang,
        "secondary_langs":secondary_langs,
        "schemas_dir":config.schemas_dir,
        "types_dir":config.types_dir,
        "excel_dir":config.excel_dir,
        "output_dir":config.output_dir,
        "cache_dir":config.cache_dir,
        "i18n_dir":config.i18n_dir,
    }));
    let resources_hash = hash_json(&json!({
        "format":"workspace-snapshot/1",
        "resources":session.resources.iter().map(resource_to_data).collect::<Vec<_>>()
    }));
    let mut excel_hashes = BTreeMap::new();
    for resource in &session.resources {
        if let Resource::Table(table) = resource {
            excel_hashes.insert(
                table.table.clone(),
                hash_file(
                    &config
                        .resolve("excel_dir")
                        .join(table.resolved_excel_file()),
                )?,
            );
        }
    }
    let mut i18n_hashes = BTreeMap::new();
    for lang in std::iter::once("source").chain(config.secondary_langs.iter().map(String::as_str)) {
        let dir = config.resolve("i18n_dir").join(lang);
        if !dir.exists() {
            continue;
        }
        let mut files: Vec<_> = fs::read_dir(&dir)
            .map_err(|error| format!("读取翻译目录 {} 失败: {error}", dir.display()))?
            .filter_map(|entry| entry.ok().map(|e| e.path()))
            .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
            .collect();
        files.sort();
        for file in files {
            if let Some(stem) = file.file_stem().and_then(|name| name.to_str()) {
                i18n_hashes.insert(format!("{lang}/{stem}"), hash_file(&file)?);
            }
        }
    }
    Ok(hash_json(&json!({
        "config":config_hash,
        "resources":resources_hash,
        "excel":excel_hashes,
        "i18n":i18n_hashes,
        "generation":hash_json(&json!({})),
    })))
}
