//! 分页契约（任务 6.3/6.11）：令牌绑定快照代次；内部写入或外部改动后旧令牌
//! 必须返回 stale-page，不得混合两个 revision 的行数据。

use ct_protocol::event::Issue;
use ct_tests_protocol::{rich_workspace, schema_revision, Wire};
use serde_json::{json, Value};

fn rows_of(payload: &Value) -> Vec<Value> {
    payload["rows"].as_array().cloned().unwrap_or_default()
}

#[test]
fn preview_pages_walk_through_rows_without_mixing() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let first = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    assert_eq!(rows_of(&first).len(), 1, "{first}");
    let revision = first["revision"].as_u64().expect("必须回传 revision");
    let cursor = first["nextCursor"]
        .as_str()
        .expect("还有下一页")
        .to_string();

    let second = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1, "cursor": cursor}}),
    );
    assert_eq!(second["revision"], revision, "同一快照内 revision 必须一致");
    assert_eq!(rows_of(&second).len(), 1, "{second}");
    assert_ne!(
        rows_of(&first)[0],
        rows_of(&second)[0],
        "两页必须给出不同的行，不得重叠或混排"
    );
    assert!(
        second["nextCursor"].is_null(),
        "最后一页不得再给令牌：{second}"
    );
    wire.shutdown();
}

#[test]
fn successful_write_invalidates_older_pages() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let first = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    let cursor = first["nextCursor"]
        .as_str()
        .expect("应有下一页")
        .to_string();

    // 走 i18n.query 拿到真实键，再用写方法改一条译文（内容变化即快照变化）
    let query = wire.payload(
        "i18n.query",
        json!({"table": "Item", "lang": "en", "page": {}}),
    );
    let key = query["entries"][0]["key"]
        .as_str()
        .unwrap_or_else(|| panic!("夹具应含译文条目：{query}"))
        .to_string();
    let saved = wire.payload(
        "i18n.save",
        json!({"table": "Item", "lang": "en", "key": key, "text": "Contract Sword", "confirmed": true}),
    );
    let status = saved["status"].as_str().unwrap_or_default().to_string();
    assert!(
        ["confirmed", "translated", "stale", "orphan"].contains(&status.as_str()),
        "译文保存应回传条目状态：{saved}"
    );

    let code = wire.error_code(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1, "cursor": cursor}}),
    );
    assert_eq!(code, "stale-page", "写入后旧令牌必须失效");
    wire.shutdown();
}

#[test]
fn external_edit_invalidates_pages() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let first = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    let cursor = first["nextCursor"]
        .as_str()
        .expect("应有下一页")
        .to_string();

    // 工作区被外部修改（不经 worker）：分页令牌同样必须失效
    let path = dir.path().join("config/global.yaml");
    let text = std::fs::read_to_string(&path).expect("读取全局配置");
    std::fs::write(&path, format!("{text}# 外部改动\n")).expect("写入全局配置");

    let code = wire.error_code(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1, "cursor": cursor}}),
    );
    assert_eq!(code, "stale-page", "外部输入变化必须使旧快照过期");
    // 整页重查必须可用（客户端按新 revision 重新取页）
    let retried = wire.payload(
        "table.preview",
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    assert_ne!(
        retried["revision"].as_u64().expect("revision"),
        first["revision"].as_u64().expect("revision"),
        "重查必须拿到新 revision"
    );
    wire.shutdown();
}

#[test]
fn unknown_or_tampered_cursor_is_stale() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    for bad in ["", "abc", "999.0", "1.999999", "0.-1"] {
        let code = wire.error_code(
            "table.preview",
            json!({"table": "Item", "page": {"limit": 1, "cursor": bad}}),
        );
        assert_eq!(code, "stale-page", "非法令牌 {bad} 必须按过期处理");
    }
    wire.shutdown();
}

