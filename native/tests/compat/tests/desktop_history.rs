//! 桌面导出历史读写（任务 6.10）：实际 cache_dir、最近五条裁剪、未知格式忽略、
//! CLI 不追加历史、以及"历史写失败不得误报业务提交失败"。

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ct_app::export::{run_export, CompletionPolicy, ExportRequest, Reporter};
use ct_app::history::{
    append_history, import_legacy_history, read_history, HISTORY_FORMAT, MAX_ENTRIES,
};
use serde_json::{json, Value};

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().expect("父目录")).expect("创建目录");
    std::fs::write(path, content.replace("\r\n", "\n")).expect("写入文件");
}

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).expect("创建目录");
    for entry in std::fs::read_dir(src).expect("读取夹具").flatten() {
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).expect("复制夹具文件");
        }
    }
}

/// 与 Python golden 同源的多行工作区（可直接导出）。
fn rich_workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    let fixture =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace");
    copy_dir(&fixture, dir.path());
    dir
}

fn plain_workspace(cache_dir: &str) -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    write(
        &dir.path().join("config/global.yaml"),
        &format!("primary_lang: zh\nsecondary_langs:\n  - en\ncache_dir: {cache_dir}\n"),
    );
    dir
}

#[derive(Clone, Default)]
struct Capture(Arc<Mutex<Vec<String>>>);

impl Reporter for Capture {
    fn stage(&self, _name: &str, _index: usize, _total: usize) {}

    fn log(&self, line: &str, _err: bool) {
        self.0.lock().expect("捕获中毒").push(line.to_string());
    }
}

impl Capture {
    fn lines(&self) -> Vec<String> {
        self.0.lock().expect("捕获中毒").clone()
    }
}

