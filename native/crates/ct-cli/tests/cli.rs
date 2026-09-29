//! CLI 集成测试（任务 2.6/6.1）：只读入口不写缓存、不恢复事务。

use std::path::{Path, PathBuf};
use std::process::Command;

fn ct() -> Command {
    Command::new(env!("CARGO_BIN_EXE_ct"))
}

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content).unwrap();
}

/// 最小工作区：一张表，无 Excel。
fn setup_workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("config/global.yaml"), "primary_lang: zh\n");
    write(
        &root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n",
    );
    dir
}

#[test]
fn validate_missing_excel_fails_readonly() {
    let dir = setup_workspace();
    let out = ct()
        .args(["validate", "--root"])
        .arg(dir.path())
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("Excel 文件不存在"), "{stderr}");
    // 只读：不创建 cache/state.json
    assert!(!dir.path().join("cache/state.json").exists());
}

#[test]
fn validate_unknown_table_filter() {
    let dir = setup_workspace();
    let out = ct()
        .args(["validate", "--table", "Nope", "--root"])
        .arg(dir.path())
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("表 'Nope' 不存在"), "{stderr}");
}

#[test]
fn status_reports_missing_and_pending_journal() {
    let dir = setup_workspace();
    // 写入一个 pending 发布 journal
    write(
        &dir.path().join(".ct/export-publication.json"),
        r#"{"format": "export-publication/1", "operation_id": "op-1", "phase": "publishing"}"#,
    );
    let out = ct()
        .args(["status", "--root"])
        .arg(dir.path())
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stdout.is_empty(),
        "pending journal must not expose mixed status: {stdout}"
    );
    assert!(stderr.contains("[recovery-needed]"), "{stderr}");
    assert!(stderr.contains("op-1"), "{stderr}");
    assert!(stderr.contains("publishing"), "{stderr}");
    // 只读：不恢复、不写缓存
    assert!(dir.path().join(".ct/export-publication.json").exists());
    assert!(!dir.path().join("cache").exists());
}

#[test]
fn status_clean_minimal() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(&root.join("config/global.yaml"), "primary_lang: zh\n");
    // 无表 → 无缺失/变更
    let out = ct().args(["status", "--root"]).arg(root).output().unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("[OK]"), "{stdout}");
}

// ---- 任务 6.1：全量命令面（文本/JSON 输出、过滤错误、退出码、panel 指引） ----

/// 带 i18n 字段的工作区（可 gen-template + export）。
fn setup_full_workspace() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(
        &root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\n",
    );
    write(
        &root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Name\n    type: string\n    i18n: true\nindexes:\n  - kind: codename\n",
    );
    dir
}