#[test]
fn logs_pages_are_contiguous_and_share_one_revision() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    wire.payload("export", json!({"all": true}));

    let whole = wire.payload("logs.list", json!({"page": {}}));
    let total = whole["entries"].as_array().expect("entries").len();
    assert!(total >= 3, "导出日志应足够分页：{total} 条");
    let revision = whole["revision"].as_u64().expect("revision");

    let mut paged: Vec<Value> = Vec::new();
    let mut cursor: Option<String> = None;
    for _ in 0..10 {
        let params = match &cursor {
            Some(token) => json!({"page": {"limit": 2, "cursor": token}}),
            None => json!({"page": {"limit": 2}}),
        };
        let page = wire.payload("logs.list", params);
        assert_eq!(page["revision"], revision, "翻页期间不得换 revision");
        let entries = page["entries"].as_array().expect("entries");
        assert!(!entries.is_empty(), "空页不得返回令牌：{page}");
        paged.extend(entries.iter().cloned());
        cursor = page["nextCursor"].as_str().map(str::to_string);
        if cursor.is_none() {
            break;
        }
    }
    assert_eq!(
        paged.len(),
        total,
        "分页拼接必须等于整表：{} vs {total}",
        paged.len()
    );
    assert_eq!(
        paged,
        whole["entries"].as_array().expect("entries").to_vec(),
        "顺序必须稳定"
    );
    wire.shutdown();
}

#[test]
fn revisions_never_regress_across_calls() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    let mut seen: Vec<u64> = Vec::new();
    let mut remember = |payload: &Value| {
        if let Some(at) = payload["revision"].as_u64() {
            seen.push(at);
        }
    };
    wire.bind_root(dir.path());
    remember(&wire.payload("workspace.open", json!({})));
    remember(&wire.payload("resources.list", json!({})));
    remember(&wire.payload("table.preview", json!({"table": "Item", "page": {}})));
    remember(&wire.payload(
        "i18n.query",
        json!({"table": "Item", "lang": "en", "page": {}}),
    ));
    remember(&wire.payload("logs.list", json!({"page": {}})));
    let candidate = wire.payload(
        "schema.candidate",
        json!({"schemaRevision": schema_revision(dir.path()), "commands": [], "cursor": "1", "draftGeneration": 1}),
    );
    let _ = candidate;
    remember(&wire.payload("workspace.status", json!({})));
    wire.payload("export", json!({"all": true}));
    remember(&wire.payload("logs.list", json!({"page": {}})));
    assert!(seen.len() >= 6, "应有足够 revision 样本：{seen:?}");
    assert!(
        seen.windows(2).all(|pair| pair[0] <= pair[1]),
        "revision 必须单调不减：{seen:?}"
    );
    assert!(
        seen.last().expect("最后一个") > seen.first().expect("第一个"),
        "导出写入后 revision 必须推进：{seen:?}"
    );
    wire.shutdown();
}

#[test]
fn task_issues_page_through_structured_problems() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    // 制造一次带结构化问题的写失败：给不存在的表加字段
    let commands = json!([
        {"kind": "add_field", "payload": {"owner": "table:NoSuchTable", "field": {"name": "X", "type": "int32"}}}
    ]);
    let params = json!({
        "schemaRevision": schema_revision(dir.path()),
        "candidateHash": "0000000000000000000000000000000000000000000000000000000000000000",
        "commands": commands,
        "cursor": "1",
    });
    let id = wire.call("schema.save", params);
    let (terminal, events) = wire.until_terminal(id);
    let issues_in_events: Vec<&Issue> = events
        .iter()
        .filter_map(|message| match message {
            ct_protocol::message::Message::Issue(event) => Some(&event.issue),
            _ => None,
        })
        .collect();
    match &terminal {
        ct_protocol::message::Message::Error(response) => {
            assert!(!response.error.issues.is_empty(), "{response:?}");
            assert_eq!(
                issues_in_events.len(),
                response.error.issues.len(),
                "issue 事件不可丢弃，且必须与终态明细一一对应"
            );
            assert!(
                events
                    .iter()
                    .position(|message| matches!(message, ct_protocol::message::Message::Issue(_)))
                    .is_some_and(|first| {
                        events.iter().enumerate().all(|(index, message)| {
                            !matches!(message, ct_protocol::message::Message::Issue(_))
                                || index >= first
                        })
                    }),
                "issue 事件必须紧邻终态：{events:?}"
            );
        }
        other => panic!("非法保存必须失败，实际 {other:?}"),
    }
    wire.shutdown();
}
