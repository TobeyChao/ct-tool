//! 桌面状态面（任务 6.10）：历史跨重启读取、模块日志筛选、任务问题分页与
//! dismiss 归属，以及历史写失败在协议层的"分开报告"。

use ct_protocol::message::Message;
use ct_tests_protocol::{minimal_workspace, rich_workspace, write, Wire, QUIET};
use serde_json::{json, Value};

fn terminal_id(wire: &mut Wire, method: &str, params: Value) -> (Message, Vec<Message>, u64) {
    let id = wire.call(method, params);
    let (terminal, events) = wire.until_terminal(id);
    (terminal, events, id)
}

fn workspace_id(message: &Message) -> Option<String> {
    match message {
        Message::Result(response) => Some(response.workspace_id.clone()),
        Message::Error(response) => response.workspace_id.clone(),
        Message::Progress(event) => Some(event.workspace_id.clone()),
        Message::Log(event) => Some(event.workspace_id.clone()),
        Message::Issue(event) => Some(event.workspace_id.clone()),
        Message::Hello(_) | Message::Request(_) => None,
    }
}

#[test]
fn history_survives_worker_restart() {
    let dir = rich_workspace();
    let mut first = Wire::connected();
    first.bind_root(dir.path());
    first.payload("workspace.open", json!({}));
    let (terminal, _, _) = terminal_id(&mut first, "export", json!({}));
    let id = match &terminal {
        Message::Result(response) => response.request_id,
        other => panic!("导出应成功：{other:?}"),
    };
    let _ = id;
    let history = first.payload("history.list", json!({}));
    assert_eq!(history["entries"].as_array().unwrap().len(), 1, "{history}");
    assert_eq!(history["entries"][0]["result"], "success", "{history}");
    first.close_input();
    first.wait_exit().expect("干净退出");

    // 新连接（等价于 worker 重启）：历史来自磁盘，不依赖会话内存
    let mut again = Wire::connected();
    again.bind_root(dir.path());
    again.payload("workspace.open", json!({}));
    let after_restart = again.payload("history.list", json!({}));
    assert_eq!(after_restart, history, "重启后必须读回同一批历史");
    again.shutdown();
}

#[test]
fn imported_web_history_is_readable_through_worker_history_contract() {
    let dir = minimal_workspace();
    let source = dir.path().join("cache/panel_history.json");
    std::fs::create_dir_all(source.parent().unwrap()).unwrap();
    std::fs::write(&source, r#"[{"time":"2026-01-01 00:00:00","scope":"全部表 × 全量语言","result":"成功","tables":1,"elapsed":0.1,"forced":false,"error":""}]"#).unwrap();
    {
        let _lock = ct_storage::lock::WorkspaceLock::acquire(dir.path()).unwrap();
        ct_app::history::import_legacy_history(dir.path()).unwrap();
    }
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let history = wire.payload("history.list", json!({}));
    assert_eq!(history["entries"][0]["result"], "success", "{history}");
    assert_eq!(history["entries"][0]["tables"], 1, "{history}");
    assert_eq!(history["entries"][0]["elapsed"], 0.1, "{history}");
    assert_eq!(
        history["entries"][0]["scope"], "全部表 × 全量语言",
        "{history}"
    );
    assert_eq!(history["entries"].as_array().unwrap().len(), 1);
    wire.shutdown();
    assert!(source.exists(), "旧历史源必须保留");
}

#[test]
fn every_response_is_attributed_to_the_same_workspace() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    let (opened, _, _) = terminal_id(&mut wire, "workspace.open", json!({}));
    let id = workspace_id(&opened).expect("响应必须带 workspaceId");
    assert!(
        id.len() >= 8 && id.chars().all(|c| c.is_ascii_hexdigit()),
        "{id}"
    );
    let (status, _, _) = terminal_id(&mut wire, "workspace.status", json!({}));
    assert_eq!(
        workspace_id(&status).as_deref(),
        Some(id.as_str()),
        "同一连接内 workspaceId 必须稳定"
    );
    wire.close_input();
    wire.wait_exit().expect("干净退出");

    // 同一根路径重连：workspaceId 由规范化路径导出，必须一致
    let mut again = Wire::connected();
    again.bind_root(dir.path());
    let (reopened, _, _) = terminal_id(&mut again, "workspace.open", json!({}));
    assert_eq!(
        workspace_id(&reopened).as_deref(),
        Some(id.as_str()),
        "workspaceId 必须可跨连接归属"
    );
    again.shutdown();
}