fn export(
    root: &Path,
    history: bool,
    reporter: &Capture,
) -> Result<ct_app::export::ExportResult, String> {
    let request = ExportRequest {
        root: root.to_path_buf(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    run_export(
        &request,
        CompletionPolicy::export_only(),
        None,
        Some(std::sync::Arc::new(reporter.clone())),
        history,
    )
    .map(|(result, _logs, _recovery)| result)
    .map_err(|e| e.to_string())
}

#[test]
fn history_appends_newest_first_and_trims_to_five() {
    let dir = plain_workspace("cache");
    for index in 0..7 {
        append_history(
            dir.path(),
            json!({"time": format!("t{index}"), "result": "success"}),
        )
        .expect("追加历史");
    }
    let entries = read_history(dir.path());
    assert_eq!(
        entries.len(),
        MAX_ENTRIES,
        "只保留最近 {MAX_ENTRIES} 条：{entries:?}"
    );
    assert_eq!(entries[0]["time"], "t6", "最新在前：{entries:?}");
    assert_eq!(entries[4]["time"], "t2", "{entries:?}");
    let raw: Value = serde_json::from_str(
        &std::fs::read_to_string(dir.path().join("cache/history.json")).unwrap(),
    )
    .expect("历史文件是合法 JSON");
    assert_eq!(raw["format"], HISTORY_FORMAT, "{raw}");
}

#[test]
fn two_native_exports_in_one_second_remain_two_history_events() {
    let dir = plain_workspace("cache");
    let entry = json!({"time":"2026-01-01T00:00:00Z","scope":"all","result":"success","tables":1,"elapsed":0.1,"forced":false,"error":""});
    append_history(dir.path(), entry.clone()).unwrap();
    append_history(dir.path(), entry).unwrap();
    assert_eq!(read_history(dir.path()).len(), 2);
}

#[test]
fn history_follows_configured_cache_dir() {
    let dir = plain_workspace("state/desktop");
    append_history(dir.path(), json!({"time": "x", "result": "success"})).expect("追加历史");
    assert!(
        dir.path().join("state/desktop/history.json").exists(),
        "必须落在配置的 cache_dir"
    );
    assert!(
        !dir.path().join("cache/history.json").exists(),
        "不得写到默认位置"
    );
    assert_eq!(read_history(dir.path()).len(), 1);
}

#[test]
fn unknown_history_format_is_ignored_then_replaced() {
    let dir = plain_workspace("cache");
    std::fs::create_dir_all(dir.path().join("cache")).expect("创建目录");
    write(
        &dir.path().join("cache/history.json"),
        "{\"format\": \"panel-history/0\", \"entries\": [{\"time\": \"旧\"}]}",
    );
    assert!(read_history(dir.path()).is_empty(), "旧格式不迁移、不读取");
    append_history(dir.path(), json!({"time": "新", "result": "success"})).expect("追加历史");
    let entries = read_history(dir.path());
    assert_eq!(entries.len(), 1, "未知格式被整体替换：{entries:?}");
    assert_eq!(entries[0]["time"], "新");
}

#[test]
fn cli_path_does_not_write_desktop_history() {
    let dir = rich_workspace();
    let capture = Capture::default();
    let result = export(dir.path(), false, &capture).unwrap_or_else(|e| panic!("导出应成功: {e}"));
    assert!(result.tables > 0, "{result:?}");
    assert!(result.history_warning.is_none(), "未写历史就不该有警告");
    assert!(
        !dir.path().join("cache/history.json").exists(),
        "CLI 不追加桌面历史"
    );
    assert!(
        dir.path().join(".ct/state.json").exists() || dir.path().join(".ct").exists(),
        "成功账本仍要写入：{:?}",
        dir.path().join(".ct")
    );
}

#[test]
fn desktop_export_records_success_entry() {
    let dir = rich_workspace();
    let capture = Capture::default();
    let result = export(dir.path(), true, &capture).unwrap_or_else(|e| panic!("导出应成功: {e}"));
    assert!(
        result.history_warning.is_none(),
        "{:?}",
        result.history_warning
    );
    let entries = read_history(dir.path());
    assert_eq!(entries.len(), 1, "{entries:?}");
    let entry = &entries[0];
    assert_eq!(entry["result"], "success", "{entry}");
    assert_eq!(entry["scope"], "all", "{entry}");
    assert_eq!(
        entry["tables"].as_u64(),
        Some(result.tables as u64),
        "{entry}"
    );
    assert_eq!(entry["forced"], false, "{entry}");
    assert!(
        entry["time"].as_str().is_some_and(|t| !t.is_empty()),
        "{entry}"
    );
    assert!(entry["elapsed"].as_f64().is_some(), "{entry}");
    assert_eq!(entry["error"], "", "{entry}");
}

#[test]
fn history_write_failure_is_reported_separately() {
    let dir = rich_workspace();
    // 把历史文件位置做成目录：写入必然失败
    std::fs::create_dir_all(dir.path().join("cache/history.json")).expect("制造冲突目录");
    let capture = Capture::default();
    let result = export(dir.path(), true, &capture)
        .unwrap_or_else(|e| panic!("历史写失败不得推翻已成功的业务提交，实际返回错误：{e}"));
    let warning = result
        .history_warning
        .as_ref()
        .expect("历史失败必须留下可报告的警告");
    assert!(warning.contains("历史"), "{warning}");
    assert!(
        capture.lines().iter().any(|line| line.contains("历史")),
        "报告要经诊断通道送出：{:?}",
        capture.lines()
    );
    assert!(
        dir.path().join("output/json/item_zh.json").exists(),
        "产物必须完整发布（业务已提交）"
    );
    assert!(
        read_history(dir.path()).is_empty(),
        "历史确实没写进去，但业务状态不受影响"
    );
}

#[test]
fn history_failure_does_not_change_second_export_outcome() {
    let dir = rich_workspace();
    std::fs::create_dir_all(dir.path().join("cache/history.json")).expect("制造冲突目录");
    let first = Capture::default();
    let a = export(dir.path(), true, &first).expect("首次导出成功");
    let b = export(dir.path(), true, &first).expect("二次导出仍成功");
    assert!(a.history_warning.is_some() && b.history_warning.is_some());
    assert_eq!(a.tables, b.tables, "两次业务结果一致：{a:?} {b:?}");
}

#[test]
fn legacy_history_merges_once_with_stable_ids_and_source_digest() {
    let dir = plain_workspace("state/desktop");
    let root = dir.path();
    let source = root.join("cache/panel_history.json");
    let old: Vec<Value> = (1..=7)
        .map(|day| {
            json!({
                "time": format!("2026-01-{day:02} 00:00:00"),
                "scope": "全部表 × 全量语言", "result": "成功",
                "tables": 1, "elapsed": 0.1, "forced": false, "error": ""
            })
        })
        .collect();
    let source_text = serde_json::to_string(&old).unwrap();
    write(&source, &source_text);
    let second_source = root.join("state/desktop/panel_history.json");
    write(&second_source, &source_text);
    let native = json!({
        "time": "2026-01-07 00:00:00", "scope": "全部表 × 全量语言",
        "result": "success", "tables": 1, "elapsed": 0.1,
        "forced": false, "error": "", "nativeOnlyMetadata": true
    });
    append_history(root, native.clone()).unwrap();
    let entries = read_history(root);
    assert_eq!(entries.len(), 5, "{entries:?}");
    assert_eq!(entries[0]["time"], "2026-01-07 00:00:00");
    assert_eq!(
        entries[0]["nativeOnlyMetadata"], true,
        "native duplicate wins"
    );
    assert_eq!(entries[4]["time"], "2026-01-03 00:00:00");
    let saved: Value =
        serde_json::from_slice(&std::fs::read(root.join("state/desktop/history.json")).unwrap())
            .unwrap();
    assert_eq!(saved["legacyPanelImported"], true);
    assert_eq!(saved["legacyPanelSources"].as_array().unwrap().len(), 2);
    assert_eq!(
        saved["legacyPanelSources"][0]["path"],
        "cache/panel_history.json"
    );
    assert_eq!(
        saved["legacyPanelSources"][0]["sha256"],
        ct_domain::hashing::sha256_hex(source_text.as_bytes())
    );
    assert_eq!(std::fs::read_to_string(&source).unwrap(), source_text);
    assert_eq!(
        std::fs::read_to_string(&second_source).unwrap(),
        source_text
    );

    // A truncated old record must never reappear, even if the retained source changes.
    let mut changed = old;
    changed.push(json!({"time":"2026-01-09 00:00:00","result":"成功"}));
    write(&source, &serde_json::to_string(&changed).unwrap());
    import_legacy_history(root).unwrap();
    assert_eq!(read_history(root), entries);
}

#[test]
fn corrupt_legacy_history_and_atomic_write_failure_keep_source_for_retry() {
    let dir = plain_workspace("cache");
    let root = dir.path();
    let source = root.join("cache/panel_history.json");
    write(&source, "not JSON");
    let error = import_legacy_history(root).unwrap_err().to_string();
    assert!(error.contains("保留原文件"), "{error}");
    assert_eq!(std::fs::read_to_string(&source).unwrap(), "not JSON");
    assert!(read_history(root).is_empty());

    let old = json!([{"time":"2026-01-01 00:00:00","result":"成功","tables":1}]);
    let source_text = old.to_string();
    write(&source, &source_text);
    std::fs::create_dir_all(root.join("cache/history.json")).unwrap();
    let error = import_legacy_history(root).unwrap_err().to_string();
    assert!(error.contains("历史写入失败"), "{error}");
    assert_eq!(std::fs::read_to_string(&source).unwrap(), source_text);
    std::fs::remove_dir(root.join("cache/history.json")).unwrap();
    import_legacy_history(root).unwrap();
    assert_eq!(read_history(root).len(), 1);
    let imported = &read_history(root)[0];
    assert_eq!(imported["result"], "success");
    assert_eq!(imported["scope"], "all");
    assert_eq!(imported["elapsed"], 0.0);
}
