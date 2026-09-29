//! 可恢复的多文件发布（对应 Python `ct/storage/publication.py`）。
//!
//! 阶段：prepared（目标清单落 journal）→ backed_up（备份+校验）→
//! publishing（逐文件替换/删除并记录）→ committed（原子提交点后清理）。
//! 任一阶段失败即回滚到发布前文件集合；崩溃后由 `recover` 幂等恢复。
//! 仅识别 `export-publication/1` 新格式，不迁移旧格式。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::journal::{journal_path, JOURNAL_FORMAT, PRIVATE_DIRNAME};

pub const PHASE_PREPARED: &str = "prepared";
pub const PHASE_BACKED_UP: &str = "backed_up";
pub const PHASE_PUBLISHING: &str = "publishing";
pub const PHASE_COMMITTED: &str = "committed";

pub const OP_CREATE: &str = "create";
pub const OP_REPLACE: &str = "replace";
pub const OP_DELETE: &str = "delete";

#[derive(Debug, Clone)]
pub struct PublicationError(pub String);

impl std::fmt::Display for PublicationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for PublicationError {}

/// 内容摘要：写穿后内存只留哈希，去重与发布前复核都靠它。
pub fn sha256_hex(data: &[u8]) -> String {
    use sha2::Digest;
    let mut hasher = sha2::Sha256::new();
    hasher.update(data);
    format!("{:x}", hasher.finalize())
}

fn file_mtime(path: &Path) -> Option<u64> {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs())
}

fn sha256_file(path: &Path) -> Result<String, PublicationError> {
    let data = std::fs::read(path)
        .map_err(|e| PublicationError(format!("读取失败 {}: {e}", path.display())))?;
    Ok(sha256_hex(&data))
}

