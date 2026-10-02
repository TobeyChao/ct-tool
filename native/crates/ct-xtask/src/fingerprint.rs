//! 基线指纹（任务 1.1）：固定「可验收原生/Web 源码树 + 依赖 + 冻结历史测试清单」。
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
        "web",
        &["node_modules", "test-results", "playwright-report"],
    ),
    (
        "launcher",
        &[
            "build",
            ".dart_tool",
            ".gradle",
            "ephemeral",
            ".idea",
            ".flutter-plugins",
            ".flutter-plugins-dependencies",
            // Flutter golden-test diagnostics are local outputs, not source fixtures.
            "test/failures",
        ],
    ),
    ("openspec", &[]),
    (".github", &[]),
    (
        "test-proj",
        &["bin", "obj", "node_modules", ".venv", "__pycache__", "_ws"],
    ),
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
    if name.eq_ignore_ascii_case(".DS_Store") {
        return true;
    }
    if excludes.iter().any(|skip| name.eq_ignore_ascii_case(skip)) {
        return true;
    }
    let lowered = name.to_ascii_lowercase();
    SKIP_SUFFIXES.iter().any(|suffix| lowered.ends_with(suffix))
}

// Git applies CRLF to platform scripts on checkout; git archive stores LF.
// Canonicalize only these scripts, keeping frozen inputs/oracles byte-sensitive.
fn source_bytes(path: &Path) -> Result<Vec<u8>> {
    let bytes = std::fs::read(path)?;
    if path
        .extension()
        .is_some_and(|ext| ext == "ps1" || ext == "bat" || ext == "cmd")
    {
        return Ok(String::from_utf8(bytes)?.replace("\r\n", "\n").into_bytes());
    }
    Ok(bytes)
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
            let relative = path
                .strip_prefix(scope_dir)
                .context("目标不在 scope 内")?
                .to_string_lossy()
                .replace('\\', "/");
            if excludes
                .iter()
                .any(|skip| relative.eq_ignore_ascii_case(skip))
            {
                continue;
            }
            let meta = std::fs::symlink_metadata(&path)?;
            if meta.is_symlink() {
                continue;
            }
            if meta.is_dir() {
                stack.push(path);
                continue;
            }
            out.insert(relative, sha256_hex(&source_bytes(&path)?));
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

/// 原生测试清单：集成测试和 crate 内的单元测试。
fn native_test_inventory(root: &Path) -> Result<(Map<String, Value>, usize)> {
    let mut map = Map::new();
    let mut total = 0usize;
    let mut files = Vec::new();
    walk_files(&root.join("native/tests"), &mut files);
    walk_files(&root.join("native/crates"), &mut files);
    files.sort();
    for path in files {
        if path.extension().is_some_and(|ext| ext == "rs") {
            let count = count_lines_with(&path, "#[test]")?;
            map.insert(relative_key(root, &path)?, json!(count));
            total += count;
        }
    }
    Ok((map, total))
}

/// 运行命令并返回裁剪后的标准输出；只有执行失败或非零退出才是 `None`。
///
/// 空输出是有意义的结果：`git status --porcelain` 在干净工作树上什么都不打印，
/// 而那仍代表「0 条脏路径」。把它折叠成 `None` 会让干净工作树生成 `dirtyPaths: null`
/// 的指纹，直接被 `baseline_fingerprint_is_pinned_and_complete` 拒绝。
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
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// 计算基线指纹（无时间戳，可逐字节重放）。
#[cfg(test)]
fn compute() -> Result<Value> {
    compute_at(&repo_root())
}

fn compute_at(root: &Path) -> Result<Value> {
    let mut tree = Sha256::new();
    let mut scopes = Map::new();
    let mut file_count = 0usize;
    for (scope, excludes) in SCOPES {
        let dir = root.join(scope);
        if !dir.is_dir() {
            bail!("缺少必要原生源码范围：{}", dir.display());
        }
        let entries = collect(&dir, excludes)?;
        let digest = scope_digest(&entries, &mut tree);
        let mut bytes = 0u64;
        let mut listed = Map::new();
        for (relative, hash) in &entries {
            bytes += source_bytes(&root.join(format!("{scope}/{relative}")))?.len() as u64;
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
    let historical = ct_test_support::reference_inventory::read(root)?;
    let historical_tests: Map<String, Value> = historical
        .files
        .iter()
        .map(|(name, file)| (name.clone(), json!(file.functions.len())))
        .collect();
    let (native_tests, native_total) = native_test_inventory(root)?;
    let cargo_lock =
        sha256_hex(&std::fs::read(root.join("native/Cargo.lock")).context("缺少 Cargo.lock")?);
    Ok(json!({
        "schema": "ct-source-tree/2",
        "git": {
            "commit": command_line("git", &["rev-parse", "HEAD"], Some(root)).unwrap_or_default(),
            "dirtyPaths": command_line("git", &["status", "--porcelain"], Some(root))
                .map(|text| text.lines().count()),
        },
        "toolchain": {
            "rustc": command_line("rustc", &["-V"], None).unwrap_or_else(|| "unavailable".to_string()),
            "cargoLockSha256": cargo_lock,
            "pythonRuntimeRequired": false,
        },
        "tree": {
            "sha256": format!("{:x}", tree.finalize()),
            "files": file_count,
        },
        "scopes": scopes,
        "testInventory": {
            "historicalPythonFiles": historical_tests,
            "historicalSource": "native/docs/baseline/reference-tests.json",
            "nativeFiles": native_tests,
            "totals": {
                "historicalPythonTestFunctions": historical.total_test_functions,
                "nativeTestFunctions": native_total,
            },
        },
    }))
}

fn render(value: &Value) -> Result<String> {
    let mut text = serde_json::to_string_pretty(value).context("序列化基线指纹")?;
    text.push('\n');
    Ok(text)
}

/// 与已提交快照相比变化的字段（commit/脏路径数/工具链随环境变化，不参与比对）。
fn changed_fields(recorded: &Value, current: &Value) -> Vec<&'static str> {
    ["tree", "scopes", "testInventory"]
        .into_iter()
        .filter(|key| recorded[*key] != current[*key])
        .collect()
}

/// 相对已提交快照的漂移说明：只用于记录，不参与判定。
fn drift_summary(recorded: &Value, current: &Value) -> String {
    let changed = changed_fields(recorded, current);
    if changed.is_empty() {
        return format!(
            "与快照一致（{} 个文件，树摘要 {}）",
            current["tree"]["files"].as_u64().unwrap_or_default(),
            current["tree"]["sha256"].as_str().unwrap_or_default()
        );
    }
    format!(
        "快照已落后（{}）：快照 {} 个文件 / {} → 当前 {} 个文件 / {}",
        changed.join(", "),
        recorded["tree"]["files"].as_u64().unwrap_or_default(),
        recorded["tree"]["sha256"].as_str().unwrap_or_default(),
        current["tree"]["files"].as_u64().unwrap_or_default(),
        current["tree"]["sha256"].as_str().unwrap_or_default(),
    )
}

/// 仓库内验收快照的相对路径（错误与漂移提示只暴露这个稳定标签）。
const SNAPSHOT_RELATIVE: &str = "native/docs/baseline/source-tree.json";

pub fn run(check: bool, source_root: Option<PathBuf>, out: Option<PathBuf>) -> Result<()> {
    let root = source_root.unwrap_or_else(repo_root);
    let value = compute_at(&root)?;
    let rendered = render(&value)?;
    // 仓库里的验收快照：验收/发布前重算并提交，日常提交不强制与源码树同步。
    let snapshot = root.join(SNAPSHOT_RELATIVE);
    if check {
        let existing = std::fs::read_to_string(&snapshot).with_context(|| {
            format!(
                "缺少基线指纹 {SNAPSHOT_RELATIVE}，先运行 `cargo run -p ct-xtask -- fingerprint`"
            )
        })?;
        let recorded: Value = serde_json::from_str(&existing).context("基线指纹不是合法 JSON")?;
        let mismatched = changed_fields(&recorded, &value);
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
    let path = out.unwrap_or_else(|| snapshot.clone());
    std::fs::create_dir_all(path.parent().context("基线路径缺少目录")?)?;
    std::fs::write(&path, &rendered)?;
    println!(
        "已写入 {}（{} 个文件，树摘要 {}）",
        path.display(),
        value["tree"]["files"].as_u64().unwrap_or_default(),
        value["tree"]["sha256"].as_str().unwrap_or_default()
    );
    if path != snapshot {
        match std::fs::read_to_string(&snapshot).map(|text| serde_json::from_str::<Value>(&text)) {
            Ok(Ok(recorded)) => println!(
                "验收快照 {SNAPSHOT_RELATIVE}：{}",
                drift_summary(&recorded, &value)
            ),
            Ok(Err(_)) => println!("验收快照 {SNAPSHOT_RELATIVE} 不是合法 JSON，未参与比对"),
            Err(_) => println!("未找到验收快照 {SNAPSHOT_RELATIVE}"),
        }
    }
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
    fn drift_summary_reports_the_fields_that_moved() {
        let current = compute().expect("计算基线");
        assert_eq!(changed_fields(&current, &current), Vec::<&str>::new());
        assert!(drift_summary(&current, &current).contains("与快照一致"));

        let mut stale = current.clone();
        stale["tree"]["files"] = json!(1);
        stale["tree"]["sha256"] = json!("0".repeat(64));
        assert_eq!(changed_fields(&stale, &current), vec!["tree"]);
        let note = drift_summary(&stale, &current);
        assert!(note.contains("快照已落后（tree）"), "{note}");
        assert!(note.contains("1 个文件"), "{note}");
    }

    #[test]
    fn git_metadata_is_optional_but_a_clean_tree_still_counts_zero() {
        let value = compute().expect("计算基线");
        let commit = value["git"]["commit"].as_str().unwrap_or_default();
        let dirty_paths = &value["git"]["dirtyPaths"];
        // 干净工作树的 `git status --porcelain` 没有输出，但它仍是 0 条脏路径；
        // 只有完全没有 Git 元数据时才允许 commit 与 dirtyPaths 同时缺省。
        assert!(
            dirty_paths.is_u64() || (commit.is_empty() && dirty_paths.is_null()),
            "有 Git 元数据时脏路径数必须是数字（干净工作树记 0），实际 {dirty_paths}"
        );
    }

    #[test]
    fn fingerprint_pins_supported_trees_and_frozen_history() {
        let value = compute().expect("计算基线");
        let scopes = [
            "native",
            "web",
            "launcher",
            "openspec",
            ".github",
            "test-proj",
        ];
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
        assert_eq!(
            value["testInventory"]["totals"]["historicalPythonTestFunctions"],
            690
        );
        assert_eq!(
            value["testInventory"]["historicalPythonFiles"]
                .as_object()
                .unwrap()
                .len(),
            85
        );
        assert_eq!(value["toolchain"]["pythonRuntimeRequired"], false);
        assert!(value["scopes"].get("ct").is_none());
        assert!(
            value["testInventory"]["totals"]["nativeTestFunctions"]
                .as_u64()
                .unwrap_or(0)
                > 200,
            "原生测试清单应覆盖内核验收测试"
        );
    }

    #[test]
    fn retired_tree_does_not_change_fingerprint_or_test_inventory() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        for (scope, _) in SCOPES {
            std::fs::create_dir_all(root.join(scope)).unwrap();
        }
        for relative in [
            "native/Cargo.lock",
            "native/docs/baseline/reference-tests.json",
            "native/docs/baseline/reference-tests.sha256",
            "native/docs/baseline/source/source-tree-native-origin.json",
        ] {
            let target = root.join(relative);
            std::fs::create_dir_all(target.parent().unwrap()).unwrap();
            std::fs::copy(repo_root().join(relative), target).unwrap();
        }
        let without = compute_at(root).unwrap();
        std::fs::create_dir_all(root.join("ct/tests")).unwrap();
        std::fs::write(
            root.join("ct/tests/test_fake.py"),
            "def test_unrelated(): pass",
        )
        .unwrap();
        std::fs::create_dir_all(root.join("ct/.venv/bin")).unwrap();
        std::fs::write(root.join("ct/.venv/bin/python"), "must never execute").unwrap();
        let with = compute_at(root).unwrap();
        for key in ["tree", "scopes", "testInventory"] {
            assert_eq!(without[key], with[key], "旧 ct/ 的存在不能改变 {key}");
        }
        assert_eq!(
            with["testInventory"]["totals"]["historicalPythonTestFunctions"],
            690
        );
    }

    #[test]
    fn finder_metadata_does_not_change_source_fingerprint() {
        let temp = tempfile::tempdir().unwrap();
        std::fs::write(temp.path().join("source.rs"), "source").unwrap();
        let before = collect(temp.path(), &[]).unwrap();
        std::fs::write(temp.path().join(".DS_Store"), "Finder metadata").unwrap();
        assert_eq!(before, collect(temp.path(), &[]).unwrap());
        assert_eq!(before.len(), 1);
    }

    #[test]
    fn launcher_golden_diagnostics_do_not_change_source_fingerprint() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path();
        let excludes = SCOPES
            .iter()
            .find(|(scope, _)| *scope == "launcher")
            .unwrap()
            .1;
        for relative in ["test/goldens", "lib/failures"] {
            std::fs::create_dir_all(root.join(relative)).unwrap();
        }
        std::fs::write(root.join("test/goldens/workbench.png"), "golden source").unwrap();
        std::fs::write(root.join("lib/failures/state.dart"), "source").unwrap();
        let before = collect(root, excludes).unwrap();
        assert_eq!(before.len(), 2, "基准图片与同名源码目录仍参与指纹");

        std::fs::create_dir_all(root.join("test/failures/nested")).unwrap();
        std::fs::write(root.join("test/failures/testImage.png"), "diagnostic").unwrap();
        std::fs::write(root.join("test/failures/nested/diff.png"), "diagnostic").unwrap();
        assert_eq!(before, collect(root, excludes).unwrap());

        std::fs::write(root.join("test/goldens/workbench.png"), "changed golden").unwrap();
        assert_ne!(before, collect(root, excludes).unwrap());
    }

    #[test]
    fn git_script_line_endings_are_canonical_but_oracles_are_exact() {
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("build.ps1");
        std::fs::write(&script, "line\r\n").unwrap();
        assert_eq!(source_bytes(&script).unwrap(), b"line\n");
        let oracle = temp.path().join("reference.txt");
        std::fs::write(&oracle, "line\r\n").unwrap();
        assert_eq!(source_bytes(&oracle).unwrap(), b"line\r\n");
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
