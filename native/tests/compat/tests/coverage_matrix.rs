//! 业务兼容矩阵的机器校验（任务 1.1 / 6.12）。
//!
//! `native/docs/baseline/compat-matrix.json` 是 `coverage.md` 表格的可执行形式：
//! 每行都必须能在这里被自动检查——冻结 main 测试清单完整且被映射、
//! 原生验收锚点文件存在且含 `#[test]`/`@test(`、点名的 `文件::函数` 锚点确实定义在该文件里，
//! 并且历史测试（Web/架构目录另有验收）不因旧工程缺席而跳过。

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use serde_json::Value;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..")
}

fn read_text(root: &Path, relative: &str) -> String {
    let path = root.join(relative);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("读取 {relative} 失败: {e}"))
}

fn read_json(root: &Path, relative: &str) -> Value {
    let text = read_text(root, relative);
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("解析 {relative} 失败: {e}"))
}

/// coverage.md 里业务兼容表格的数据行（去掉表头与分隔行）。
fn coverage_rows(root: &Path) -> Vec<[String; 3]> {
    let text = read_text(root, "openspec/changes/rust-native-core/coverage.md");
    text.lines()
        .filter_map(|line| {
            let line = line.trim();
            if !line.starts_with('|') {
                return None;
            }
            let cells: Vec<String> = line
                .trim_matches('|')
                .split('|')
                .map(|cell| cell.trim().to_string())
                .collect();
            if cells.len() != 3
                || cells[0].starts_with("现有能力")
                || cells[0].chars().all(|c| c == '-' || c.is_whitespace())
            {
                return None;
            }
            Some([cells[0].clone(), cells[1].clone(), cells[2].clone()])
        })
        .collect()
}

fn test_targets(matrix: &Value, field: &str) -> Vec<String> {
    matrix["rows"]
        .as_array()
        .expect("rows 应为数组")
        .iter()
        .flat_map(|row| {
            row[field]
                .as_array()
                .cloned()
                .unwrap_or_default()
                .into_iter()
                .map(|value| value.as_str().expect("字符串").to_string())
                .collect::<Vec<String>>()
        })
        .collect()
}

#[test]
fn matrix_rows_match_coverage_table_row_by_row() {
    let root = repo_root();
    let matrix = read_json(&root, "native/docs/baseline/compat-matrix.json");
    let table = coverage_rows(&root);
    let rows = matrix["rows"].as_array().expect("rows");
    assert_eq!(
        rows.len(),
        table.len(),
        "矩阵行数与 coverage.md 表格行数不一致"
    );
    assert!(rows.len() >= 20, "矩阵应覆盖全部现有能力行");
    for (index, row) in rows.iter().enumerate() {
        assert_eq!(
            row["capability"].as_str().expect("capability"),
            table[index][0],
            "第 {} 行的能力名与 coverage.md 不一致",
            index + 1
        );
        assert_eq!(
            row["behaviors"].as_str().expect("behaviors"),
            table[index][1],
            "第 {} 行的必须承接行为与 coverage.md 不一致",
            index + 1
        );
        let id = row["id"].as_str().expect("id");
        assert!(!id.is_empty(), "每行都要有稳定 id");
        assert!(
            !row["change"].as_str().expect("change").is_empty(),
            "{id} 缺少负责 change"
        );
    }
    let mut ids = rows
        .iter()
        .map(|row| row["id"].as_str().expect("id").to_string())
        .collect::<Vec<_>>();
    let sorted = {
        ids.sort();
        ids.clone()
    };
    assert_eq!(ids, sorted, "行 id 必须唯一且有序");
}

fn verify_reference_mapping(root: &Path) {
    let matrix = read_json(root, "native/docs/baseline/compat-matrix.json");
    let historical =
        ct_test_support::reference_inventory::read(root).expect("冻结 main 测试清单完整");
    let excluded = matrix["excludedPythonDirs"]
        .as_array()
        .expect("excludedPythonDirs")
        .iter()
        .map(|value| value.as_str().expect("目录"))
        .collect::<Vec<_>>();
    let discovered = historical
        .files
        .iter()
        .filter(|(name, file)| {
            !file.functions.is_empty() && !excluded.iter().any(|skip| name.starts_with(skip))
        })
        .map(|(name, _)| name.clone())
        .collect::<BTreeSet<_>>();
    let pinned = test_targets(&matrix, "pythonTests")
        .into_iter()
        .collect::<BTreeSet<_>>();
    assert!(discovered.len() >= 55, "冻结 main 测试清单范围异常");
    assert_eq!(
        discovered, pinned,
        "每个冻结 main 测试文件必须有承接，不能缺失或虚构引用"
    );
}

#[test]
fn every_python_reference_test_is_pinned() {
    verify_reference_mapping(&repo_root());
}

