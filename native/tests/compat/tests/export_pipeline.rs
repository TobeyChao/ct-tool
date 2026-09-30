//! 导出 pipeline 对照（rust-native-core 任务 4.3/4.4/4.5）：
//! Python golden 逐字节对照、构建期间输入变化阻止发布、deploy 同步语义、
//! 完成策略与成功账本。

use std::path::{Path, PathBuf};

use ct_app::export::{
    run_export, run_pipeline, run_pipeline_with_reporter, CompletionPolicy, ExportError,
    ExportRequest, Reporter,
};
use ct_app::export_inputs::{capture_export_inputs, verify_inputs_unchanged};
use ct_app::task::CancelFlag;

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline")
}

fn copy_workspace(dst: &Path) {
    let src = fixture_dir().join("workspace");
    copy_dir(&src, dst);
}

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).unwrap();
    for entry in std::fs::read_dir(src).unwrap() {
        let entry = entry.unwrap();
        let name = entry.file_name().to_string_lossy().to_string();
        // 产物/缓存不带入：每个用例从输入工作区全新导出
        if name == "output" || name == "cache" {
            continue;
        }
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).unwrap();
        }
    }
}

fn collect_files(root: &Path, base: &Path) -> Vec<(String, Vec<u8>)> {
    let mut out = Vec::new();
    if !root.exists() {
        return out;
    }
    for entry in std::fs::read_dir(root).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        if path.is_dir() {
            out.extend(collect_files(&path, base));
        } else {
            let rel = path
                .strip_prefix(base)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            out.push((rel, std::fs::read(&path).unwrap()));
        }
    }
    out
}

struct CancelAtPublish(CancelFlag);

impl Reporter for CancelAtPublish {
    fn log(&self, _line: &str, _err: bool) {}

    fn stage(&self, name: &str, _index: usize, _total: usize) {
        if name == "publish" {
            self.0.cancel();
        }
    }
}

#[test]
fn cancellation_before_publish_keeps_output_unpublished() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    let cancel = CancelFlag::new();
    let signal = cancel.clone();
    let hook = |stage: &str| {
        if stage == "pre_publish" {
            signal.cancel();
        }
        Ok(())
    };
    let error = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: true,
        },
        Some(&cancel),
        Some(&hook),
    )
    .unwrap_err();
    assert!(matches!(error, ExportError::Cancelled(_)), "{error}");
    assert!(!root.join("output").exists());
    assert!(!root.join(".ct/export-publication.json").exists());
}

#[test]
fn cancellation_after_publish_boundary_preserves_success() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    let cancel = CancelFlag::new();
    let reporter = CancelAtPublish(cancel.clone());
    let result = run_pipeline_with_reporter(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: true,
        },
        Some(&cancel),
        None,
        Some(&reporter),
    )
    .unwrap();
    assert!(cancel.requested());
    assert!(!cancel.observed());
    assert_eq!(result.tables, 1);
    assert!(root.join("output/binary/data_en.bin").exists());
}

#[test]
fn pipeline_matches_python_byte_for_byte() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);

    let result = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        None,
    )
    .unwrap();
    assert_eq!(result.tables, 1);
    assert_eq!(result.languages, vec!["zh".to_string(), "en".to_string()]);
    assert_eq!(result.excel_hashes.len(), 1);
    assert_eq!(result.bundle_hashes.len(), 2);

    // 产物集合与 golden 一致（文件名按小写比较：Python 在 Windows 的 normcase
    // 会把发布路径小写化；Rust 保留原始大小写——内容逐字节对照不受影响）
    let golden_dir = fixture_dir().join("golden");
    let golden = collect_files(&golden_dir, &golden_dir);
    // 键与 golden 同形（相对工作区根的 posix 路径）
    let mut actual = collect_files(&root.join("output"), &root);
    actual.extend(collect_files(&root.join("excel/layout_manifests"), &root));
    let actual_map: std::collections::HashMap<String, Vec<u8>> = actual
        .into_iter()
        .map(|(rel, bytes)| (rel.to_lowercase(), bytes))
        .collect();
    assert_eq!(golden.len(), actual_map.len(), "产物文件数不一致");
    for (rel, bytes) in &golden {
        let rel_key = rel.to_lowercase();
        let actual_bytes = actual_map
            .get(&rel_key)
            .unwrap_or_else(|| panic!("缺少产物 {rel}"));
        assert_eq!(actual_bytes, bytes, "产物内容不一致: {rel}");
    }

    // 幂等：第二次导出全部复用（内容一致不重写）
    let second = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        None,
    )
    .unwrap();
    assert!(second.written.is_empty(), "{:?}", second.written);
    assert!(!second.reused.is_empty());
}