/// 原子写：同目录临时文件 + rename（不跨卷）。
pub fn atomic_write(path: &Path, data: &[u8]) -> Result<(), PublicationError> {
    let parent = path
        .parent()
        .ok_or_else(|| PublicationError(format!("目标没有父目录：{}", path.display())))?;
    std::fs::create_dir_all(parent)
        .map_err(|e| PublicationError(format!("创建目录失败 {}: {e}", parent.display())))?;
    let temporary = parent.join(format!(
        ".ct-stage-{}-{}",
        std::process::id(),
        path.file_name().and_then(|n| n.to_str()).unwrap_or("tmp")
    ));
    std::fs::write(&temporary, data)
        .map_err(|e| PublicationError(format!("暂存失败 {}: {e}", temporary.display())))?;
    std::fs::rename(&temporary, path).map_err(|e| {
        let _ = std::fs::remove_file(&temporary);
        PublicationError(format!("替换失败 {}: {e}", path.display()))
    })?;
    Ok(())
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PublicationEntry {
    pub path: String,
    pub op: String,
    pub existed: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub old_hash: Option<String>,
    /// 原文件 mtime（秒，UNIX epoch）；恢复时一并还原（Python 由 copy2 隐式携带）
    #[serde(skip_serializing_if = "Option::is_none")]
    pub old_mtime: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub new_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub staged: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backup: Option<String>,
    #[serde(default)]
    pub done: bool,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PublicationJournal {
    pub format: String,
    pub operation_id: String,
    pub root: String,
    pub phase: String,
    pub allowed_dirs: Vec<String>,
    pub entries: Vec<PublicationEntry>,
}

/// 已写穿到私有暂存区的一批字节：生成期间只留路径与哈希，发布时仅改名。
#[derive(Debug, Clone)]
pub struct StagedPayload {
    /// 暂存文件（工作区私有目录内，与目标同卷，改名保持原子）。
    pub staged: PathBuf,
    /// 内容 sha256：发布前复核与同内容去重都靠它，不再留字节。
    pub new_hash: String,
    /// 字节数（诊断与内存预算用）。
    pub bytes: u64,
}

pub struct FilePublisher {
    root: PathBuf,
    private_dir: PathBuf,
    journal_path: PathBuf,
    staged_seq: std::sync::atomic::AtomicUsize,
}

impl FilePublisher {
    pub fn new(root: &Path) -> Self {
        let private_dir = root.join(PRIVATE_DIRNAME);
        FilePublisher {
            root: root.to_path_buf(),
            journal_path: private_dir.join(crate::journal::JOURNAL_NAME),
            staged_seq: std::sync::atomic::AtomicUsize::new(0),
            private_dir,
        }
    }

    pub fn journal_exists(&self) -> bool {
        self.journal_path.exists()
    }

    pub fn read_journal(&self) -> Result<Option<PublicationJournal>, PublicationError> {
        if !self.journal_path.exists() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(&self.journal_path).map_err(|e| {
            PublicationError(format!(
                "发布恢复记录读取失败，已保留材料并拒绝继续：{}（{e}）",
                self.journal_path.display()
            ))
        })?;
        let data: serde_json::Value = serde_json::from_str(&text).map_err(|e| {
            PublicationError(format!(
                "发布恢复记录损坏，已保留材料并拒绝继续：{}（{e}）",
                self.journal_path.display()
            ))
        })?;
        if !data.is_object() || data.get("format").and_then(|f| f.as_str()) != Some(JOURNAL_FORMAT)
        {
            return Err(PublicationError(format!(
                "发布恢复记录格式未知，已保留材料并拒绝继续：{}（需要 {JOURNAL_FORMAT}）",
                self.journal_path.display()
            )));
        }
        let journal: PublicationJournal = serde_json::from_value(data).map_err(|e| {
            PublicationError(format!(
                "发布恢复记录损坏，已保留材料并拒绝继续：{}（{e}）",
                self.journal_path.display()
            ))
        })?;
        self.validate_journal(&journal)?;
        Ok(Some(journal))
    }

    /// 记录里的每个路径都必须落在声明的允许目录内。
    fn validate_journal(&self, journal: &PublicationJournal) -> Result<(), PublicationError> {
        for entry in &journal.entries {
            let target = PathBuf::from(&entry.path);
            let inside = journal
                .allowed_dirs
                .iter()
                .map(PathBuf::from)
                .any(|base| target == base || target.starts_with(&base));
            if !inside {
                return Err(PublicationError(format!(
                    "发布恢复记录包含越界路径，已保留材料并拒绝继续：{}",
                    target.display()
                )));
            }
        }
        Ok(())
    }

    fn write_journal(&self, journal: &PublicationJournal) -> Result<(), PublicationError> {
        let payload = serde_json::to_string_pretty(journal)
            .map_err(|e| PublicationError(format!("journal 序列化失败: {e}")))?;
        atomic_write(&self.journal_path, payload.as_bytes())
    }

    /// 发布一批写入与删除；任一步失败即回滚到发布前状态。
    pub fn publish(
        &self,
        writes: &BTreeMap<PathBuf, Vec<u8>>,
        deletes: &[PathBuf],
    ) -> Result<(), PublicationError> {
        if writes.is_empty() && deletes.is_empty() {
            return Ok(());
        }
        // 本批次尚未开始暂存，可以清扫上一轮残留
        self.recover()?;
        let operation_id = self.new_operation_id();
        let mut staged: Vec<(PathBuf, StagedPayload)> = Vec::with_capacity(writes.len());
        for (path, data) in writes {
            match self.stage_private(&operation_id, path, data) {
                Ok(payload) => staged.push((path.clone(), payload)),
                Err(error) => {
                    let paths: Vec<PathBuf> = staged
                        .iter()
                        .map(|(_, payload)| payload.staged.clone())
                        .collect();
                    self.drop_staged(&paths);
                    let _ = std::fs::remove_dir_all(self.staging_dir(&operation_id));
                    return Err(error);
                }
            }
        }
        let result = self.publish_staged(&operation_id, &staged, deletes);
        let _ = std::fs::remove_dir_all(self.staging_dir(&operation_id));
        result
    }

    fn new_operation_id(&self) -> String {
        format!(
            "{:x}-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0),
            std::process::id()
        )
    }

    /// 发布已经写穿到暂存区的批次：journal 阶段、备份、逐文件改名与回滚语义与 publish 相同。
    pub fn publish_staged(
        &self,
        operation_id: &str,
        writes: &[(PathBuf, StagedPayload)],
        deletes: &[PathBuf],
    ) -> Result<(), PublicationError> {
        if writes.is_empty() && deletes.is_empty() {
            return Ok(());
        }
        // 先处理上一次未完成的发布，避免叠加；此处**不能**清扫私有暂存：
        // 本批次的待发布字节正躺在暂存目录里。
        self.recover_inner(false)?;
        let mut allowed: Vec<String> = writes
            .iter()
            .map(|(path, _)| path.clone())
            .chain(deletes.iter().cloned())
            .filter_map(|p| p.parent().map(|p| p.to_string_lossy().to_string()))
            .collect();
        allowed.sort();
        allowed.dedup();

        let mut entries: Vec<PublicationEntry> = Vec::new();
        let mut staging: Vec<PathBuf> = Vec::new();

        let result = (|| -> Result<(), PublicationError> {
            for (path, payload) in writes {
                let staged = payload.staged.clone();
                if !staged.is_file() {
                    return Err(PublicationError(format!(
                        "暂存文件缺失：{}",
                        staged.display()
                    )));
                }
                staging.push(staged.clone());
                let existed = path.is_file();
                entries.push(PublicationEntry {
                    path: path.to_string_lossy().to_string(),
                    op: if existed { OP_REPLACE } else { OP_CREATE }.to_string(),
                    existed,
                    old_hash: if existed {
                        Some(sha256_file(path)?)
                    } else {
                        None
                    },
                    old_mtime: file_mtime(path),
                    new_hash: Some(payload.new_hash.clone()),
                    staged: Some(staged.to_string_lossy().to_string()),
                    backup: None,
                    done: false,
                });
            }
            for path in deletes {
                if !path.is_file() {
                    continue;
                }
                entries.push(PublicationEntry {
                    path: path.to_string_lossy().to_string(),
                    op: OP_DELETE.to_string(),
                    existed: true,
                    old_hash: Some(sha256_file(path)?),
                    old_mtime: file_mtime(path),
                    new_hash: None,
                    staged: None,
                    backup: None,
                    done: false,
                });
            }

            let mut journal = PublicationJournal {
                format: JOURNAL_FORMAT.to_string(),
                operation_id: operation_id.to_string(),
                root: self.root.to_string_lossy().to_string(),
                phase: PHASE_PREPARED.to_string(),
                allowed_dirs: allowed,
                entries: entries.clone(),
            };
            self.write_journal(&journal)?;

            // backed_up：备份完成且 hash 校验通过之前不改写正式目标
            let backup_dir = self.private_dir.join("backup").join(operation_id);
            for (index, entry) in entries.iter_mut().enumerate() {
                if entry.old_hash.is_none() {
                    continue;
                }
                std::fs::create_dir_all(&backup_dir)
                    .map_err(|e| PublicationError(format!("创建备份目录失败: {e}")))?;
                let name = Path::new(&entry.path)
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("file")
                    .to_string();
                let backup = backup_dir.join(format!("{}-{name}", entry.path.len()));
                std::fs::copy(Path::new(&entry.path), &backup)
                    .map_err(|e| PublicationError(format!("备份失败 {}: {e}", entry.path)))?;
                if sha256_file(&backup)? != entry.old_hash.clone().unwrap_or_default() {
                    return Err(PublicationError(format!(
                        "备份校验失败，未改写任何正式文件：{}",
                        entry.path
                    )));
                }
                entry.backup = Some(backup.to_string_lossy().to_string());
                journal.entries[index] = entry.clone();
            }
            journal.phase = PHASE_BACKED_UP.to_string();
            self.write_journal(&journal)?;

            // publishing：逐文件替换/删除，进度写入 journal
            journal.phase = PHASE_PUBLISHING.to_string();
            self.write_journal(&journal)?;
            for (index, entry) in entries.iter().enumerate() {
                self.apply_entry(entry)?;
                journal.entries[index].done = true;
                self.write_journal(&journal)?;
            }

            // committed：先原子记录提交点，再清理材料
            journal.phase = PHASE_COMMITTED.to_string();
            self.write_journal(&journal)?;
            self.cleanup(&journal);
            Ok(())
        })();

        match result {
            Err(error) => match self.rollback(&staging) {
                Ok(()) => Err(error),
                Err(rollback_error) => Err(PublicationError(format!(
                    "{error}；回滚不完整：{rollback_error}"
                ))),
            },
            ok => ok,
        }
    }

    pub fn staging_dir(&self, operation_id: &str) -> PathBuf {
        self.private_dir.join("staged").join(operation_id)
    }

    /// 把字节立刻写入工作区私有暂存区：调用方随后即可释放内存，发布时只做改名。
    /// 文件名保留 `.ct-stage-` 前缀：恢复演练与陈旧清理都按这个前缀识别私有暂存。
    /// 暂存目录在 `.ct/` 下，绝不污染 output/，崩溃残留由 sweep_staging 收走。
    pub fn stage_private(
        &self,
        operation_id: &str,
        target: &Path,
        data: &[u8],
    ) -> Result<StagedPayload, PublicationError> {
        let dir = self.staging_dir(operation_id);
        std::fs::create_dir_all(&dir)
            .map_err(|e| PublicationError(format!("创建暂存目录失败 {}: {e}", dir.display())))?;
        let seq = self
            .staged_seq
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let base = target.file_name().and_then(|n| n.to_str()).unwrap_or("tmp");
        // 同一批次里同名文件很多（各目录同名），用目标路径摘要 + 序号保证唯一。
        let slot = sha256_hex(target.to_string_lossy().as_bytes());
        let staged = dir.join(format!(".ct-stage-{seq:05}-{}-{base}", &slot[..12]));
        let mut file = std::fs::File::create(&staged)
            .map_err(|e| PublicationError(format!("暂存失败 {}: {e}", staged.display())))?;
        std::io::Write::write_all(&mut file, data)
            .map_err(|e| PublicationError(format!("暂存写入失败 {}: {e}", staged.display())))?;
        std::io::Write::flush(&mut file)
            .map_err(|e| PublicationError(format!("暂存落盘失败 {}: {e}", staged.display())))?;
        drop(file);
        Ok(StagedPayload {
            staged,
            new_hash: sha256_hex(data),
            bytes: data.len() as u64,
        })
    }

    /// 丢弃尚未发布的暂存文件（生成失败/放弃发布时调用；不碰正式文件）。
    pub fn drop_staged(&self, paths: &[PathBuf]) {
        for path in paths {
            let _ = std::fs::remove_file(path);
        }
    }

    /// 没有 journal 时清扫私有暂存根目录：上一轮生成中途被杀不该留下垃圾。
    /// 有 journal 时不能动（恢复要按记录处理）。返回清掉的暂存文件数。
    pub fn sweep_staging(&self) -> Result<usize, PublicationError> {
        if self.journal_path.exists() {
            return Ok(0);
        }
        let root = self.private_dir.join("staged");
        if !root.is_dir() {
            return Ok(0);
        }
        let mut removed = 0usize;
        let mut stack = vec![root.clone()];
        while let Some(dir) = stack.pop() {
            // 目录可能已被上一步清走；读不到就当没有，绝不让清扫本身成为失败源。
            let Ok(entries) = std::fs::read_dir(&dir) else {
                continue;
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                if std::fs::remove_file(&path).is_ok() {
                    removed += 1;
                }
            }
        }
        // 只剩空目录：整棵删掉（失败也无妨，正式文件从未被触碰）
        let _ = std::fs::remove_dir_all(&root);
        Ok(removed)
    }

    fn apply_entry(&self, entry: &PublicationEntry) -> Result<(), PublicationError> {
        let target = Path::new(&entry.path);
        if entry.op == OP_DELETE {
            if target.exists() {
                std::fs::remove_file(target)
                    .map_err(|e| PublicationError(format!("删除失败 {}: {e}", target.display())))?;
            }
            return Ok(());
        }
        let staged = entry
            .staged
            .clone()
            .ok_or_else(|| PublicationError(format!("缺少暂存文件记录：{}", entry.path)))?;
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| PublicationError(format!("创建目录失败 {}: {e}", parent.display())))?;
        }
        std::fs::rename(&staged, target)
            .map_err(|e| PublicationError(format!("替换失败 {}: {e}", target.display())))?;
        Ok(())
    }

    /// 回滚到发布前文件集合：恢复被覆盖/删除的文件，移除本次新建。
    /// 恢复失败时保留 journal 与材料（交给显式 recover/人工处理）。
    fn rollback(&self, staging: &[PathBuf]) -> Result<(), PublicationError> {
        for staged in staging {
            let _ = std::fs::remove_file(staged);
        }
        let Some(journal) = self.read_journal()? else {
            return Ok(());
        };
        self.restore(&journal)?;
        self.cleanup(&journal);
        Ok(())
    }

    /// 幂等恢复未完成的发布。返回一句描述；没有待恢复记录时返回 None。
    ///
    /// 这是对外入口（加载资源前调用）：没有恢复记录时顺手清走上一轮崩溃残留的
    /// 私有暂存。
    pub fn recover(&self) -> Result<Option<String>, PublicationError> {
        self.recover_inner(true)
    }

    /// `sweep_orphans=false` 供发布路径内部使用：此时本批次的暂存文件正在路上，
    /// 清扫会把待发布的字节自己删掉。
    fn recover_inner(&self, sweep_orphans: bool) -> Result<Option<String>, PublicationError> {
        let Some(journal) = self.read_journal()? else {
            if sweep_orphans {
                self.sweep_staging()?;
            }
            return Ok(None);
        };
        match journal.phase.as_str() {
            // 备份尚未完成 ⇒ 正式文件不可能被改动，只清理私有资源
            PHASE_PREPARED => {
                self.cleanup(&journal);
                Ok(Some("上次发布尚未完成备份，仅清理私有材料".to_string()))
            }
            // 已提交：只完成清理，不回滚完整的新版本
            PHASE_COMMITTED => {
                self.cleanup(&journal);
                Ok(Some("上次发布已提交，仅清理恢复材料".to_string()))
            }
            _ => {
                self.restore(&journal)?;
                self.cleanup(&journal);
                Ok(Some(format!(
                    "已回滚未完成的发布（{}）",
                    journal.operation_id
                )))
            }
        }
    }

    /// 把正式文件恢复到发布前集合（内容与 mtime），并移除本次新建文件。
    /// 备份缺失/恢复失败：返回错误并保留全部材料（journal、备份目录、现状文件）。
    fn restore(&self, journal: &PublicationJournal) -> Result<(), PublicationError> {
        for entry in &journal.entries {
            let target = Path::new(&entry.path);
            if entry.existed {
                let Some(backup) = &entry.backup else {
                    return Err(PublicationError(format!(
                        "无法恢复：备份未生成（目标 {}），已保留恢复材料",
                        entry.path
                    )));
                };
                let backup = PathBuf::from(backup);
                if !backup.is_file() {
                    return Err(PublicationError(format!(
                        "无法恢复：备份缺失 {}（目标 {}），已保留恢复材料",
                        backup.display(),
                        entry.path
                    )));
                }
                // Python journals carry mtime on the copy2 backup, not in an
                // old_mtime field. std::fs::copy does not preserve timestamps
                // on every platform, so restore it explicitly in both formats.
                let modified = match entry.old_mtime {
                    Some(mtime) => std::time::UNIX_EPOCH + std::time::Duration::from_secs(mtime),
                    None => std::fs::metadata(&backup)
                        .and_then(|metadata| metadata.modified())
                        .map_err(|e| {
                            PublicationError(format!(
                                "读取备份 mtime 失败 {}: {e}",
                                backup.display()
                            ))
                        })?,
                };
                if let Some(parent) = target.parent() {
                    std::fs::create_dir_all(parent).map_err(|e| {
                        PublicationError(format!("恢复目录失败 {}: {e}", parent.display()))
                    })?;
                }
                std::fs::copy(&backup, target).map_err(|e| {
                    PublicationError(format!("恢复失败 {}: {e}，已保留恢复材料", entry.path))
                })?;
                {
                    let file = std::fs::File::options()
                        .write(true)
                        .open(target)
                        .map_err(|e| {
                            PublicationError(format!("恢复 mtime 失败 {}: {e}", entry.path))
                        })?;
                    file.set_modified(modified).map_err(|e| {
                        PublicationError(format!("恢复 mtime 失败 {}: {e}", entry.path))
                    })?;
                }
            } else if target.is_file() {
                // 发布器只创建文件；目标是目录说明为外部内容，不属于本事务
                std::fs::remove_file(target).map_err(|e| {
                    PublicationError(format!("清理本次新增文件失败 {}: {e}", entry.path))
                })?;
            }
        }
        Ok(())
    }

    fn cleanup(&self, journal: &PublicationJournal) {
        for entry in &journal.entries {
            // 私有暂存文件也必须收口：否则中断一次就在产物目录里永久留下一份 .ct-stage-*
            if let Some(staged) = &entry.staged {
                let _ = std::fs::remove_file(staged);
            }
            if let Some(backup) = &entry.backup {
                let _ = std::fs::remove_file(backup);
            }
        }
        let _ =
            std::fs::remove_dir_all(self.private_dir.join("backup").join(&journal.operation_id));
        let _ = std::fs::remove_file(&self.journal_path);
    }
}

/// 只读探测见 `crate::journal::pending_publication_note`。
pub fn journal_path_for(root: &Path) -> PathBuf {
    journal_path(root)
}