fn success(args: &[&str], root: &Path) -> String {
    let out = ct().args(args).arg("--root").arg(root).output().unwrap();
    assert!(
        out.status.success(),
        "{args:?} 应成功: stdout={} stderr={}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    )
}

/// 解析「增量导出：写入 N，复用 M；生成缓存命中 K」里的两个计数。
fn summary_counts(text: &str) -> (usize, usize) {
    let line = text
        .lines()
        .find(|line| line.contains("导出：写入") || line.contains("重建：写入"))
        .expect("导出应打印写入/复用汇总行");
    let number_after = |label: &str| -> usize {
        line.split(label)
            .nth(1)
            .and_then(|rest| rest.split(['\u{ff0c}', ' ', '\u{ff1b}']).next())
            .and_then(|value| value.parse().ok())
            .unwrap_or_else(|| panic!("无法从 {line} 解析 {label}"))
    };
    (
        number_after("\u{5199}\u{5165} "),
        number_after("\u{590d}\u{7528} "),
    )
}

#[test]
fn export_happy_path_writes_artifacts_and_ledger() {
    let dir = setup_full_workspace();
    let root = dir.path();
    success(&["gen-template", "--all"], root);
    let text = success(&["export"], root);
    assert!(text.contains("导出完成: 1 张表"), "{text}");
    assert!(text.contains("增量导出：写入"), "{text}");
    // 汇总行的写入/复用计数必须反映真实发布结果（曾在发布前取样，恒为 0）
    let (written, reused) = summary_counts(&text);
    assert!(written > 0, "首次导出应写出产物：{text}");
    assert_eq!(reused, 0, "首次导出不该有复用：{text}");
    assert!(root.join("output/json/Item_zh.json").exists());
    assert!(root.join("output/json/Item_en.json").exists());
    assert!(root.join("output/binary/data_zh.bin").exists());
    assert!(root
        .join("output/generated/csharp/ItemAccessor.cs")
        .exists());
    assert!(root.join("cache/state.json").exists(), "成功后推进账本");

    // 第二次：全部复用（无写入）
    let second = success(&["export"], root);
    let (second_written, second_reused) = summary_counts(&second);
    assert_eq!(second_written, 0, "无变更导出不该重写任何产物：{second}");
    assert_eq!(
        second_reused, written,
        "无变更导出应复用首次写出的全部产物：{second}"
    );

    // --all：强制重建
    let forced = success(&["export", "--all"], root);
    assert!(forced.contains("强制重建"), "{forced}");
    let (forced_written, forced_reused) = summary_counts(&forced);
    assert_eq!(forced_written, written, "--all 应写回全部产物：{forced}");
    assert_eq!(forced_reused, 0, "--all 不得计入复用：{forced}");
}

#[test]
fn export_unknown_table_and_bad_lang_exit_one() {
    let dir = setup_full_workspace();
    let root = dir.path();
    success(&["gen-template", "--all"], root);
    let out = ct()
        .args(["export", "--table", "Nope"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stderr.contains("[export error] 表 'Nope' 不存在"),
        "{stderr}"
    );

    let out = ct()
        .args(["export", "--lang", "fr"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("语言 'fr' 不在可导出语言中"), "{stderr}");
    assert!(!root.join("output/json").exists() || stderr.contains("export error"));
}

#[test]
fn export_validation_failure_reports_issue_list() {
    let dir = setup_full_workspace();
    let root = dir.path();
    success(&["gen-template", "--all"], root);
    let ledger_before = std::fs::read(root.join("cache/state.json")).unwrap();
    // 破坏数据：主键重复
    let workbook = {
        let mut wb = rust_xlsxwriter::Workbook::new();
        let ws = wb.add_worksheet();
        ws.set_name("Item").unwrap();
        ws.write_string(1, 0, "Id\nint32").unwrap();
        ws.write_string(1, 1, "CodeName\nstring").unwrap();
        ws.write_string(1, 2, "Name\nstring").unwrap();
        ws.write_number(2, 0, 5.0).unwrap();
        ws.write_number(3, 0, 5.0).unwrap();
        wb.save_to_buffer().unwrap()
    };
    std::fs::write(root.join("excel/Item.xlsx"), workbook).unwrap();
    let out = ct()
        .args(["export"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("验证发现"), "{stderr}");
    assert!(stderr.contains("✗"), "{stderr}");
    assert_eq!(
        std::fs::read(root.join("cache/state.json")).unwrap(),
        ledger_before,
        "导出失败不得推进模板生成留下的成功账本"
    );
}

#[test]
fn gen_template_unknown_table_text_and_code() {
    let dir = setup_full_workspace();
    let out = ct()
        .args(["gen-template", "--table", "Nope"])
        .arg("--root")
        .arg(dir.path())
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    // Python 行为：文本原样，不加 [error] 前缀
    assert_eq!(stderr.trim(), "表 'Nope' 不存在", "{stderr}");
}

#[test]
fn i18n_sync_status_json_and_compact_dry_run() {
    let dir = setup_full_workspace();
    let root = dir.path();
    success(&["gen-template", "--all"], root);
    let text = success(&["i18n", "sync"], root);
    assert!(text.contains("[i18n sync]"), "{text}");

    let json_text = success(&["i18n", "status", "--json"], root);
    let parsed: serde_json::Value = serde_json::from_str(json_text.trim()).unwrap();
    assert!(parsed["langs"]["en"].is_object(), "{json_text}");
    assert!(parsed["langs"]["en"]["tables"]["Item"].is_object());

    let line = success(&["i18n", "status"], root);
    assert!(line.contains("[en]"), "{line}");
    assert!(line.contains("translated"), "{line}");

    // 注入 orphan 后 dry-run 不修改文件
    let en_path = root.join("i18n/en/Item.json");
    let mut entries: serde_json::Map<String, serde_json::Value> =
        serde_json::from_str(&std::fs::read_to_string(&en_path).unwrap()).unwrap_or_default();
    entries.insert(
        "9999.Name".into(),
        serde_json::json!({"text": "ghost", "confirmed": true, "status": "orphan", "source": ""}),
    );
    std::fs::write(
        &en_path,
        serde_json::to_string_pretty(&serde_json::Value::Object(entries)).unwrap(),
    )
    .unwrap();
    let before = std::fs::read_to_string(&en_path).unwrap();
    let text = success(&["i18n", "compact", "--dry-run"], root);
    assert!(text.contains("将移除 1 条 orphan"), "{text}");
    assert!(text.contains("dry-run，未修改任何文件"), "{text}");
    assert_eq!(std::fs::read_to_string(&en_path).unwrap(), before);
    let text = success(&["i18n", "compact"], root);
    assert!(text.contains("共 1 条 orphan 已移除"), "{text}");

    // 未知语言：友好失败
    let out = ct()
        .args(["i18n", "status", "--lang", "fr"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("[i18n status] 语言 'fr'"), "{stderr}");
}

#[test]
fn deploy_without_config_reports_no_change() {
    let dir = setup_full_workspace();
    let root = dir.path();
    success(&["gen-template", "--all"], root);
    success(&["export"], root);
    let text = success(&["deploy"], root);
    assert!(text.contains("未配置或未启用，跳过"), "{text}");
    assert!(text.contains("[deploy] 无文件变更"), "{text}");
}

#[test]
fn panel_command_exposes_native_web_options() {
    let out = ct().args(["panel", "--help"]).output().unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    for option in ["--root", "--host", "--port", "--no-browser"] {
        assert!(stdout.contains(option), "{stdout}");
    }
}

#[test]
fn help_lists_full_command_surface() {
    let out = ct().arg("--help").output().unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    for command in [
        "export",
        "validate",
        "status",
        "gen-template",
        "i18n",
        "deploy",
        "panel",
        "worker",
    ] {
        assert!(stdout.contains(command), "{stdout}");
    }
}

// ---- 任务 4.6：journal 恢复、workspace.recover、只读快照恢复阻塞 ----

/// 造一个 publishing 阶段的中断现场（覆盖 item.yaml，备份在 .ct/backup）。
fn plant_pending_publish(root: &Path) -> (PathBuf, Vec<u8>) {
    let target = root.join("config/schemas/item.yaml");
    let original = std::fs::read(&target).unwrap();
    let backup_dir = root.join(".ct/backup/op-cli");
    std::fs::create_dir_all(&backup_dir).unwrap();
    let backup = backup_dir.join("1-item.yaml");
    std::fs::write(&backup, &original).unwrap();
    std::fs::write(&target, b"corrupted mid publish\n").unwrap();
    let journal = serde_json::json!({
        "format": "export-publication/1",
        "operation_id": "op-cli",
        "root": root.to_string_lossy(),
        "phase": "publishing",
        "allowed_dirs": [root.join("config/schemas").to_string_lossy()],
        "entries": [{
            "path": target.to_string_lossy(),
            "op": "replace",
            "existed": true,
            "backup": backup.to_string_lossy(),
            "done": false
        }],
    });
    std::fs::write(
        root.join(".ct/export-publication.json"),
        serde_json::to_string_pretty(&journal).unwrap(),
    )
    .unwrap();
    (target, original)
}

#[test]
fn validate_and_status_report_recovery_needed() {
    let dir = setup_full_workspace();
    let root = dir.path();
    let (target, _) = plant_pending_publish(root);

    // validate：混合状态不出结论
    let out = ct()
        .args(["validate"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("[recovery-needed]"), "{stderr}");
    // status：混合状态不出「看似健康」的快照结论，直接报 recovery-needed
    let out = ct()
        .args(["status"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("[recovery-needed]"), "{stderr}");
    assert!(
        out.stdout.is_empty(),
        "status must not expose mixed resources"
    );
    // 只读：不得自行恢复
    assert!(root.join(".ct/export-publication.json").exists());
    assert_eq!(std::fs::read(&target).unwrap(), b"corrupted mid publish\n");
}

#[test]
fn recover_command_restores_and_returns_new_baseline() {
    let dir = setup_full_workspace();
    let root = dir.path();
    let (target, original) = plant_pending_publish(root);

    let out = ct()
        .args(["recover"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("已回滚未完成的发布"), "{stdout}");
    assert!(stdout.contains("新基线 schemaRevision"), "{stdout}");
    // 现场已还原，材料清理
    assert_eq!(std::fs::read(&target).unwrap(), original);
    assert!(!root.join(".ct/export-publication.json").exists());
    assert!(!root.join(".ct/backup/op-cli").exists());
    if root.join(".ct/backup").exists() {
        // 与 Python 一致：只清理 operation 子目录，空壳目录允许残留
        assert_eq!(
            std::fs::read_dir(root.join(".ct/backup")).unwrap().count(),
            0
        );
    }

    // 再跑一次：无待恢复事务
    let second = ct()
        .args(["recover"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&second.stdout);
    assert!(stdout.contains("无待恢复事务"), "{stdout}");

    // 恢复后 validate 正常出结论
    let validate = ct()
        .args(["validate"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    let stderr = String::from_utf8_lossy(&validate.stderr);
    assert!(!stderr.contains("recovery-needed"), "{stderr}");
}

#[test]
fn recover_json_output_shape() {
    let dir = setup_full_workspace();
    let root = dir.path();
    plant_pending_publish(root);
    let out = ct()
        .args(["recover", "--json"])
        .arg("--root")
        .arg(root)
        .output()
        .unwrap();
    assert!(out.status.success());
    let parsed: serde_json::Value =
        serde_json::from_str(String::from_utf8_lossy(&out.stdout).trim()).unwrap();
    assert_eq!(parsed["recovered"], serde_json::json!(true));
    assert!(parsed["note"].as_str().unwrap().contains("已回滚"));
    assert_eq!(parsed["schemaRevision"].as_str().unwrap().len(), 64);
}
