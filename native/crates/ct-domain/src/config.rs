//! 工作区配置（`ct/config.py`）：global.yaml + 相对根目录的路径解析。

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeployTarget {
    /// 相对 project_root 的产物子目录。
    pub source: String,
    /// 相对 unity_project 的目标目录。
    pub dest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeployConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub unity_project: String,
    #[serde(default)]
    pub targets: Vec<DeployTarget>,
    #[serde(default)]
    pub build_targets: Vec<DeployTarget>,
}

impl DeployConfig {
    pub fn all_targets(&self, for_build: bool) -> Vec<&DeployTarget> {
        if for_build {
            self.targets
                .iter()
                .chain(self.build_targets.iter())
                .collect()
        } else {
            self.targets.iter().collect()
        }
    }
}

/// 全局配置。`project_root` 运行期注入，不从 YAML 读取。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GlobalConfig {
    pub primary_lang: String,
    #[serde(default)]
    pub secondary_langs: Vec<String>,
    #[serde(default = "default_schema_format")]
    pub schema_format: String,
    #[serde(default = "default_schemas_dir")]
    pub schemas_dir: String,
    #[serde(default = "default_types_dir")]
    pub types_dir: String,
    #[serde(default = "default_excel_dir")]
    pub excel_dir: String,
    #[serde(default = "default_output_dir")]
    pub output_dir: String,
    #[serde(default = "default_cache_dir")]
    pub cache_dir: String,
    #[serde(default = "default_i18n_dir")]
    pub i18n_dir: String,
    #[serde(default)]
    pub deploy: DeployConfig,
    #[serde(skip)]
    pub project_root: PathBuf,
}

fn default_schema_format() -> String {
    "yaml".to_string()
}
fn default_schemas_dir() -> String {
    "config/schemas".to_string()
}
fn default_types_dir() -> String {
    "config/types".to_string()
}
fn default_excel_dir() -> String {
    "excel".to_string()
}
fn default_output_dir() -> String {
    "output".to_string()
}
fn default_cache_dir() -> String {
    "cache".to_string()
}
fn default_i18n_dir() -> String {
    "i18n".to_string()
}

impl GlobalConfig {
    /// 从捕获到的 YAML 文本解析（导出期配置与复核内容必须同字节）。
    pub fn from_yaml(text: &str, project_root: &Path) -> Result<Self, String> {
        let mut config: GlobalConfig =
            serde_yaml_ng::from_str(text).map_err(|e| format!("配置文件解析失败: {e}"))?;
        config.primary_lang = config.primary_lang.trim().to_string();
        if config.primary_lang.is_empty() {
            return Err("primary_lang 不能为空".to_string());
        }
        config.project_root = project_root.to_path_buf();
        Ok(config)
    }

    /// 从磁盘加载 config/global.yaml。
    pub fn load(project_root: &Path) -> Result<Self, String> {
        let path = project_root.join("config").join("global.yaml");
        if !path.exists() {
            return Err(format!("配置文件不存在: {}", path.display()));
        }
        let text = std::fs::read_to_string(&path)
            .map_err(|e| format!("配置文件读取失败 {}: {e}", path.display()))?;
        Self::from_yaml(&text, project_root)
    }

    /// 按目录名解析（schemas_dir/excel_dir/...）。
    pub fn resolve(&self, name: &str) -> PathBuf {
        let rel = match name {
            "schemas_dir" => &self.schemas_dir,
            "types_dir" => &self.types_dir,
            "excel_dir" => &self.excel_dir,
            "output_dir" => &self.output_dir,
            "cache_dir" => &self.cache_dir,
            "i18n_dir" => &self.i18n_dir,
            other => return self.project_root.join(other),
        };
        self.project_root.join(rel)
    }

    pub fn all_langs(&self) -> Vec<String> {
        let mut langs = vec![self.primary_lang.clone()];
        langs.extend(self.secondary_langs.iter().cloned());
        langs
    }

    pub fn unity_project_root(&self) -> Option<PathBuf> {
        if self.deploy.unity_project.is_empty() {
            return None;
        }
        let p = PathBuf::from(&self.deploy.unity_project);
        Some(if p.is_absolute() {
            p
        } else {
            self.project_root.join(p)
        })
    }

    /// 展开 deploy 目标为 (source, dest) 绝对路径对；未配置/未启用返回空。
    pub fn resolve_deploy_targets(&self, for_build: bool) -> Vec<(PathBuf, PathBuf)> {
        if !self.deploy.enabled {
            return Vec::new();
        }
        let Some(unity_root) = self.unity_project_root() else {
            return Vec::new();
        };
        self.deploy
            .all_targets(for_build)
            .into_iter()
            .map(|t| (self.project_root.join(&t.source), unity_root.join(&t.dest)))
            .collect()
    }
}
