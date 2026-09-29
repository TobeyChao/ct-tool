//! requestId 语义：连接内唯一、重复拒绝且写请求不执行两次、重连不重放写任务、
//! 大整数双向不丢精度（任务 6.3/6.11）。

use ct_protocol::message::Message;
use ct_tests_protocol::{minimal_workspace, schema_revision, Wire};
use serde_json::json;

#[test]
fn duplicate_read_request_is_rejected() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.request(100, "workspace.open", json!({}));
    assert!(
        matches!(wire.until_terminal(100).0, Message::Result(_)),
        "首次请求必须被接受"
    );
    wire.request(100, "workspace.open", json!({}));
    let (second, events) = wire.until_terminal(100);
    match second {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), "duplicate-request-id");
            assert_eq!(response.request_id, Some(100), "重复错误必须可归属");
        }
        other => panic!("重复 requestId 应被拒绝，实际 {other:?}"),
    }
    assert!(events.is_empty(), "拒绝不得产生事件：{events:?}");
    wire.shutdown();
}

#[test]
fn duplicate_write_request_executes_only_once() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    let params = json!({"table": "Item"});

    wire.request(200, "template.generate", params.clone());
    assert!(matches!(wire.until_terminal(200).0, Message::Result(_)));
    assert!(dir.path().join("excel/Item.xlsx").exists());

    // 同一 ID 重发：必须拒绝，且模板任务不得再执行一次
    wire.request(200, "template.generate", params);
    match wire.until_terminal(200).0 {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), "duplicate-request-id")
        }
        other => panic!("重复写请求应被拒绝，实际 {other:?}"),
    }
    let tasks = wire.payload("tasks.list", json!({}));
    let hits = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|task| task["method"] == "template.generate")
        .count();
    assert_eq!(hits, 1, "写请求只能执行一次：{tasks}");
    wire.shutdown();
}

#[test]
fn ids_are_scoped_per_connection_and_writes_are_not_replayed() {
    let dir = minimal_workspace();
    let mut first = Wire::connected();
    first.bind_root(dir.path());
    first.payload("workspace.open", json!({}));
    first.request(5, "template.generate", json!({"table": "Item"}));
    assert!(matches!(first.until_terminal(5).0, Message::Result(_)));
    first.close_input();
    first.wait_exit().expect("干净退出");

    // 重连：同一 requestId 可再次使用，但历史写任务不得复活或重放
    let mut again = Wire::connected();
    again.bind_root(dir.path());
    again.payload("workspace.open", json!({}));
    let tasks = again.payload("tasks.list", json!({}));
    assert_eq!(
        tasks["tasks"].as_array().unwrap().len(),
        0,
        "新连接不得带回上一连接的写任务：{tasks}"
    );
    again.request(5, "workspace.status", json!({}));
    assert!(matches!(again.until_terminal(5).0, Message::Result(_)));
    again.shutdown();
}

#[test]
fn big_integers_survive_both_directions() {
    let dir = minimal_workspace();
    let mut wire = Wire::connected();
    wire.bind_root(dir.path());
    wire.payload("workspace.open", json!({}));
    // 2^53+1：JSON number 无法精确表示，必须走 $int 标签
    let tagged = json!({"$int": "9007199254740993"});
    let params = json!({
        "schemaRevision": schema_revision(dir.path()),
        "commands": [],
        "cursor": "1",
        "draftGeneration": tagged,
    });
    wire.request(300, "schema.candidate", params);
    let (terminal, _) = wire.until_terminal(300);
    match &terminal {
        Message::Result(response) => {
            assert_eq!(
                response.payload["draftGeneration"], tagged,
                "回显必须保持标签形式：{}",
                response.payload
            );
        }
        other => panic!("候选应成功，实际 {other:?}"),
    }
    // 线格式必须是标签对象，而不是丢精度的裸 number
    let raw = wire.received.last().expect("应收到终态原始行");
    let on_wire: serde_json::Value = serde_json::from_str(raw).expect("终态必须是合法 JSON");
    assert_eq!(
        on_wire["payload"]["draftGeneration"]["$int"].as_str(),
        Some("9007199254740993"),
        "{raw}"
    );
    assert!(
        !raw.contains(":9007199254740993"),
        "不得以裸 number 送出：{raw}"
    );
    let mut decoded = on_wire["payload"].clone();
    ct_protocol::bigint::decode_value(&mut decoded);
    assert_eq!(
        decoded["draftGeneration"].as_u64(),
        Some(9_007_199_254_740_993)
    );
    wire.shutdown();
}