#[test]
fn pending_publication_status_never_loads_mixed_schema() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    assert_eq!(wire.payload("workspace.open", json!({}))["status"], "ready");

    let schema = dir.path().join("config/schemas/item.yaml");
    let original = std::fs::read(&schema).unwrap();
    write(&schema, "broken mid publication: [\n");
    write(
        &dir.path().join(".ct/export-publication.json"),
        r#"{"format":"export-publication/1","operation_id":"op-worker","phase":"publishing"}"#,
    );

    let opened = wire.payload("workspace.open", json!({}));
    assert_eq!(opened["status"], "recovery_needed", "{opened}");
    assert_eq!(opened["tables"], 0, "{opened}");
    let status = wire.payload("workspace.status", json!({}));
    assert_eq!(status["pendingJournal"], true, "{status}");
    assert_eq!(status["changedTables"], json!([]), "{status}");
    assert_eq!(
        wire.error_code("workspace.snapshot", json!({})),
        "recovery-needed"
    );
    for method in ["resources.list", "history.list", "validate"] {
        assert_eq!(
            wire.error_code(method, json!({})),
            "recovery-needed",
            "{method} must not read mixed resources"
        );
    }
    assert_eq!(
        std::fs::read(&schema).unwrap(),
        b"broken mid publication: [\n"
    );

    std::fs::remove_file(dir.path().join(".ct/export-publication.json")).unwrap();
    std::fs::write(&schema, original).unwrap();
    assert_eq!(wire.payload("workspace.open", json!({}))["status"], "ready");
    wire.shutdown();
}

#[test]
fn worker_reads_report_busy_for_locked_root_without_blocking_another_root() {
    let locked = minimal_workspace();
    let free = minimal_workspace();
    let mut locked_wire = Wire::connected();
    locked_wire.bind_root(locked.path());
    let mut free_wire = Wire::connected();
    free_wire.bind_root(free.path());
    let guard = ct_storage::lock::WorkspaceLock::acquire(locked.path()).unwrap();
    assert_eq!(locked_wire.error_code("resources.list", json!({})), "busy");
    assert_eq!(
        free_wire.payload("workspace.open", json!({}))["status"],
        "ready"
    );
    drop(guard);
    assert_eq!(
        locked_wire.payload("workspace.open", json!({}))["status"],
        "ready"
    );
    locked_wire.shutdown();
    free_wire.shutdown();
}

