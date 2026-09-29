//! 基线指纹（任务 1.1）：固定「可验收源码树 + 依赖 + Python 参照测试清单」。
//!
//! 输出 `native/docs/baseline/source-tree.json`。内容完全可重放（不含时间戳与绝对路径），
//! 因此 `xtask fingerprint --check` 做逐字节比对：任何人重新计算都必须得到同一份文件。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

/// 参与指纹的范围及排除项（相对仓库根目录）。
const SCOPES: &[(&str, &[&str])] = &[
    // 基线指纹自身与打包输出不参与（前者自引用，后者每次构建都变）。
    ("native", &["target", "dist", "source-tree.json"]),
    (
        "ct",
        &[
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        ],
    ),
    (
        "launcher",
        &["build", ".dart_tool", ".gradle", "ephemeral", ".idea"],
    ),
    ("openspec", &[]),
    (".github", &[]),
];

/// 逐文件清单只保留内核树，其余范围只留聚合摘要（避免基线文件过大）。
const FILE_LIST_SCOPE: &str = "native";

/// 构建噪声后缀不计入指纹。
const SKIP_SUFFIXES: &[&str] = &[
    ".pyc", ".pyo", ".pdb", ".obj", ".exe", ".dll", ".dylib", ".so",
];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn skipped(name: &str, excludes: &[&str]) -> bool {
    if excludes.iter().any(|skip| name.eq_ignore_ascii_case(skip)) {
        return true;
    }
    let lowered = name.to_ascii_lowercase();
    SKIP_SUFFIXES.iter().any(|suffix| lowered.ends_with(suffix))
}

/// 收集 scope 下参与指纹的文件：相对路径（正斜杠）→ 内容 sha256，按路径有序。
fn collect(scope_dir: &Path, excludes: &[&str]) -> Result<BTreeMap<String, String>> {
    let mut out = BTreeMap::new();
    let mut stack = vec![scope_dir.to_path_buf()];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).with_context(|| format!("读取 {}", dir.display()))? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().to_string();
            if skipped(&name, excludes) {
                continue;
            }
            let path = entry.path();
            let meta = std::fs::symlink_metadata(&path)?;
            if meta.is_symlink() {
                continue;
            }
            if meta.is_dir() {
                stack.push(path);
                continue;
            }
            let relative = path
                .strip_prefix(scope_dir)
                .context("目标不在 scope 内")?
                .to_string_lossy()
                .replace('\\', "/");
            out.insert(relative, sha256_hex(&std::fs::read(&path)?));
        }
    }
    Ok(out)
}

/// 把「路径\t哈希」按序喂给摘要器，得到该范围的聚合指纹。
fn scope_digest(entries: &BTreeMap<String, String>, sink: &mut Sha256) -> String {
    let mut local = Sha256::new();
    for (path, hash) in entries {
        let line = format!("{path}\t{hash}\n");
        local.update(line.as_bytes());
        sink.update(line.as_bytes());
    }
    format!("{:x}", local.finalize())
}

fn count_lines_with(file: &Path, prefix: &str) -> Result<usize> {
    let text = std::fs::read_to_string(file)?;
    Ok(text
        .lines()
        .filter(|line| {
            let trimmed = line.trim_start();
            trimmed.starts_with(prefix)
                || trimmed
                    .strip_prefix("async ")
                    .is_some_and(|rest| rest.starts_with(prefix))
        })
        .count())
}

fn relative_key(root: &Path, path: &Path) -> Result<String> {
    Ok(path
        .strip_prefix(root)
        .context("文件不在仓库内")?
        .to_string_lossy()
        .replace('\\', "/"))
}

/// 逐文件遍历（不进入被排除的目录）。
fn walk_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            walk_files(&path, out);
        } else {
            out.push(path);
        }
    }
}

/// Python 参照测试清单：`ct/tests/**.py` 的 `def test_` 数量。
fn python_test_inventory(root: &Path) -> Result<(Map<String, Value>, usize)> {
    let mut map = Map::new();
    let mut total = 0usize;
    let mut files = Vec::new();
    walk_files(&root.join("ct/tests"), &mut files);
    files.sort();
    for path in files {
        let is_python = path.extension().is_some_and(|ext| ext == "py");
        let is_test_name = path
            .file_name()
            .is_some_and(|name| name.to_string_lossy().starts_with("test_"));
        if !is_python {
            continue;
        }
        let count = if is_test_name {
            count_lines_with(&path, "def test_")?
        } else {
            0
        };
        map.insert(relative_key(root, &path)?, json!(count));
        total += count;
    }
    Ok((map, total))
}