#[test]
fn input_change_during_build_blocks_publish() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);

    // 在发布前复核前篡改 Excel 源：必须中止且不产出任何文件
    let hook = |stage: &str| -> Result<(), ct_app::export::ExportError> {
        if stage == "pre_publish" {
            let xlsx = root.join("excel/Item.xlsx");
            let mut bytes = std::fs::read(&xlsx).unwrap();
            bytes.push(0);
            std::fs::write(&xlsx, bytes).unwrap();
        }
        Ok(())
    };
    let err = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        Some(&hook),
    )
    .unwrap_err();
    assert!(err.to_string().contains("输入在生成期间发生变化"), "{err}");
    assert!(!root.join("output").exists(), "中止的导出不产生任何产物");
    assert!(!root.join(".ct/export-publication.json").exists());
}

#[test]
fn input_change_directory_membership_blocks() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);

    // schemas 目录新增成员
    let hook = |stage: &str| -> Result<(), ct_app::export::ExportError> {
        if stage == "pre_publish" {
            std::fs::write(
                root.join("config/schemas/extra.yaml"),
                "table: Extra\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n",
            )
            .unwrap();
        }
        Ok(())
    };
    let err = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        Some(&hook),
    )
    .unwrap_err();
    assert!(err.to_string().contains("资源目录成员变化"), "{err}");
}

#[test]
fn input_change_translation_blocks() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    let hook = |stage: &str| -> Result<(), ct_app::export::ExportError> {
        if stage == "pre_publish" {
            std::fs::write(
                root.join("i18n/en/Item.json"),
                "{\"1001.Name\": {\"text\": \"Changed\", \"confirmed\": true}}\n",
            )
            .unwrap();
        }
        Ok(())
    };
    let err = run_pipeline(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        None,
        Some(&hook),
    )
    .unwrap_err();
    assert!(err.to_string().contains("输入内容变化"), "{err}");
}

#[test]
fn capture_verify_unit() {
    // 单元级：capture → 篡改 → verify 报告对应变化
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    let config = ct_domain::config::GlobalConfig::load(&root).unwrap();
    let ws = ct_app::workspace::Workspace::open(&root).unwrap();
    let selected = ct_app::validate::select_tables(&ws, None);
    let refs: Vec<_> = selected.iter().collect();
    let before = capture_export_inputs(&config, &refs, &config.all_langs(), false);
    verify_inputs_unchanged(
        &before,
        &capture_export_inputs(&config, &refs, &config.all_langs(), false),
        "测试",
    )
    .unwrap();
    std::fs::write(
        root.join("config/types/rarity.yaml"),
        b"kind: enum\nname: Rarity\nvalues:\n  - name: Common\n  - name: Epic\n",
    )
    .unwrap();
    let err = verify_inputs_unchanged(
        &before,
        &capture_export_inputs(&config, &refs, &config.all_langs(), false),
        "测试",
    )
    .unwrap_err();
    assert!(err.to_string().contains("rarity.yaml"), "{err}");
}

#[test]
fn deploy_syncs_and_preserves_meta() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    // 配置部署目标
    std::fs::write(
        root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\ndeploy:\n  enabled: true\n  unity_project: ../unity\n  targets:\n    - source: output/generated/csharp\n      dest: Assets/Config/CSharp\n",
    )
    .unwrap();
    let unity = dir.path().join("unity");
    std::fs::create_dir_all(unity.join("Assets/Config/CSharp")).unwrap();
    // 预置：旧文件 + 既有 .meta（GUID 必须保留）+ 孤儿 .meta（删除）
    std::fs::write(unity.join("Assets/Config/CSharp/Old.cs"), b"old").unwrap();
    std::fs::write(unity.join("Assets/Config/CSharp/Old.cs.meta"), b"guid:old").unwrap();
    std::fs::write(
        unity.join("Assets/Config/CSharp/Orphan.cs.meta"),
        b"guid:orphan",
    )
    .unwrap();

    let request = ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    let (result, logs, _recovery) = run_export(
        &request,
        CompletionPolicy::export_then_deploy(false),
        None,
        None,
        false,
    )
    .unwrap();
    assert_eq!(result.tables, 1);
    assert!(logs.iter().any(|l| l.contains("同步")), "{logs:?}");

    let csharp = unity.join("Assets/Config/CSharp");
    // 新产物已同步（注意 Python 写小写名；Rust 保留原名）
    assert!(csharp.join("ItemAccessor.cs").exists());
    // 旧文件被删除、其 .meta 连带删除；源里无对应产物的孤儿 .meta 删除
    assert!(!csharp.join("Old.cs").exists());
    assert!(!csharp.join("Old.cs.meta").exists());
    assert!(!csharp.join("Orphan.cs.meta").exists());
    // state.json 账本已推进
    let state = std::fs::read_to_string(root.join("cache/state.json")).unwrap();
    assert!(state.contains("canonical-cache/1"));
    assert!(!state.contains("bundle-fp"), "账本只存指纹值");
    let parsed: serde_json::Value = serde_json::from_str(&state).unwrap();
    assert_eq!(parsed["excel_hashes"]["Item"].as_str().unwrap().len(), 64);
    assert!(parsed["bundles"]["zh"].is_string());
}

