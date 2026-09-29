//! 取消与安全关闭（任务 6.3）：忙碌期可读控制消息、发布边界、断连未知终态。

use ct_protocol::message::Message;
use ct_tests_protocol::{minimal_workspace, rich_workspace, Wire, QUIET};
use serde_json::json;

fn state_of(terminal: &Message) -> String {
    match terminal {
        Message::Result(response) => response.payload.as_str().unwrap_or_default().to_string(),
        other => panic!("cancel 应返回 result，实际 {other:?}"),
    }
}

#[test]
fn cancel_states_are_exhaustive() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    // 未知请求
    let id = wire.call("cancel", json!({"targetRequestId": 4242}));
    assert_eq!(state_of(&wire.until_terminal(id).0), "unknown_request");

    // 只读方法没有任务记录：同样不可取消
    let read_id = wire.call("resources.list", json!({}));
    wire.until_terminal(read_id);
    let id = wire.call("cancel", json!({"targetRequestId": read_id}));
    assert_eq!(state_of(&wire.until_terminal(id).0), "unknown_request");

    // 已有终态的写任务：already_terminal（不得被误报为可重放）
    let write_id = wire.call("template.generate", json!({"table": "Item"}));
    assert!(matches!(
        wire.until_terminal(write_id).0,
        Message::Result(_)
    ));
    let id = wire.call("cancel", json!({"targetRequestId": write_id}));
    assert_eq!(state_of(&wire.until_terminal(id).0), "already_terminal");
    wire.shutdown();
}

#[test]
fn control_messages_are_served_while_a_write_task_runs() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));

    let export_id = wire.call("export", json!({"all": true}));
    let cancel_id = wire.call("cancel", json!({"targetRequestId": export_id}));
    let (cancel_terminal, before) = wire.until_terminal(cancel_id);
    let state = state_of(&cancel_terminal);
    assert!(
        ["cancelling", "already_terminal"].contains(&state.as_str()),
        "cancel 只能返回三态之一，实际 {state}"
    );
    if state == "cancelling" {
        // 控制消息先于写任务终态返回：主循环没有被写任务阻塞
        assert!(
            !before.iter().any(|message| matches!(
                message,
                Message::Result(response) if response.request_id == export_id
            )),
            "取消响应必须先于导出终态：{before:?}"
        );
    }
    let (export_terminal, events) = wire.until_terminal(export_id);
    let payload = match &export_terminal {
        // 取消也是成功终态 + outcome=cancelled，不是 error
        Message::Result(response) => response.payload.clone(),
        other => panic!("导出终态应为 result，实际 {other:?}"),
    };
    if state == "cancelling" {
        // The request may arrive after the last reversible checkpoint. In
        // that case the committed export must retain its success outcome.
        assert!(
            payload["outcome"] == "cancelled" || payload["outcome"] == "succeeded",
            "{payload}"
        );
    } else {
        assert_eq!(
            payload["outcome"], "succeeded",
            "already_terminal 必须已有成功终态"
        );
    }
    assert!(
        events
            .iter()
            .any(|message| matches!(message, Message::Progress(_))),
        "强制导出应上报阶段进度：{events:?}"
    );
    assert!(wire.line_within(QUIET).is_none(), "每个请求只允许一个终态");
    wire.shutdown();
}

#[test]
fn requests_after_shutdown_are_rejected_as_busy() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let id = wire.call("shutdown", json!({}));
    assert!(matches!(wire.until_terminal(id).0, Message::Result(_)));
    let late = wire.call("workspace.status", json!({}));
    match wire.until_terminal(late).0 {
        Message::Error(response) => assert_eq!(response.error.code.to_string(), "busy"),
        other => panic!("关闭后新请求必须被拒绝，实际 {other:?}"),
    }
    wire.close_input();
    wire.wait_exit().expect("worker 干净退出");
}

#[test]
fn eof_disconnect_still_delivers_the_terminal_state() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let export_id = wire.call("export", json!({}));
    // 客户端立刻断连（stdin EOF）：写任务仍要跑到发布边界
    wire.close_input();
    assert!(
        matches!(wire.until_terminal(export_id).0, Message::Result(_)),
        "EOF 前已接受的请求必须送达终态"
    );
    wire.wait_exit()
        .expect("EOF 视为隐式 shutdown，必须干净退出");
    assert!(
        dir.path().join("output/json/item_zh.json").exists(),
        "断连不得留下半成品：发布必须完整"
    );
}

#[test]
fn disconnect_without_reader_leaves_the_task_unknown() {
    let dir = rich_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let seen_before = wire.received.len();
    let export_id = wire.call("export", json!({"all": true}));
    // 读端关闭：终态无处送达，客户端只能把它标为 unknown（v1.md §7）
    wire.close_output();
    wire.close_input();
    wire.wait_exit()
        .expect("写端失效时不得 panic，也不得吞掉写任务");
    assert_eq!(
        wire.received.len(),
        seen_before,
        "读端已关闭，不应声称送达任何后续消息（请求 #{export_id} 属未知终态）"
    );
}