#[test]
fn module_logs_filter_by_module_and_level() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    wire.payload("export", json!({"all": true}));

    let all = wire.payload("logs.list", json!({"page": {}}));
    let total = all["entries"].as_array().unwrap().len();
    assert!(total >= 3, "导出应留下多条模块日志：{all}");
    let modules: Vec<&str> = all["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| entry["module"].as_str().unwrap_or_default())
        .collect();
    assert!(modules.contains(&"export"), "{modules:?}");

    let only_export = wire.payload("logs.list", json!({"module": "export", "page": {}}));
    let filtered = only_export["entries"].as_array().unwrap();
    assert!(!filtered.is_empty(), "export 模块必须有日志：{only_export}");
    for entry in filtered {
        assert_eq!(entry["module"], "export", "{entry}");
    }
    assert!(
        filtered.len() < total,
        "筛选必须真的收窄：export {} 条 / 全部 {total} 条",
        filtered.len()
    );
    // 握手也进模块日志，便于诊断 worker 版本与连接建立
    assert!(
        all["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["module"] == "control"),
        "{all}"
    );

    let nothing = wire.payload("logs.list", json!({"module": "no-such-module", "page": {}}));
    assert!(
        nothing["entries"].as_array().unwrap().is_empty(),
        "{nothing}"
    );
    assert!(nothing["nextCursor"].is_null(), "空页不得给令牌：{nothing}");
    let errors = wire.payload("logs.list", json!({"level": "error", "page": {}}));
    assert!(errors["entries"].as_array().unwrap().is_empty(), "{errors}");
    assert!(
        errors["revision"].is_number(),
        "分页响应必须回传 revision：{errors}"
    );
    wire.shutdown();
}

#[test]
fn task_issues_page_and_dismiss_are_connection_scoped() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let (terminal, _, write_id) =
        terminal_id(&mut wire, "template.generate", json!({"table": "Item"}));
    assert!(matches!(terminal, Message::Result(_)), "{terminal:?}");

    let tasks = wire.payload("tasks.list", json!({}));
    let task = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["requestId"] == json!(write_id))
        .unwrap_or_else(|| panic!("应能按 requestId 归属任务：{tasks}"));
    assert_eq!(task["status"], "success", "{task}");
    assert_eq!(task["dismissed"], false, "{task}");
    let task_id = task["id"].as_str().unwrap().to_string();

    // 成功任务没有问题：分页结果为空且不给令牌
    let issues = wire.payload(
        "tasks.issues",
        json!({"taskId": task_id, "page": {"limit": 1}}),
    );
    assert!(
        issues["issues"].as_array().unwrap().is_empty(),
        "{issues:?}"
    );
    assert!(issues["nextCursor"].is_null(), "{issues:?}");
    assert!(issues["revision"].is_number(), "{issues:?}");

    // 关闭通知
    let dismissed = wire.payload("tasks.dismiss", json!({"taskId": task_id.clone()}));
    assert_eq!(dismissed, json!(true), "{dismissed}");
    let tasks = wire.payload("tasks.list", json!({}));
    let after = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["id"] == task_id)
        .expect("任务仍在列表里（只关闭通知）");
    assert_eq!(after["dismissed"], true, "{after}");

    // 未知任务：拒绝，不静默成功
    let code = wire.error_code("tasks.dismiss", json!({"taskId": "nope#1"}));
    assert_eq!(code, "internal", "未知任务应报错：{code}");

    // 重连：上一连接的任务与通知都不复活
    wire.close_input();
    wire.wait_exit().expect("干净退出");
    let mut again = Wire::connected();
    again.bind_root(dir.path());
    again.payload("workspace.open", json!({}));
    let fresh = again.payload("tasks.list", json!({}));
    assert!(
        fresh["tasks"].as_array().unwrap().is_empty(),
        "关闭的通知不得复活：{fresh}"
    );
    again.shutdown();
}

#[test]
fn history_write_failure_is_reported_as_issue_not_failure() {
    let dir = rich_workspace();
    std::fs::create_dir_all(dir.path().join("cache/history.json")).expect("制造历史写入冲突");
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let (terminal, events, _) = terminal_id(&mut wire, "export", json!({"all": true}));
    let payload = match &terminal {
        Message::Result(response) => response.payload.clone(),
        other => panic!("历史写失败不得变成 error 终态：{other:?}"),
    };
    assert_eq!(payload["outcome"], "succeeded", "{payload}");
    assert!(
        payload["tables"].as_u64().unwrap_or_default() >= 1,
        "{payload}"
    );
    let issues = payload["issues"].as_array().cloned().unwrap_or_default();
    assert_eq!(issues.len(), 1, "分开报告的问题必须带出：{payload}");
    assert_eq!(issues[0]["code"], "history-write-failed", "{issues:?}");
    assert!(
        issues[0]["message"]
            .as_str()
            .is_some_and(|text| text.contains("历史")),
        "{issues:?}"
    );
    assert!(
        events.iter().any(|message| matches!(
            message,
            Message::Log(event) if event.message.contains("历史")
        )),
        "诊断通道也要有一条：{events:?}"
    );
    // 业务确实已提交：产物与账本存在，历史为空
    assert!(dir.path().join("output/json/item_zh.json").exists());
    let history = wire.payload("history.list", json!({}));
    assert!(
        history["entries"].as_array().unwrap().is_empty(),
        "{history}"
    );
    assert!(wire.line_within(QUIET).is_none(), "终态只有一个");
    wire.shutdown();
}

