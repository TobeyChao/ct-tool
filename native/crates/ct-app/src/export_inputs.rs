//! 导出输入捕获与发布前复核（对应 Python `app/exporting/prepare.py`）。
//!
//! 捕获一次、处处复用：源 Excel/译文/manifest 只读一次，reader 与账本共用
//! 同一批字节；发布前复核同一快照，任何输入变化（含资源目录成员）都阻止发布，
//! 不产出混合版本。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use ct_domain::config::GlobalConfig;
use ct_domain::hashing::sha256_hex;
use ct_domain::schema::TableResource;

/// 规范化路径作为快照身份键（解析相对段，Windows 统一小写）。
pub fn normalize(path: &Path) -> String {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    let text = out.to_string_lossy().replace('/', "\\");
    #[cfg(windows)]
    {
        text.to_lowercase()
    }
    #[cfg(not(windows))]
    {
        text
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileRevision {
    pub path: String,
    pub exists: bool,
    pub sha256: Option<String>,
    pub size: Option<u64>,
}

/// 一次输入快照：文件集合 + 资源目录成员。
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InputRevision {
    pub files: Vec<FileRevision>,
    /// (目录规范化路径, 该目录下 *.yaml 成员名有序列表)
    pub directories: Vec<(String, Vec<String>)>,
}

impl InputRevision {
    pub fn capture(paths: &[PathBuf], directories: &[PathBuf]) -> Self {
        let mut revisions = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for path in paths {
            let key = normalize(path);
            if !seen.insert(key.clone()) {
                continue;
            }
            if path.is_file() {
                let payload = std::fs::read(path).unwrap_or_default();
                revisions.push(FileRevision {
                    path: key,
                    exists: true,
                    sha256: Some(sha256_hex(&payload)),
                    size: Some(payload.len() as u64),
                });
            } else {
                revisions.push(FileRevision {
                    path: key,
                    exists: false,
                    sha256: None,
                    size: None,
                });
            }
        }
        let dirs = directories
            .iter()
            .map(|dir| {
                let mut members: Vec<String> = if dir.is_dir() {
                    std::fs::read_dir(dir)
                        .map(|entries| {
                            entries
                                .filter_map(|e| e.ok())
                                .map(|e| e.file_name().to_string_lossy().to_string())
                                .filter(|n| n.ends_with(".yaml"))
                                .collect()
                        })
                        .unwrap_or_default()
                } else {
                    Vec::new()
                };
                members.sort();
                (normalize(dir), members)
            })
            .collect();
        InputRevision {
            files: revisions,
            directories: dirs,
        }
    }

    /// 相对 `other` 的变化描述（新增/删除/内容变化/目录成员变化）。
    pub fn changes_since(&self, other: &InputRevision) -> Vec<String> {
        let mut changes = Vec::new();
        let left: BTreeMap<&str, &FileRevision> =
            other.files.iter().map(|r| (r.path.as_str(), r)).collect();
        let right: BTreeMap<&str, &FileRevision> =
            self.files.iter().map(|r| (r.path.as_str(), r)).collect();
        let keys: std::collections::BTreeSet<&str> =
            left.keys().chain(right.keys()).copied().collect();
        for key in keys {
            match (left.get(key), right.get(key)) {
                (None, Some(_)) => changes.push(format!("新增输入 {key}")),
                (Some(_), None) => changes.push(format!("移出输入范围 {key}")),
                (Some(before), Some(after)) => {
                    if before.exists != after.exists {
                        changes.push(format!(
                            "输入{} {key}",
                            if after.exists { "出现" } else { "消失" }
                        ));
                    } else if before.sha256 != after.sha256 {
                        changes.push(format!("输入内容变化 {key}"));
                    }
                }
                (None, None) => {}
            }
        }
        let dirs_left: BTreeMap<&str, &Vec<String>> = other
            .directories
            .iter()
            .map(|(k, v)| (k.as_str(), v))
            .collect();
        let dirs_right: BTreeMap<&str, &Vec<String>> = self
            .directories
            .iter()
            .map(|(k, v)| (k.as_str(), v))
            .collect();
        let dir_keys: std::collections::BTreeSet<&str> =
            dirs_left.keys().chain(dirs_right.keys()).copied().collect();
        for key in dir_keys {
            let before = dirs_left.get(key);
            let after = dirs_right.get(key);
            if before != after {
                let empty = Vec::new();
                let before = before.copied().unwrap_or(&empty);
                let after = after.copied().unwrap_or(&empty);
                let mut detail = Vec::new();
                let added: Vec<&String> = after.iter().filter(|m| !before.contains(m)).collect();
                let removed: Vec<&String> = before.iter().filter(|m| !after.contains(m)).collect();
                if !added.is_empty() {
                    detail.push(format!(
                        "新增 {}",
                        added
                            .iter()
                            .map(|s| s.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
                if !removed.is_empty() {
                    detail.push(format!(
                        "删除 {}",
                        removed
                            .iter()
                            .map(|s| s.as_str())
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
                changes.push(format!("资源目录成员变化 {key}（{}）", detail.join("；")));
            }
        }
        changes
    }
}

/// 输入在构建期间变化：中止导出，不发布混合版本。
#[derive(Debug)]
pub struct InputChangedError(pub String);

impl std::fmt::Display for InputChangedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for InputChangedError {}

pub fn verify_inputs_unchanged(
    before: &InputRevision,
    after: &InputRevision,
    when: &str,
) -> Result<(), InputChangedError> {
    let changes = after.changes_since(before);
    if changes.is_empty() {
        return Ok(());
    }
    let preview = changes
        .iter()
        .take(5)
        .cloned()
        .collect::<Vec<_>>()
        .join("；");
    let more = if changes.len() > 5 {
        format!("（共 {} 处）", changes.len())
    } else {
        String::new()
    };
    Err(InputChangedError(format!(
        "输入在{when}发生变化，已中止导出以免发布混合版本：{preview}{more}"
    )))
}

pub fn excel_path_of(config: &GlobalConfig, table: &TableResource) -> PathBuf {
    config
        .resolve("excel_dir")
        .join(table.resolved_excel_file())
}

/// 捕获 global.yaml + schemas/types 字节；返回从捕获内容解析的配置与字节映射。
pub fn capture_sources(root: &Path) -> Result<(GlobalConfig, BTreeMap<PathBuf, Vec<u8>>), String> {
    let config_path = root.join("config").join("global.yaml");
    let mut contents: BTreeMap<PathBuf, Vec<u8>> = BTreeMap::new();
    let text = if config_path.is_file() {
        let bytes = std::fs::read(&config_path)
            .map_err(|e| format!("配置文件读取失败 {}: {e}", config_path.display()))?;
        let text = String::from_utf8(bytes.clone())
            .map_err(|e| format!("配置文件不是合法 UTF-8 {}: {e}", config_path.display()))?;
        contents.insert(config_path, bytes);
        text
    } else {
        return Err(format!("配置文件不存在: {}", config_path.display()));
    };
    let config = GlobalConfig::from_yaml(&text, root)?;
    for dir in [config.resolve("schemas_dir"), config.resolve("types_dir")] {
        if !dir.is_dir() {
            continue;
        }
        let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
            .map_err(|e| format!("读取目录失败 {}: {e}", dir.display()))?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
            .collect();
        files.sort();
        for path in files {
            let bytes =
                std::fs::read(&path).map_err(|e| format!("读取失败 {}: {e}", path.display()))?;
            contents.insert(path, bytes);
        }
    }
    Ok((config, contents))
}

/// 捕获本次导出实际消费的译文文件字节（含主语言）。
pub fn capture_translation_contents(
    config: &GlobalConfig,
    tables: &[&TableResource],
    languages: &[String],
) -> BTreeMap<PathBuf, Vec<u8>> {
    let i18n_dir = config.resolve("i18n_dir");
    let mut captured = BTreeMap::new();
    let mut langs: Vec<&String> = languages.iter().collect();
    langs.push(&config.primary_lang);
    langs.sort();
    langs.dedup();
    for table in tables {
        for lang in &langs {
            let path = i18n_dir.join(lang).join(format!("{}.json", table.table));
            if path.is_file() {
                if let Ok(bytes) = std::fs::read(&path) {
                    captured.insert(path, bytes);
                }
            }
        }
    }
    captured
}

/// 捕获旧 layout manifest 字节（本次导出消费的输入快照）。
pub fn capture_manifest_contents(
    config: &GlobalConfig,
    tables: &[&TableResource],
) -> BTreeMap<PathBuf, Vec<u8>> {
    let manifest_dir = config.resolve("excel_dir").join("layout_manifests");
    let mut captured = BTreeMap::new();
    for table in tables {
        let path = manifest_dir.join(format!("{}.json", table.table));
        if path.is_file() {
            if let Ok(bytes) = std::fs::read(&path) {
                captured.insert(path, bytes);
            }
        }
    }
    captured
}

/// 只捕获一次选中表的 Excel 字节（reader 与账本共用）。
pub fn read_excel_bytes(
    config: &GlobalConfig,
    tables: &[&TableResource],
) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut captured = BTreeMap::new();
    for table in tables {
        let path = excel_path_of(config, table);
        if path.is_file() {
            if let Ok(bytes) = std::fs::read(&path) {
                captured.insert(path, bytes);
            }
        }
    }
    captured
}

/// 本次导出实际消费的输入文件集合。
///
/// `include_manifests`：manifest 既被读又被本次导出写（发布目标），
/// 只进入记录用快照，不进入发布前复核 —— 否则自己刚写的 manifest 会被误判。
pub fn consumed_paths(
    config: &GlobalConfig,
    tables: &[&TableResource],
    languages: &[String],
    include_manifests: bool,
) -> Vec<PathBuf> {
    let mut paths = vec![config.project_root.join("config").join("global.yaml")];
    for dir in [config.resolve("schemas_dir"), config.resolve("types_dir")] {
        if dir.is_dir() {
            let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
                .map(|entries| {
                    entries
                        .filter_map(|e| e.ok().map(|e| e.path()))
                        .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
                        .collect()
                })
                .unwrap_or_default();
            files.sort();
            paths.extend(files);
        }
    }
    let excel_dir = config.resolve("excel_dir");
    let i18n_dir = config.resolve("i18n_dir");
    let mut langs: Vec<&String> = languages.iter().collect();
    langs.push(&config.primary_lang);
    langs.sort();
    langs.dedup();
    for table in tables {
        paths.push(excel_path_of(config, table));
        if include_manifests {
            paths.push(
                excel_dir
                    .join("layout_manifests")
                    .join(format!("{}.json", table.table)),
            );
        }
        for lang in &langs {
            paths.push(i18n_dir.join(lang).join(format!("{}.json", table.table)));
        }
    }
    paths
}

/// 捕获输入快照（默认不含 manifest）。
pub fn capture_export_inputs(
    config: &GlobalConfig,
    tables: &[&TableResource],
    languages: &[String],
    include_manifests: bool,
) -> InputRevision {
    InputRevision::capture(
        &consumed_paths(config, tables, languages, include_manifests),
        &[config.resolve("schemas_dir"), config.resolve("types_dir")],
    )
}
