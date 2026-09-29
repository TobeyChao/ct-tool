//! 信封层坏消息：非法 JSON、缺字段、非 UTF-8、超限、客户端误发事件（任务 6.3）。

use ct_protocol::message::{Message, MAX_MESSAGE_BYTES};
use ct_tests_protocol::{minimal_workspace, Wire, QUIET};
use serde_json::json;

fn parse(raw: &str) -> Message {
    serde_json::from_str(raw).unwrap_or_else(|e| panic!("非法协议消息 {e}: {raw}"))
}

/// 连接级错误：无法归属 requestId，信封字段必须整体缺席。
fn assert_connection_error(raw: &str, code: &str) {
    match parse(raw) {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), code, "{response:?}");
            assert_eq!(response.request_id, None, "{response:?}");
            assert_eq!(response.workspace_id, None, "{response:?}");
            assert_eq!(response.seq, None, "{response:?}");
        }
        other => panic!("应回 {code} 连接级错误，实际 {other:?}"),
    }
}

#[test]
fn truncated_json_is_rejected_and_connection_survives() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.send_line(r#"{"type":"request","requestId":999,"method":"workspace.open""#);
    assert_connection_error(&wire.line(), "malformed-message");
    let snapshot = wire.payload("workspace.open", json!({}));
    assert_eq!(snapshot["status"], "ready", "坏行之后连接必须可用");
    wire.shutdown();
}

#[test]
fn non_object_and_missing_fields_are_malformed() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    for bad in [
        "[1,2,3]",
        r#"{"type":"request"}"#,
        r#"{"type":"request","requestId":"x","method":"validate","workspaceRoot":"","params":{}}"#,
        r#"{"type":"nope"}"#,
    ] {
        wire.send_line(bad);
        assert_connection_error(&wire.line(), "malformed-message");
    }
    let snapshot = wire.payload("workspace.open", json!({}));
    assert_eq!(snapshot["status"], "ready");
    wire.shutdown();
}

#[test]
fn invalid_utf8_line_is_rejected_without_killing_worker() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    // {"type":<非法 UTF-8>}
    wire.send_bytes(&[
        0x7b, 0x22, 0x74, 0x79, 0x70, 0x65, 0x22, 0x3a, 0xff, 0xfe, 0x7d,
    ]);
    assert_connection_error(&wire.line(), "malformed-message");
    let snapshot = wire.payload("workspace.open", json!({}));
    assert_eq!(snapshot["status"], "ready");
    wire.shutdown();
}

#[test]
fn oversized_message_is_rejected_and_stream_resyncs() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    let padding = "x".repeat(MAX_MESSAGE_BYTES + 1);
    wire.send(&json!({
        "type": "request",
        "requestId": 4242,
        "method": "workspace.open",
        "workspaceRoot": "",
        "params": {"pad": padding},
    }));
    assert_connection_error(&wire.line(), "message-too-large");
    // 超限整行丢弃后必须能从下一条消息重新同步
    let snapshot = wire.payload("workspace.open", json!({}));
    assert_eq!(snapshot["status"], "ready");
    assert!(
        wire.line_within(QUIET).is_none(),
        "被丢弃的请求不得有任何终态：{:?}",
        wire.received
    );
    wire.shutdown();
}

#[test]
fn message_exactly_at_the_limit_is_accepted() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    let root = dir.path().to_string_lossy().to_string();
    let frame = |pad: usize| {
        json!({
            "type": "request", "requestId": 7, "method": "workspace.open",
            "workspaceRoot": root, "params": {"pad": "x".repeat(pad)}
        })
        .to_string()
    };
    // 纯 ASCII 填充：每多一个字符线长多一字节，可直接反推恰好等于上限的填充
    let line = frame(MAX_MESSAGE_BYTES - frame(0).len());
    assert_eq!(line.len(), MAX_MESSAGE_BYTES, "夹具必须正好等于上限");
    wire.send_line(&line);
    let (terminal, _) = wire.until_terminal(7);
    assert!(matches!(terminal, Message::Result(_)), "{terminal:?}");
    wire.shutdown();
}

#[test]
fn client_sent_events_after_hello_are_rejected() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.send(&json!({
        "type": "progress", "requestId": 1, "workspaceId": "fake",
        "seq": 1, "stage": "x", "done": 0, "total": 1
    }));
    assert_connection_error(&wire.line(), "malformed-message");
    let snapshot = wire.payload("workspace.open", json!({}));
    assert_eq!(snapshot["status"], "ready", "误发事件不得污染会话");
    wire.shutdown();
}

#[test]
fn each_request_has_exactly_one_terminal() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.request(11, "workspace.open", json!({}));
    wire.request(12, "resources.list", json!({}));
    for id in [11, 12] {
        let (terminal, events) = wire.until_terminal(id);
        assert!(
            matches!(terminal, Message::Result(_)),
            "#{id}: {terminal:?}"
        );
        assert!(events.is_empty(), "只读方法不得产生事件：{events:?}");
    }
    assert!(
        wire.line_within(QUIET).is_none(),
        "不得有多余终态：{:?}",
        wire.received
    );
    wire.shutdown();
}