#[test]
fn session_log_buffer_is_bounded_and_keeps_latest() {
    let mut session = ct_worker::session::Session::default();
    for index in 0..2_500 {
        session.push_log("export", "info", &format!("第 {index} 行"), None);
    }
    assert_eq!(session.logs.len(), 2_000, "日志缓冲必须有界");
    assert_eq!(session.logs[0].message, "第 500 行", "必须丢弃最旧的");
    assert_eq!(session.logs[1999].message, "第 2499 行");
}

#[test]
fn task_issues_page_through_every_problem() {
    let dir = rich_workspace();
    // 让两行数据都落到枚举声明值之外：导出必然带出 2 条结构化问题
    std::fs::write(
        dir.path().join("config/types/rarity.yaml"),
        "kind: enum\nname: Rarity\nvalues:\n  - name: Epic\n",
    )
    .expect("改写枚举");
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let (terminal, events, write_id) = terminal_id(&mut wire, "export", json!({}));
    let to_values = |items: &[ct_protocol::event::Issue]| {
        items
            .iter()
            .map(|item| serde_json::to_value(item).expect("Issue 可序列化"))
            .collect::<Vec<Value>>()
    };
    let problems = match &terminal {
        Message::Error(response) => to_values(&response.error.issues),
        other => panic!("非法数据导出必须失败，实际 {other:?}"),
    };
    assert_eq!(problems.len(), 2, "{problems:?}");
    let streamed: Vec<Value> = events
        .iter()
        .filter_map(|message| match message {
            Message::Issue(event) => Some(serde_json::to_value(event.issue.clone()).unwrap()),
            _ => None,
        })
        .collect();
    assert_eq!(streamed, problems, "issue 事件与终态明细必须一一对应");
    for problem in &problems {
        assert!(
            problem["excelRow"].as_u64().is_some_and(|row| row > 0),
            "问题必须定位到原始 Excel 行：{problem}"
        );
        assert_eq!(problem["resource"], "Item", "{problem}");
        assert_eq!(problem["fieldPath"], "Quality", "{problem}");
    }

    let tasks = wire.payload("tasks.list", json!({}));
    let task = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["requestId"] == json!(write_id))
        .unwrap_or_else(|| panic!("失败任务要能被查到：{tasks}"));
    assert_eq!(task["status"], "error", "{task}");
    assert!(!task["message"].as_str().unwrap().is_empty(), "{task}");
    let task_id = task["id"].as_str().unwrap().to_string();

    let mut paged: Vec<Value> = Vec::new();
    let mut revision: Option<u64> = None;
    let mut cursor: Option<String> = None;
    for _ in 0..5 {
        let params = match &cursor {
            Some(token) => json!({"taskId": task_id, "page": {"limit": 1, "cursor": token}}),
            None => json!({"taskId": task_id, "page": {"limit": 1}}),
        };
        let page = wire.payload("tasks.issues", params);
        let issues = page["issues"].as_array().unwrap();
        assert_eq!(issues.len(), 1, "每页一条：{page}");
        paged.extend(issues.iter().cloned());
        let at = page["revision"].as_u64().expect("分页响应必须带 revision");
        revision = Some(match revision {
            Some(previous) => {
                assert_eq!(previous, at, "翻页期间不得换 revision");
                previous
            }
            None => at,
        });
        cursor = page["nextCursor"].as_str().map(str::to_string);
        if cursor.is_none() {
            break;
        }
    }
    assert_eq!(paged, problems, "分页拼接必须等于终态明细：{paged:?}");
    wire.shutdown();
}
