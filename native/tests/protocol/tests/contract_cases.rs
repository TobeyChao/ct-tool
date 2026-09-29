//! 同源契约夹具（任务 6.11）：Rust 侧用**真实 worker** 逐例执行
//! `native/fixtures/protocol/wire-cases.json`，Dart 侧解码同一批消息。
//!
//! 覆盖：重复 requestId、输入变化后的分页令牌失效、重连不重放写任务、
//! 候选代次回显、大整数双向精确、安全关闭。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use ct_protocol::message::Message;
use ct_protocol::version::PROTOCOL_VERSION;
use ct_tests_protocol::{minimal_workspace, rich_workspace, schema_revision, Wire, IDLE};
use serde_json::{json, Value};
use tempfile::TempDir;

#[derive(serde::Deserialize)]
struct Fixture {
    #[serde(rename = "protocolVersion")]
    protocol_version: u64,
    cases: Vec<Case>,
}

#[derive(serde::Deserialize)]
struct Case {
    name: String,
    #[allow(dead_code)]
    title: String,
    workspace: String,
    frames: Vec<Frame>,
}

#[derive(serde::Deserialize)]
struct Frame {
    #[serde(rename = "dir")]
    direction: String,
    #[serde(default)]
    conn: Option<u64>,
    #[serde(default)]
    hello: Option<Value>,
    #[serde(default)]
    request: Option<Value>,
    #[serde(default)]
    change: Option<String>,
    #[serde(default)]
    expected: Option<Value>,
}

fn fixture_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/protocol/wire-cases.json")
}

