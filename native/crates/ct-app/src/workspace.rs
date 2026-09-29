//! 工作区装载：配置 + 资源（对应 Python `CanonicalWorkspace`）。

use std::path::{Path, PathBuf};

use ct_domain::config::GlobalConfig;
use ct_domain::repository::{ResourceWorkspace, YamlResourceRepository};
use ct_domain::schema::SchemaError;

/// 已装载的工作区。
pub struct Workspace {
    pub root: PathBuf,
    pub config: GlobalConfig,
    pub resources: ResourceWorkspace,
}

impl Workspace {
    /// 从磁盘打开（config/global.yaml + schemas/types 目录）。
    pub fn open(root: &Path) -> Result<Self, SchemaError> {
        let config = GlobalConfig::load(root).map_err(SchemaError)?;
        let repo =
            YamlResourceRepository::new(config.resolve("schemas_dir"), config.resolve("types_dir"));
        let resources = repo.load()?;
        Ok(Workspace {
            root: root.to_path_buf(),
            config,
            resources,
        })
    }

    pub fn excel_dir(&self) -> PathBuf {
        self.config.resolve("excel_dir")
    }

    pub fn manifest_dir(&self) -> PathBuf {
        self.excel_dir().join("layout_manifests")
    }
}

/// 只读探测：存在未完成发布时给出需要恢复的描述（不恢复、不写盘）。
pub fn recovery_needed(root: &Path) -> Option<String> {
    ct_storage::journal::pending_publication_note(root)
}

/// 显式恢复结果：恢复描述（无事务时为 None）+ 恢复后的新基线。
#[derive(Debug)]
pub struct RecoveryReport {
    pub note: Option<String>,
    pub revision: String,
}

/// 显式 `workspace.recover`：共享锁下恢复未完成发布并返回新基线。
/// 不隐式保存草稿、不导出、不推进成功账本。
pub fn recover_workspace(root: &Path) -> Result<RecoveryReport, String> {
    let transaction =
        ct_storage::workspace::WorkspaceTransaction::begin(root).map_err(|e| match e {
            ct_storage::workspace::TransactionError::Busy(busy) => busy.0,
            ct_storage::workspace::TransactionError::Recovery(message) => message,
        })?;
    let config = GlobalConfig::load(root)?;
    let sources = crate::schema::capture_schema_sources(&config);
    Ok(RecoveryReport {
        note: transaction.recovery.clone(),
        revision: sources.revision.revision,
    })
}