#[test]
fn frozen_reference_mapping_survives_absent_retired_tree_and_rejects_corruption() {
    let temp = tempfile::tempdir().unwrap();
    for relative in [
        "native/docs/baseline/compat-matrix.json",
        "native/docs/baseline/reference-tests.json",
        "native/docs/baseline/reference-tests.sha256",
        "native/docs/baseline/source/source-tree-native-origin.json",
    ] {
        let target = temp.path().join(relative);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::copy(repo_root().join(relative), target).unwrap();
    }
    assert!(!temp.path().join("ct").exists());
    verify_reference_mapping(temp.path());
    let path = temp
        .path()
        .join("native/docs/baseline/reference-tests.json");
    let mut data = std::fs::read(&path).unwrap();
    data.push(b' ');
    std::fs::write(path, data).unwrap();
    let error = ct_test_support::reference_inventory::read(temp.path())
        .err()
        .expect("损坏基线必须失败");
    assert!(error.to_string().contains("SHA-256"), "{error}");
}

#[test]
fn native_anchors_exist_and_carry_tests() {
    let root = repo_root();
    let matrix = read_json(&root, "native/docs/baseline/compat-matrix.json");
    let rows = matrix["rows"].as_array().expect("rows");
    let statuses = matrix["statusVocabulary"]
        .as_array()
        .expect("statusVocabulary")
        .iter()
        .map(|value| value.as_str().expect("字符串").to_string())
        .collect::<Vec<_>>();
    let mut families = BTreeSet::new();
    for row in rows {
        let id = row["id"].as_str().expect("id");
        let status = row["status"].as_str().expect("status");
        assert!(
            statuses.iter().any(|known| known == status),
            "{id} 使用了未登记的状态 {status}"
        );
        families.insert(row["family"].as_str().expect("family").to_string());
        assert!(
            !row["owner"].as_str().expect("owner").is_empty(),
            "{id} 缺少 owner"
        );
        let targets = row["nativeTests"]
            .as_array()
            .expect("nativeTests")
            .iter()
            .map(|value| value.as_str().expect("字符串").to_string())
            .collect::<Vec<_>>();
        assert!(
            !targets.is_empty() || status == "ui-change",
            "{id} 既没有原生验收锚点，也不是纯界面承接行"
        );
        for relative in &targets {
            let text = read_text(&root, relative);
            let has_tests = if relative.ends_with(".rs") {
                text.contains("#[test]")
            } else if relative.ends_with(".dart") {
                text.lines().any(|line| {
                    let trimmed = line.trim_start();
                    trimmed.starts_with("test(")
                        || trimmed.starts_with("testWidgets(")
                        || trimmed.starts_with("group(")
                })
            } else {
                panic!("{id} 引用了不支持的锚点类型 {relative}");
            };
            assert!(has_tests, "{relative} 里没有任何测试");
        }
        for anchor in row["nativeAnchors"]
            .as_array()
            .expect("nativeAnchors")
            .iter()
            .map(|value| value.as_str().expect("字符串").to_string())
            .collect::<Vec<_>>()
        {
            let (file, name) = anchor
                .split_once("::")
                .unwrap_or_else(|| panic!("{id} 的锚点 {anchor} 应写成 文件::测试函数"));
            let text = read_text(&root, file);
            assert!(
                targets.iter().any(|target| target == file),
                "{id} 的点名锚点 {anchor} 所在文件未列进 nativeTests"
            );
            assert!(
                text.contains(&format!("fn {name}")),
                "{id} 的点名锚点 {anchor} 在 {file} 里不存在"
            );
            assert!(
                text.contains(&format!("fn {name}(")),
                "{id} 的点名锚点 {anchor} 签名异常"
            );
        }
    }
    for family in matrix["requiredFamilies"]
        .as_array()
        .expect("requiredFamilies")
        .iter()
        .map(|value| value.as_str().expect("字符串").to_string())
        .collect::<Vec<_>>()
    {
        assert!(
            families.contains(&family),
            "兼容矩阵必须覆盖 {family} 这一现行测试族"
        );
    }
}

