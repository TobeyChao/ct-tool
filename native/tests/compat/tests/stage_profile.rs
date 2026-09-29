//! 阶段 profile 与「不重复计算」契约（任务 5.5）：导出带出逐阶段耗时，
//! 增量复用把写入/复制次数降到 0，校验闸门的结构化问题只算一次就交给上层。

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ct_app::export::{
    run_export, CompletionPolicy, ExportRequest, ExportResult, Reporter, RunError,
};

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

fn fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline/workspace")
}

fn workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    copy_dir(&fixture_root(), dir.path());
    dir
}

fn run(root: &Path, forced: bool) -> Result<ExportResult, RunError> {
    let request = ExportRequest {
        root: root.to_path_buf(),
        table_filter: None,
        lang_filter: None,
        forced,
    };
    run_export(&request, CompletionPolicy::export_only(), None, None, false)
        .map(|(result, _logs, _recovery)| result)
}

fn export(root: &Path, forced: bool) -> ExportResult {
    run(root, forced).expect("导出应成功")
}

/// 记录内核上报的阶段边界，用于证明进度事件语义未被 profile 改写。
#[derive(Default, Clone)]
struct Capture {
    stages: Arc<Mutex<Vec<String>>>,
    indices: Arc<Mutex<Vec<usize>>>,
    logs: Arc<Mutex<Vec<String>>>,
}

impl Reporter for Capture {
    fn log(&self, line: &str, _err: bool) {
        self.logs.lock().expect("中毒").push(line.to_string());
    }

    fn stage(&self, name: &str, index: usize, _total: usize) {
        self.stages.lock().expect("中毒").push(name.to_string());
        self.indices.lock().expect("中毒").push(index);
    }
}

#[test]
fn progress_visits_five_steps_then_the_publish_boundary() {
    let dir = workspace();
    let capture = Capture::default();
    let request = ExportRequest {
        root: dir.path().to_path_buf(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    run_export(
        &request,
        CompletionPolicy::export_only(),
        None,
        Some(Arc::new(capture.clone())),
        false,
    )
    .unwrap();
    assert_eq!(
        capture.stages.lock().expect("中毒").as_slice(),
        ["prepare", "json", "accessor", "fbs", "bundle", "publish"]
    );
    assert_eq!(
        capture.indices.lock().expect("中毒").as_slice(),
        [0, 1, 2, 3, 4, 5]
    );
}

#[test]
fn export_reports_every_stage_once() {
    let dir = workspace();
    let result = export(dir.path(), false);
    let names: Vec<&str> = result
        .stages
        .iter()
        .map(|(name, _)| name.as_str())
        .collect();
    assert_eq!(
        names,
        vec!["lock", "prepare", "json", "accessor", "fbs", "bundle", "publish"],
        "阶段 profile 应按流水线顺序各出现一次: {:?}",
        result.stages
    );
    let total_ms: u64 = result.stages.iter().map(|(_, ms)| *ms).sum();
    let elapsed_ms = (result.elapsed * 1000.0) as u64;
    assert!(elapsed_ms > 0, "导出耗时应大于 0");
    // profile 只比流水线多出「取锁 + 恢复」的开销，不得重复累加。
    assert!(
        total_ms < elapsed_ms + 2_000,
        "阶段耗时合计 {total_ms}ms 远超总耗时 {elapsed_ms}ms，profile 可能在重复计数"
    );
    for (name, ms) in &result.stages {
        assert!(*ms < 60_000, "阶段 {name} 耗时异常: {ms}ms");
    }
}

#[test]
fn incremental_export_writes_nothing_and_forced_rewrites_all() {
    let dir = workspace();
    let cold = export(dir.path(), false);
    assert!(!cold.written.is_empty(), "冷导出应写出全部产物");
    assert!(cold.reused.is_empty(), "冷导出没有可复用的正式产物");

    // 无变更再导一次：复用全部产物，写入次数为 0 —— 这就是「减少重复构建与复制」的证据。
    let warm = export(dir.path(), false);
    assert!(
        warm.written.is_empty(),
        "增量导出不得重写任何产物: {:?}",
        warm.written
    );
    assert_eq!(
        warm.reused.len(),
        cold.written.len(),
        "增量导出应复用冷导出的全部产物"
    );
    assert!(
        warm.cache_hits > 0 && warm.cache_misses == 0,
        "增量导出应全部命中生成缓存: {}/{}",
        warm.cache_hits,
        warm.cache_misses
    );
    assert_eq!(
        warm.stages.len(),
        cold.stages.len(),
        "增量路径的阶段集合应与冷导出一致"
    );

    // 强制重建：写回全部产物，且不复用任何既有文件。
    let forced = export(dir.path(), true);
    assert_eq!(
        forced.written.len(),
        cold.written.len(),
        "--all 应重写全部产物"
    );
    assert!(forced.reused.is_empty(), "--all 不得计入复用");
}

#[test]
fn validation_issues_are_carried_by_the_error_once() {
    let dir = workspace();
    std::fs::write(
        dir.path().join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Epic\n",
    )
    .expect("写入非法枚举");

    let err = run(dir.path(), false).expect_err("非法枚举值应让闸门失败");
    let RunError::Validation(text, issues) = err else {
        panic!("应为校验类错误: {err}");
    };
    assert!(text.contains("验证发现 2 个错误"), "{text}");
    assert_eq!(issues.len(), 2, "{issues:?}");

    // 上层拿到的就是闸门算出的那份：与重新跑一次 canonical_validate 完全一致，
    // 因此 worker 不必再解析校验文本或二次跑校验。
    let guard = ct_app::workspace::Workspace::open(dir.path()).expect("打开工作区");
    let recomputed = ct_app::validate::canonical_validate(&guard, None);
    assert_eq!(issues, recomputed, "结构化问题应与闸门算法结果逐值一致");
}

#[test]
fn failing_export_stops_progress_at_the_gate() {
    let dir = workspace();
    std::fs::write(
        dir.path().join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Epic\n",
    )
    .expect("写入非法枚举");
    let capture = Capture::default();
    let request = ExportRequest {
        root: dir.path().to_path_buf(),
        table_filter: None,
        lang_filter: None,
        forced: false,
    };
    let err = run_export(
        &request,
        CompletionPolicy::export_only(),
        None,
        Some(Arc::new(capture.clone())),
        false,
    )
    .expect_err("闸门应失败");
    assert!(matches!(err, RunError::Validation(_, _)), "{err}");
    assert_eq!(
        capture.stages.lock().expect("中毒").clone(),
        vec!["prepare".to_string()],
        "闸门失败后不得再上报后续阶段"
    );
}