#[test]
fn deploy_failure_keeps_ledger_untouched() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    // 部署目标源目录不存在（output/generated/csharp 首次导出前）→ 部署失败
    std::fs::write(
        root.join("config/global.yaml"),
        "primary_lang: zh\ndeploy:\n  enabled: true\n  unity_project: ../unity\n  targets:\n    - source: output/nonexistent\n      dest: Assets/X\n",
    )
    .unwrap();
    let request = ExportRequest {
        root: root.clone(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    let err = run_export(
        &request,
        CompletionPolicy::export_then_deploy(false),
        None,
        None,
        false,
    )
    .unwrap_err();
    assert!(
        matches!(err, ct_app::export::RunError::Deploy(_)),
        "应为部署类错误: {err}"
    );
    assert!(err.to_string().contains("产物目录不存在"), "{err}");
    // 本地产物保留、账本不推进
    assert!(root.join("output/json/Item_zh.json").exists());
    assert!(
        !root.join("cache/state.json").exists(),
        "部署失败不得推进账本"
    );
}

#[test]
fn partial_export_keeps_other_ledger_entries() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("ws");
    copy_workspace(&root);
    // 先全量导出记账，再造一张新表并全量导出，随后单表导出：
    // 单表导出不得清掉其他表的账本条目。
    run_export(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        CompletionPolicy::export_only(),
        None,
        None,
        false,
    )
    .unwrap();
    // 新表加入工作区并导出（全量）
    std::fs::write(
        root.join("config/schemas/buff.yaml"),
        "table: Buff\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n",
    )
    .unwrap();
    // Buff 的 Excel：由 gen_template 生成空模板
    let ws = ct_app::workspace::Workspace::open(&root).unwrap();
    ct_app::template::gen_template(&ws, Some("Buff"), false).unwrap();
    run_export(
        &ExportRequest {
            root: root.clone(),
            table_filter: None,
            lang_filter: None,
            forced: false,
        },
        CompletionPolicy::export_only(),
        None,
        None,
        false,
    )
    .unwrap();

    // 单表导出 Item：Buff 的账本条目保留
    run_export(
        &ExportRequest {
            root: root.clone(),
            table_filter: Some("Item".to_string()),
            lang_filter: None,
            forced: false,
        },
        CompletionPolicy::export_only(),
        None,
        None,
        false,
    )
    .unwrap();
    let state: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(root.join("cache/state.json")).unwrap())
            .unwrap();
    assert!(
        state["excel_hashes"]["Buff"].is_string(),
        "部分导出不得清掉 Buff 的账本"
    );
    assert!(state["excel_hashes"]["Item"].is_string());
    // 部分导出不清理陈旧产物
    assert!(root.join("output/json/Buff_zh.json").exists());
}

#[test]
fn deploy_preserves_meta_when_generated_name_changes_case() {
    let temp = tempfile::tempdir().unwrap();
    let src = temp.path().join("src");
    let dst = temp.path().join("dst");
    std::fs::create_dir_all(&src).unwrap();
    std::fs::create_dir_all(&dst).unwrap();
    std::fs::write(src.join("itemaccessor.cs"), b"new").unwrap();
    std::fs::write(dst.join("ItemAccessor.cs"), b"old").unwrap();
    std::fs::write(dst.join("ItemAccessor.cs.meta"), b"GUID-KEEP").unwrap();
    let (count, _) = ct_export::deploy::sync_dir(&src, &dst).unwrap();
    assert_eq!(count, 1);
    assert_eq!(std::fs::read(dst.join("ItemAccessor.cs")).unwrap(), b"new");
    assert_eq!(
        std::fs::read(dst.join("ItemAccessor.cs.meta")).unwrap(),
        b"GUID-KEEP"
    );
    assert_eq!(std::fs::read_dir(&dst).unwrap().count(), 2);
    assert_eq!(ct_export::deploy::sync_dir(&src, &dst).unwrap().0, 0);
}