#[test]
fn baseline_fingerprint_is_pinned_and_complete() {
    let root = repo_root();
    let matrix = read_json(&root, "native/docs/baseline/compat-matrix.json");
    let fingerprint_relative = matrix["baselineFingerprint"]
        .as_str()
        .expect("baselineFingerprint");
    let fingerprint = read_json(&root, fingerprint_relative);
    assert_eq!(
        fingerprint["schema"].as_str().expect("schema"),
        "ct-source-tree/2"
    );
    assert!(fingerprint["git"]["commit"].is_string());
    assert!(
        fingerprint["git"]["dirtyPaths"].is_number()
            || (fingerprint["git"]["commit"] == "" && fingerprint["git"]["dirtyPaths"].is_null()),
        "源码包可以没有 Git 元数据；源码摘要和完整测试清单仍须成立"
    );
    assert_eq!(
        fingerprint["tree"]["sha256"]
            .as_str()
            .expect("树摘要")
            .len(),
        64,
        "树摘要长度异常"
    );
    assert!(fingerprint["tree"]["files"].as_u64().expect("文件数") > 500);
    assert!(
        fingerprint["scopes"].get("ct").is_none(),
        "当前指纹不能依赖已退役源码树"
    );
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
            fingerprint["scopes"][scope]["sha256"]
                .as_str()
                .is_some_and(|hash| hash.len() == 64),
            "缺少 {scope} 范围摘要"
        );
    }
    assert_eq!(
        fingerprint["toolchain"]["cargoLockSha256"]
            .as_str()
            .expect("Cargo.lock 摘要")
            .len(),
        64
    );
    // 指纹始终保留全部冻结 main 历史测试；旧 ct/ 缺席不能使清单归零。
    assert_eq!(
        fingerprint["testInventory"]["totals"]["historicalPythonTestFunctions"],
        690
    );
    let inventory = fingerprint["testInventory"]["historicalPythonFiles"]
        .as_object()
        .expect("historicalPythonFiles");
    let excluded = matrix["excludedPythonDirs"]
        .as_array()
        .expect("excludedPythonDirs")
        .iter()
        .filter_map(|value| value.as_str())
        .collect::<Vec<_>>();
    let pinned = BTreeSet::from_iter(test_targets(&matrix, "pythonTests"));
    for (relative, count) in inventory {
        let count = count.as_u64().unwrap_or(0);
        if count == 0 || excluded.iter().any(|skip| relative.starts_with(skip)) {
            continue;
        }
        assert!(
            pinned.contains(relative),
            "基线指纹里的 {relative}（{count} 个测试）没有被矩阵承接"
        );
    }
}

#[test]
fn explicit_acceptance_checks_are_mapped() {
    let root = repo_root();
    let matrix = read_json(&root, "native/docs/baseline/compat-matrix.json");
    let historical = ct_test_support::reference_inventory::read(&root).unwrap();
    let deltas = matrix["mainReferenceDeltas"]
        .as_array()
        .expect("mainReferenceDeltas");
    assert_eq!(
        deltas.len(),
        3,
        "main 比旧 native 基线多出的三项检查不得遗漏"
    );
    for delta in deltas {
        let (file, name) = delta["source"].as_str().unwrap().split_once("::").unwrap();
        assert!(historical.files[file]
            .functions
            .iter()
            .any(|item| item == name));
        let (file, name) = delta["target"].as_str().unwrap().split_once("::").unwrap();
        assert!(read_text(&root, file).contains(&format!("fn {name}")));
        assert!(root.join(delta["evidence"].as_str().unwrap()).is_file());
    }
    let checks = matrix["explicitChecks"]
        .as_array()
        .expect("explicitChecks 应为数组");
    assert!(checks.len() >= 8, "6.12 要求逐条显式检查");
    let mut mentions = String::new();
    for check in checks {
        let item = check["item"].as_str().expect("item");
        let anchor = check["anchor"].as_str().expect("anchor");
        assert!(
            !check["verdict"].as_str().expect("verdict").is_empty(),
            "{item} 缺少验收结论"
        );
        assert!(
            !check["note"].as_str().expect("note").is_empty(),
            "{item} 缺少依据说明"
        );
        mentions.push_str(item);
        mentions.push('\n');
        if let Some((file, name)) = anchor.split_once("::") {
            let text = read_text(&root, file);
            assert!(
                text.contains(&format!("fn {name}")),
                "{item} 的锚点 {anchor} 不存在"
            );
        } else {
            assert!(root.join(anchor).is_file(), "{item} 的锚点 {anchor} 不存在");
        }
    }
    for required in [
        "server_only",
        "语言切换",
        ".meta",
        "for-build",
        "缺源",
        "缓存",
        "Python",
        "不迁移",
    ] {
        assert!(
            mentions.contains(required),
            "显式检查项必须覆盖 {required}（6.12 要求）"
        );
    }
    let excluded = matrix["excludedSpecs"]
        .as_array()
        .expect("excludedSpecs 应为数组");
    assert!(excluded.len() >= 10, "未迁移项必须逐条给出排除理由");
    for row in excluded {
        assert!(!row["item"].as_str().expect("item").is_empty());
        assert!(
            row["reason"].as_str().expect("reason").chars().count() >= 12,
            "未迁移项 {} 的理由过于含糊",
            row["item"].as_str().unwrap_or_default()
        );
    }
}