fn fixture() -> Fixture {
    let path = fixture_path();
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("读取契约夹具失败 {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("契约夹具非法 JSON: {e}"))
}

#[test]
fn fixture_declares_current_protocol_version() {
    let loaded = fixture();
    assert_eq!(
        loaded.protocol_version,
        u64::from(PROTOCOL_VERSION),
        "夹具必须与当前协议主版本同源"
    );
    assert!(
        loaded.cases.len() >= 7,
        "夹具用例不足：{}",
        loaded.cases.len()
    );
    let names: Vec<&str> = loaded.cases.iter().map(|case| case.name.as_str()).collect();
    for required in [
        "duplicate_request_id",
        "stale_page_after_input_change",
        "reconnect_reuses_ids_without_replay",
        "big_integer_roundtrip",
        "candidate_generation_echo",
        "shutdown_flow",
    ] {
        assert!(names.contains(&required), "缺少契约场景 {required}");
    }
}

#[test]
fn every_case_executes_against_the_real_worker() {
    for case in fixture().cases {
        run_case(&case);
    }
}

fn workspace_for(kind: &str) -> TempDir {
    match kind {
        "rich" => rich_workspace(),
        _ => minimal_workspace(),
    }
}

fn run_case(case: &Case) {
    let dir = workspace_for(&case.workspace);
    let root = dir.path().to_string_lossy().to_string();
    let mut current_conn = 0u64;
    let mut wire: Option<Wire> = None;
    let mut actual_by_id: HashMap<u64, Value> = HashMap::new();
    let mut last_seq = 0u64;
    let mut checked = 0usize;

    for frame in &case.frames {
        let want_conn = frame.conn.unwrap_or(1);
        if want_conn != current_conn {
            close_connection(&mut wire);
            current_conn = want_conn;
            last_seq = 0;
            let mut fresh = Wire::start();
            fresh.bind_root(dir.path());
            wire = Some(fresh);
        }
        let wire = wire.as_mut().expect("夹具必须先建立连接");
        match frame.direction.as_str() {
            "in" => {
                if let Some(version) = &frame.hello {
                    if version == "v1" {
                        wire.hello(PROTOCOL_VERSION);
                        assert!(
                            matches!(wire.message(), Message::Hello(_)),
                            "[{}] v1 握手必须返回 hello",
                            case.name
                        );
                    } else {
                        let number = version
                            .as_u64()
                            .unwrap_or_else(|| panic!("hello 版本必须是 v1 或整数：{version}"));
                        wire.hello(number as u32);
                    }
                    continue;
                }
                if let Some(relative) = &frame.change {
                    let path = dir.path().join(relative);
                    let text = std::fs::read_to_string(&path).expect("读取待改文件");
                    std::fs::write(&path, format!("{text}# 外部改动\n")).expect("写入待改文件");
                    continue;
                }
                let request = frame
                    .request
                    .as_ref()
                    .unwrap_or_else(|| panic!("[{}] 入站帧缺少 hello/request/change", case.name));
                let prepared = substitute(request, dir.path(), &actual_by_id);
                let mut envelope = prepared.clone();
                let object = envelope.as_object_mut().expect("request 帧必须是对象");
                object.insert("type".to_string(), json!("request"));
                object.insert("workspaceRoot".to_string(), json!(root));
                wire.send_line(&envelope.to_string());
            }
            "out" => {
                let expected = frame.expected.as_ref().expect("出站帧必须带 expected");
                let actual = read_next(wire, expected, &case.name);
                let value: Value = serde_json::from_str(&actual)
                    .unwrap_or_else(|e| panic!("[{}] 出站消息非法 JSON: {e}\n{actual}", case.name));
                validate_against_schema(&value, &case.name);
                if let Some(seq) = value["seq"].as_u64() {
                    assert!(
                        seq > last_seq,
                        "[{}] seq 必须连接内单调递增：{last_seq} -> {seq}\n{actual}",
                        case.name
                    );
                    last_seq = seq;
                }
                if let Some(id) = value["requestId"].as_u64() {
                    actual_by_id.insert(id, value.clone());
                }
                assert_matches(&value, expected, &case.name, "");
                checked += 1;
            }
            other => panic!("[{}] 未知 dir: {other}", case.name),
        }
    }
    close_connection(&mut wire);
    assert!(checked > 0, "[{}] 夹具没有核对任何出站消息", case.name);
}

fn close_connection(wire: &mut Option<Wire>) {
    if let Some(mut current) = wire.take() {
        current.close_input();
        let _ = current.wait_exit();
    }
}

/// 读取下一条与期望同类型的消息；progress/log/issue 属于事件流，跳过。
fn read_next(wire: &mut Wire, expected: &Value, case: &str) -> String {
    let want = expected["type"].as_str().expect("expected 必须带 type");
    loop {
        let raw = wire
            .line_within(IDLE)
            .unwrap_or_else(|| panic!("[{case}] 等待 {want} 超时；已收到 {:?}", wire.received));
        let Ok(value) = serde_json::from_str::<Value>(&raw) else {
            panic!("[{case}] 非法 JSON：{raw}");
        };
        let got = value["type"].as_str().unwrap_or_default();
        if got == want {
            return raw;
        }
        assert!(
            matches!(got, "progress" | "log" | "issue"),
            "[{case}] 期望 {want}，实际 {got}：{raw}"
        );
    }
}

/// 递归子集匹配：占位符按规则校验，未列出的字段不比较。
fn assert_matches(actual: &Value, expected: &Value, case: &str, trail: &str) {
    let where_about = if trail.is_empty() {
        "根".to_string()
    } else {
        trail.to_string()
    };
    match expected {
        Value::String(text) if text.starts_with('<') && text.ends_with('>') => {
            let ok = match text.as_str() {
                "<n>" => actual.as_u64().is_some_and(|value| value > 0),
                "<id>" => actual.as_str().is_some_and(|value| {
                    value.len() >= 8 && value.chars().all(|c| c.is_ascii_hexdigit())
                }),
                "<message>" => actual.as_str().is_some_and(|value| !value.is_empty()),
                "<sha256>" => actual.as_str().is_some_and(|value| {
                    value.len() == 64 && value.chars().all(|c| c.is_ascii_hexdigit())
                }),
                "<any>" => !actual.is_null(),
                other => panic!("[{case}] 未知占位符 {other}"),
            };
            assert!(ok, "[{case}] {where_about} 不满足 {text}：{}", actual);
        }
        Value::Object(want) => {
            let Some(object) = actual.as_object() else {
                panic!("[{case}] {where_about} 期望对象，实际 {actual}");
            };
            for (key, sub) in want {
                // 期望 null 表示"缺席或为 null"（线格式对 None 字段直接省略键）
                let value = object.get(key).cloned().unwrap_or(Value::Null);
                assert_matches(&value, sub, case, &format!("{where_about}.{key}"));
            }
        }
        Value::Array(want) => {
            let Some(items) = actual.as_array() else {
                panic!("[{case}] {where_about} 期望数组，实际 {actual}");
            };
            assert_eq!(
                items.len(),
                want.len(),
                "[{case}] {where_about} 长度不一致：{actual}"
            );
            for (index, sub) in want.iter().enumerate() {
                assert_matches(&items[index], sub, case, &format!("{where_about}[{index}]"));
            }
        }
        Value::Null => {
            assert!(
                actual.is_null(),
                "[{case}] {where_about} 必须缺席或为 null，实际 {actual}"
            );
        }
        scalar => assert_eq!(
            actual, scalar,
            "[{case}] {where_about} 期望 {scalar}，实际 {actual}"
        ),
    }
}

/// 展开 `<schemaRevision>` 与 `{"$from": "<requestId>.<路径>"}`。
fn substitute(value: &Value, root: &Path, actuals: &HashMap<u64, Value>) -> Value {
    match value {
        Value::String(text) if text == "<schemaRevision>" => {
            json!(schema_revision(root))
        }
        Value::Object(object) => {
            if let Some(path) = object.get("$from").and_then(Value::as_str) {
                return resolve(path, actuals);
            }
            Value::Object(
                object
                    .iter()
                    .map(|(key, sub)| (key.clone(), substitute(sub, root, actuals)))
                    .collect(),
            )
        }
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|item| substitute(item, root, actuals))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn resolve(path: &str, actuals: &HashMap<u64, Value>) -> Value {
    let (id, rest) = path
        .split_once('.')
        .unwrap_or_else(|| panic!("$from 路径必须是 <requestId>.<字段>：{path}"));
    let id: u64 = id.parse().expect("$from 首段必须是 requestId");
    let mut cursor = actuals
        .get(&id)
        .unwrap_or_else(|| panic!("$from 引用了尚未出现的请求 #{id}"))
        .clone();
    for part in rest.split('.') {
        cursor = cursor.get(part).cloned().unwrap_or(Value::Null);
    }
    cursor
}

fn validate_against_schema(value: &Value, case: &str) {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../docs/protocol/schema/protocol.v1.json");
    let text = std::fs::read_to_string(&path).expect("读取 JSON Schema");
    let compiled =
        jsonschema::draft202012::new(&serde_json::from_str::<Value>(&text).expect("schema 合法"))
            .expect("schema 可编译");
    let errors: Vec<String> = compiled
        .iter_errors(value)
        .map(|error| error.to_string())
        .collect();
    assert!(
        errors.is_empty(),
        "[{case}] 消息不符合 protocol.v1.json：{errors:?}\n{value}"
    );
}
