//! 握手与版本协商（任务 1.4/6.2）：不兼容时禁用业务、能力清单、空白行容忍。

use ct_protocol::message::Message;
use ct_protocol::version::PROTOCOL_VERSION;
use ct_tests_protocol::{minimal_workspace, Wire, QUIET};

fn error_of(raw: &str) -> Message {
    serde_json::from_str(raw).unwrap_or_else(|e| panic!("非法协议消息 {e}: {raw}"))
}

#[test]
fn handshake_declares_version_and_capabilities() {
    let mut wire = Wire::start();
    wire.hello(PROTOCOL_VERSION);
    let ack = match wire.message() {
        Message::Hello(ack) => ack,
        other => panic!("应回 hello，实际 {other:?}"),
    };
    wire.close_input();
    wire.wait_exit().expect("worker 干净退出");
    assert_eq!(ack.protocol_version, PROTOCOL_VERSION);
    assert!(!ack.core_version.is_empty(), "coreVersion 必须可诊断");
    for capability in ["workspace", "export", "tasks", "cancel", "shutdown"] {
        assert!(
            ack.capabilities.iter().any(|c| c == capability),
            "缺少能力 {capability}：{:?}",
            ack.capabilities
        );
    }
}

#[test]
fn incompatible_version_closes_connection_without_running_business() {
    let dir = minimal_workspace();
    let mut wire = Wire::start();
    wire.bind_root(dir.path());
    wire.hello(PROTOCOL_VERSION + 99);
    match error_of(&wire.line()) {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), "protocol-mismatch");
            // 握手失败无法归属请求：信封字段必须整体缺席
            assert_eq!(response.request_id, None);
            assert_eq!(response.workspace_id, None);
            assert_eq!(response.seq, None);
        }
        other => panic!("应回 protocol-mismatch，实际 {other:?}"),
    }
    // 协商失败：worker 立即退出，业务请求既不会被执行也不会有终态
    wire.close_input();
    wire.wait_exit().expect("worker 干净退出");
    assert!(
        !wire.try_send_line(
            &serde_json::json!({
                "type": "request",
                "requestId": 7,
                "method": "workspace.open",
                "workspaceRoot": dir.path().to_string_lossy(),
                "params": {},
            })
            .to_string()
        ),
        "握手失败后连接必须已关闭"
    );
    assert!(
        wire.line_within(QUIET).is_none(),
        "握手失败后不得执行任何业务请求"
    );
}

#[test]
fn business_message_before_hello_is_rejected() {
    let dir = minimal_workspace();
    let mut wire = Wire::start();
    wire.bind_root(dir.path());
    wire.request(1, "workspace.open", serde_json::json!({}));
    match error_of(&wire.line()) {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), "malformed-message");
            assert_eq!(response.request_id, None);
            assert!(response.error.message.contains("hello"));
        }
        other => panic!("握手前业务消息应被拒绝，实际 {other:?}"),
    }
    wire.close_input();
    wire.wait_exit().expect("worker 干净退出");
}

#[test]
fn empty_lines_are_tolerated_between_requests() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.send_line("");
    wire.send_line("   ");
    let snapshot = wire.payload("workspace.open", serde_json::json!({}));
    assert_eq!(snapshot["status"], "ready", "{snapshot}");
    wire.shutdown();
}
