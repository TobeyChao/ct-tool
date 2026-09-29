//! Unity 部署（`ct/export/deploy.py`）：targets/build_targets、同内容不写、
//! .meta 保留/删除、缺源失败。

use std::path::{Path, PathBuf};

use ct_domain::config::GlobalConfig;

#[derive(Debug)]
pub struct DeployError(pub String);

impl std::fmt::Display for DeployError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for DeployError {}

/// 把 dst 同步为与 src 完全一致，返回写入/删除的文件总数。
///
/// - 不存在的 src 是错误（防止把空目录同步过去造成误删）；
/// - 代码产物同步保留已存在文件的 .meta（GUID 稳定）；产物被删除时连带删
///   同名 .meta；源里仍有对应产物的孤儿 .meta 保留；
/// - 内容一致不重写（避免无谓的 mtime 变化触发 Unity 重导入）。
pub fn sync_dir(src: &Path, dst: &Path) -> Result<(usize, Vec<String>), DeployError> {
    if !src.is_dir() {
        return Err(DeployError(format!("产物目录不存在: {}", src.display())));
    }
    std::fs::create_dir_all(dst)
        .map_err(|e| DeployError(format!("创建部署目录失败 {}: {e}", dst.display())))?;

    let mut changed = 0usize;
    let mut logs = Vec::new();
    let src_names: std::collections::BTreeSet<String> = std::fs::read_dir(src)
        .map_err(|e| DeployError(format!("读取产物目录失败 {}: {e}", src.display())))?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_file())
        .map(|e| e.file_name().to_string_lossy().to_string())
        .collect();

    // 清理目标多余产物
    let mut dst_entries: Vec<PathBuf> = std::fs::read_dir(dst)
        .map_err(|e| DeployError(format!("读取部署目录失败 {}: {e}", dst.display())))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_file())
        .collect();
    dst_entries.sort();
    for path in dst_entries {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if src_names.contains(&name) {
            continue;
        }
        if let Some(stem) = name.strip_suffix(".meta") {
            if src_names.contains(stem) {
                continue; // 产物仍在：保留 .meta
            }
        }
        std::fs::remove_file(&path)
            .map_err(|e| DeployError(format!("删除失败 {}: {e}", path.display())))?;
        logs.push(format!("[deploy] 删除 {}", path.display()));
        changed += 1;
    }

    // 新增/覆盖：内容不一致才写入
    let mut src_entries: Vec<PathBuf> = std::fs::read_dir(src)
        .map_err(|e| DeployError(format!("读取产物目录失败 {}: {e}", src.display())))?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_file())
        .collect();
    src_entries.sort();
    for path in src_entries {
        let target = dst.join(path.file_name().unwrap());
        let data = std::fs::read(&path)
            .map_err(|e| DeployError(format!("读取产物失败 {}: {e}", path.display())))?;
        let same = std::fs::read(&target).is_ok_and(|old| old == data);
        if !same {
            std::fs::write(&target, &data)
                .map_err(|e| DeployError(format!("写入失败 {}: {e}", target.display())))?;
            logs.push(format!("[deploy] 写入 {}", target.display()));
            changed += 1;
        }
    }
    Ok((changed, logs))
}

/// 按配置部署产物，返回写入/删除的文件总数与日志。
/// 未配置/未启用时跳过（changed = 0）。
pub fn deploy(config: &GlobalConfig, for_build: bool) -> Result<(usize, Vec<String>), DeployError> {
    if !config.deploy.enabled {
        return Ok((0, vec!["[deploy] 未配置或未启用，跳过".to_string()]));
    }
    let targets = config.resolve_deploy_targets(for_build);
    if targets.is_empty() {
        return Ok((0, vec!["[deploy] unity_project 未配置，跳过".to_string()]));
    }
    let mut total = 0;
    let mut logs = Vec::new();
    for (src, dst) in targets {
        logs.push(format!(
            "[deploy] 同步 {} → {}",
            src.display(),
            dst.display()
        ));
        let (changed, mut entries) = sync_dir(&src, &dst)?;
        total += changed;
        logs.append(&mut entries);
    }
    Ok((total, logs))
}