/// 原生测试清单：`native/**/tests/*.rs` 的 `#[test]` 数量。
fn native_test_inventory(root: &Path) -> Result<(Map<String, Value>, usize)> {
    let mut map = Map::new();
    let mut total = 0usize;
    let mut files = Vec::new();
    walk_files(&root.join("native/tests"), &mut files);
    walk_files(&root.join("native/crates"), &mut files);
    files.sort();
    for path in files {
        if path.extension().is_some_and(|ext| ext == "rs")
            && path
                .parent()
                .is_some_and(|parent| parent.file_name().is_some_and(|name| name == "tests"))
        {
            let count = count_lines_with(&path, "#[test]")?;
            map.insert(relative_key(root, &path)?, json!(count));
            total += count;
        }
    }
    Ok((map, total))
}

fn command_line(program: &str, args: &[&str], cwd: Option<&Path>) -> Option<String> {
    let mut command = std::process::Command::new(program);
    command.args(args);
    if let Some(cwd) = cwd {
        command.current_dir(cwd);
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.is_empty() {
        return None;
    }
    Some(text)
}

fn reference_python(root: &Path) -> String {
    [
        "ct/.venv/Scripts/python.exe",
        "ct/.venv/bin/python",
        "ct/.venv/bin/python3",
    ]
    .iter()
    .map(|candidate| root.join(candidate))
    .find(|path| path.is_file())
    .and_then(|path| {
        let output = std::process::Command::new(path).arg("-V").output().ok()?;
        let text = format!(
            "{}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        Some(
            text.lines()
                .find(|line| line.contains("Python"))
                .unwrap_or("unavailable")
                .trim()
                .to_string(),
        )
    })
    .unwrap_or_else(|| "absent".to_string())
}

/// 计算基线指纹（无时间戳，可逐字节重放）。
pub fn compute() -> Result<Value> {
    let root = repo_root();
    let mut tree = Sha256::new();
    let mut scopes = Map::new();
    let mut file_count = 0usize;
    for (scope, excludes) in SCOPES {
        let dir = root.join(scope);
        if !dir.is_dir() {
            continue;
        }
        let entries = collect(&dir, excludes)?;
        let digest = scope_digest(&entries, &mut tree);
        let mut bytes = 0u64;
        let mut listed = Map::new();
        for (relative, hash) in &entries {
            bytes += std::fs::metadata(root.join(format!("{scope}/{relative}")))?.len();
            if *scope == FILE_LIST_SCOPE {
                listed.insert(relative.clone(), json!(hash));
            }
        }
        let mut value = json!({
            "files": entries.len(),
            "bytes": bytes,
            "sha256": digest,
        });
        if *scope == FILE_LIST_SCOPE {
            value
                .as_object_mut()
                .context("scope 摘要结构异常")?
                .insert("entries".to_string(), Value::Object(listed));
        }
        scopes.insert((*scope).to_string(), value);
        file_count += entries.len();
    }
    let (python_tests, python_total) = python_test_inventory(&root)?;
    let (native_tests, native_total) = native_test_inventory(&root)?;
    let cargo_lock =
        sha256_hex(&std::fs::read(root.join("native/Cargo.lock")).context("缺少 Cargo.lock")?);
    Ok(json!({
        "schema": "ct-source-tree/1",
        "git": {
            "commit": command_line("git", &["rev-parse", "HEAD"], Some(&root)).unwrap_or_default(),
            "dirtyPaths": command_line("git", &["status", "--porcelain"], Some(&root))
                .map(|text| text.lines().count()),
        },
        "toolchain": {
            "rustc": command_line("rustc", &["-V"], None).unwrap_or_else(|| "unavailable".to_string()),
            "cargoLockSha256": cargo_lock,
            "referencePython": reference_python(&root),
        },
        "tree": {
            "sha256": format!("{:x}", tree.finalize()),
            "files": file_count,
        },
        "scopes": scopes,
        "testInventory": {
            "pythonFiles": python_tests,
            "nativeFiles": native_tests,
            "totals": {
                "pythonTestFunctions": python_total,
                "nativeTestFunctions": native_total,
            },
        },
    }))
}

fn baseline_path() -> PathBuf {
    repo_root().join("native/docs/baseline/source-tree.json")
}

fn render(value: &Value) -> Result<String> {
    let mut text = serde_json::to_string_pretty(value).context("序列化基线指纹")?;
    text.push('\n');
    Ok(text)
}

pub fn run(check: bool) -> Result<()> {
    let value = compute()?;
    let rendered = render(&value)?;
    let path = baseline_path();
    if check {
        let existing = std::fs::read_to_string(&path).with_context(|| {
            format!(
                "缺少基线指纹 {}，先运行 `cargo run -p ct-xtask -- fingerprint`",
                path.display()
            )
        })?;
        let recorded: Value = serde_json::from_str(&existing).context("基线指纹不是合法 JSON")?;
        // 只比对源码树内容：commit/脏路径数/工具链/参照 Python 版本随环境变化，不参与判定。
        let mut mismatched = Vec::new();
        for key in ["tree", "scopes", "testInventory"] {
            if recorded[key] != value[key] {
                mismatched.push(key);
            }
        }
        if mismatched.is_empty() {
            println!(
                "基线指纹一致：{} 个文件，树摘要 {}",
                value["tree"]["files"].as_u64().unwrap_or_default(),
                value["tree"]["sha256"].as_str().unwrap_or_default()
            );
            return Ok(());
        }
        bail!(
            "基线指纹与当前源码树不一致（差异字段：{}），需要重新生成 source-tree.json",
            mismatched.join(", ")
        );
    }
    std::fs::create_dir_all(path.parent().context("基线路径缺少目录")?)?;
    std::fs::write(&path, &rendered)?;
    println!(
        "已写入 {}（{} 个文件，树摘要 {}）",
        path.display(),
        value["tree"]["files"].as_u64().unwrap_or_default(),
        value["tree"]["sha256"].as_str().unwrap_or_default()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_is_reproducible() {
        let first = render(&compute().expect("计算基线")).expect("序列化");
        let second = render(&compute().expect("计算基线")).expect("序列化");
        assert_eq!(first, second, "同一源码树两次计算必须逐字节一致");
    }

    #[test]
    fn fingerprint_pins_both_trees() {
        let value = compute().expect("计算基线");
        // `ct/` 只是历史参照实现：它随时可能不在工作树里，指纹仍须成立。
        let mut scopes = vec!["native", "openspec"];
        if repo_root().join("ct").is_dir() {
            scopes.push("ct");
        }
        for scope in scopes {
            assert!(
                value["scopes"][scope]["files"].as_u64().unwrap_or(0) > 0,
                "范围 {scope} 不应为空"
            );
            assert_eq!(
                value["scopes"][scope]["sha256"]
                    .as_str()
                    .unwrap_or_default()
                    .len(),
                64
            );
        }
        assert!(value["scopes"]["native"]["entries"]
            .as_object()
            .is_some_and(|entries| !entries.is_empty()));
        assert!(value["toolchain"]["cargoLockSha256"]
            .as_str()
            .is_some_and(|hash| hash.len() == 64));
        // Python 参照实现删除后清单会是 0：只影响留档，不影响指纹成立。
        let python_fns = value["testInventory"]["totals"]["pythonTestFunctions"]
            .as_u64()
            .unwrap_or(0);
        assert!(
            python_fns == 0 || python_fns > 500,
            "Python 参照测试清单异常：{python_fns}"
        );
        assert!(
            value["testInventory"]["totals"]["nativeTestFunctions"]
                .as_u64()
                .unwrap_or(0)
                > 200,
            "原生测试清单应覆盖内核验收测试"
        );
    }

    #[test]
    fn native_entries_match_disk_hashes() {
        let value = compute().expect("计算基线");
        let entries = value["scopes"]["native"]["entries"]
            .as_object()
            .expect("native 逐文件清单");
        let root = repo_root();
        for (relative, hash) in entries.iter().take(40) {
            let bytes = std::fs::read(root.join(format!("native/{relative}")))
                .unwrap_or_else(|_| panic!("清单里的文件应存在: {relative}"));
            assert_eq!(
                &sha256_hex(&bytes),
                hash.as_str().expect("哈希字符串"),
                "{relative}"
            );
        }
    }
}
