//! worker 端到端操作链（rust-native-core 任务 6.2）：
//! 用独立协议客户端驱动 `ct worker` 子进程，不依赖 Flutter。

use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

use ct_protocol::message::{Hello, Message};
use ct_protocol::version::PROTOCOL_VERSION;
use serde_json::{json, Value};

fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, content.replace("\r\n", "\n")).unwrap();
}

/// 最小可导出工作区（Item 表 + 模板由 worker 的 template.generate 生成）。
fn setup() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    write(
        &root.join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\n",
    );
    write(
        &root.join("config/types/quality.yaml"),
        "kind: enum\nname: Quality\nvalues:\n  - name: Low\n  - name: High\n",
    );
    write(
        &root.join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Name\n    type: string\n    i18n: true\nindexes:\n  - kind: codename\n",
    );
    dir
}

struct Client {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl Client {
    fn spawn() -> Self {
        let mut child = Command::new(env!("CARGO_BIN_EXE_ct"))
            .args(["worker"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("启动 ct worker");
        let stdin = child.stdin.take().unwrap();
        let stdout = BufReader::new(child.stdout.take().unwrap());
        let mut client = Client {
            child,
            stdin: Some(stdin),
            stdout,
            next_id: 1,
        };
        let hello = Hello {
            protocol_version: PROTOCOL_VERSION,
            core_version: "test-client".to_string(),
            capabilities: vec!["workspace".to_string()],
        };
        client.send_raw(&json!({
            "type": "hello",
            "protocolVersion": hello.protocol_version,
            "coreVersion": hello.core_version,
            "capabilities": hello.capabilities,
        }));
        let reply = client.read_message();
        match reply {
            Message::Hello(ack) => assert_eq!(ack.protocol_version, PROTOCOL_VERSION),
            other => panic!("握手应返回 hello，实际 {other:?}"),
        }
        client
    }

    fn send_raw(&mut self, value: &Value) {
        let stdin = self.stdin.as_mut().expect("stdin 已关闭");
        writeln!(stdin, "{value}").unwrap();
        stdin.flush().unwrap();
    }

    /// 直接写入一行原始文本（用于非法 JSON 夹具）。
    fn write_line(&mut self, text: &str) {
        let stdin = self.stdin.as_mut().expect("stdin 已关闭");
        writeln!(stdin, "{text}").unwrap();
        stdin.flush().unwrap();
    }

    /// 关闭输入管道：shutdown 后 worker 会读完剩余消息并退出。
    fn close_stdin(&mut self) {
        self.stdin = None;
    }

    fn read_message(&mut self) -> Message {
        let mut line = String::new();
        loop {
            line.clear();
            let read = self.stdout.read_line(&mut line).expect("读取消息");
            assert_ne!(read, 0, "worker 提前关闭连接");
            if let Ok(message) = serde_json::from_str::<Message>(line.trim()) {
                return message;
            }
        }
    }

    /// 读取直到某个 requestId 的终态；途中事件按类型收集。
    fn await_terminal(&mut self, request_id: u64) -> (Message, Vec<Message>) {
        let mut events = Vec::new();
        loop {
            let message = self.read_message();
            let matches = match &message {
                Message::Result(response) => response.request_id == request_id,
                Message::Error(response) => response.request_id == Some(request_id),
                _ => false,
            };
            if matches {
                return (message, events);
            }
            events.push(message);
        }
    }

    fn request(&mut self, method: &str, root: &Path, params: Value) -> (Message, Vec<Message>) {
        let id = self.next_id;
        self.next_id += 1;
        self.send_raw(&json!({
            "type": "request",
            "requestId": id,
            "method": method,
            "workspaceRoot": root.to_string_lossy(),
            "params": params,
        }));
        let (terminal, events) = self.await_terminal(id);
        (terminal, events)
    }

    fn payload_of(&mut self, method: &str, root: &Path, params: Value) -> Value {
        let (terminal, _) = self.request(method, root, params);
        match terminal {
            Message::Result(response) => response.payload,
            other => panic!("{method} 应成功，实际 {other:?}"),
        }
    }

    fn error_of(&mut self, method: &str, root: &Path, params: Value) -> (u64, String) {
        let (terminal, _) = self.request(method, root, params);
        match terminal {
            Message::Error(response) => (
                response.request_id.expect("业务错误应带 requestId"),
                response.error.code.to_string(),
            ),
            other => panic!("{method} 应失败，实际 {other:?}"),
        }
    }
}

#[test]
fn full_operation_chain() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let mut client = Client::spawn();

    // 1) 打开工作区（无模板时资源仍可列出）
    let opened = client.payload_of("workspace.open", &root, json!({}));
    assert_eq!(opened["status"], "ready", "{opened}");
    assert_eq!(opened["tables"], 1, "{opened}");

    // 2) 资源清单
    let listed = client.payload_of("resources.list", &root, json!({}));
    let names: Vec<&str> = listed["resources"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["name"].as_str().unwrap())
        .collect();
    assert_eq!(names, ["Item", "Quality"], "{listed}");
    assert_eq!(
        listed["resources"][0]["sourcePath"], "config/schemas/item.yaml",
        "{listed}"
    );
    // 清单自带 schema 定义：编辑器据此显示字段行与枚举成员（顺序即 ordinal）。
    assert_eq!(listed["resources"][0]["primary"], "Id", "{listed}");
    assert_eq!(
        listed["resources"][0]["fields"].as_array().unwrap().len(),
        3,
        "{listed}"
    );
    assert_eq!(
        listed["resources"][1]["values"][0]["name"], "Low",
        "枚举成员必须是 {{name, comment}} 形态：{listed}"
    );
    assert_eq!(
        listed["resources"][1]["values"].as_array().unwrap().len(),
        2,
        "{listed}"
    );
    assert_eq!(
        listed["schemaRevision"].as_str().unwrap().len(),
        64,
        "清单必须直接给出 schema 基线，编辑器才能构造 candidate/保存守卫"
    );
    assert_eq!(
        listed["schemaRevision"],
        schema_revision(&root).as_str(),
        "{listed}"
    );

    // 3) 显式生成模板（写任务：事件 + 终态）
    let (terminal, events) = client.request("template.generate", &root, json!({"table": "Item"}));
    assert!(matches!(terminal, Message::Result(_)), "{terminal:?}");
    assert!(
        events.iter().any(|e| matches!(e, Message::Log(_))),
        "写任务应发出日志事件"
    );
    assert!(root.join("excel/Item.xlsx").exists());

    // 4) 预览（分页 + 令牌绑定）
    let page = client.payload_of(
        "table.preview",
        &root,
        json!({"table": "Item", "page": {"limit": 1}}),
    );
    assert_eq!(page["columns"].as_array().unwrap().len(), 3, "{page}");

    // 5) 候选：加字段 → 净差异 + candidateHash + 回显 draftGeneration
    let commands = json!([
        {"kind": "add_field", "payload": {"owner": "table:Item", "field": {"name": "Price", "type": "int32"}}}
    ]);
    let revision_before = schema_revision(&root);
    let candidate = client.payload_of(
        "schema.candidate",
        &root,
        json!({
            "schemaRevision": revision_before.clone(),
            "commands": commands,
            "cursor": "1",
            "draftGeneration": 7,
        }),
    );
    assert_eq!(candidate["draftGeneration"], 7, "{candidate}");
    assert_eq!(
        candidate["candidateHash"].as_str().unwrap().len(),
        64,
        "{candidate}"
    );
    assert_eq!(
        candidate["netDiff"]["changed"][0]["name"], "Item",
        "{candidate}"
    );
    let candidate_hash = candidate["candidateHash"].as_str().unwrap().to_string();

    // 6) 保存：双守卫 + 仅写 YAML
    let excel_before = std::fs::read(root.join("excel/Item.xlsx")).unwrap();
    let saved = client.payload_of(
        "schema.save",
        &root,
        json!({
            "schemaRevision": schema_revision(&root),
            "candidateHash": candidate_hash,
            "commands": commands,
            "cursor": "1",
        }),
    );
    let new_revision = saved["schemaRevision"].as_str().unwrap().to_string();
    assert_ne!(new_revision, revision_before, "保存后基线必须推进");
    assert_eq!(new_revision, schema_revision(&root), "响应基线即磁盘现状");
    let yaml = std::fs::read_to_string(root.join("config/schemas/item.yaml")).unwrap();
    assert!(yaml.contains("name: Price"), "{yaml}");
    assert_eq!(
        std::fs::read(root.join("excel/Item.xlsx")).unwrap(),
        excel_before,
        "保存不得触碰 Excel"
    );

    // 7) 旧 candidateHash 再保存 → 拒绝
    let (id, code) = client.error_of(
        "schema.save",
        &root,
        json!({
            "schemaRevision": new_revision,
            "candidateHash": "deadbeef",
            "commands": commands,
            "cursor": "1",
        }),
    );
    assert!(id > 0);
    assert_eq!(code, "busy", "{code}");

    // 8) 校验 + 导出（进度事件 + 终态 + 记账 + 历史）
    //    YAML 保存不重建模板：先显式更新模板，再校验/导出
    client.payload_of("template.generate", &root, json!({"table": "Item"}));
    let validated = client.payload_of("validate", &root, json!({}));
    assert_eq!(validated["ok"], true, "{validated}");
    let export_id = client.next_id;
    let (terminal, events) = client.request("export", &root, json!({}));
    let export = match terminal {
        Message::Result(response) => response.payload,
        other => panic!("导出应成功: {other:?}"),
    };
    assert_eq!(export["outcome"], "succeeded", "{export}");
    assert!(
        events.iter().any(|e| matches!(e, Message::Progress(_))),
        "导出应发出进度事件"
    );
    assert!(root.join("output/json/Item_zh.json").exists());
    assert!(root.join("cache/state.json").exists(), "导出成功应记账");
    let history = client.payload_of("history.list", &root, json!({}));
    assert_eq!(history["entries"].as_array().unwrap().len(), 1, "{history}");

    // 9) 日志与任务查询、关闭通知
    let logs = client.payload_of("logs.list", &root, json!({"module": "export"}));
    assert!(!logs["entries"].as_array().unwrap().is_empty(), "{logs}");
    let tasks = client.payload_of("tasks.list", &root, json!({}));
    let export_task = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["method"] == "export")
        .expect("应能查到导出任务");
    assert_eq!(export_task["status"], "success", "{export_task}");
    let task_id = export_task["id"].as_str().unwrap().to_string();
    client.payload_of("tasks.dismiss", &root, json!({"taskId": task_id}));
    let tasks = client.payload_of("tasks.list", &root, json!({}));
    let dismissed = tasks["tasks"]
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["id"] == task_id)
        .unwrap();
    assert_eq!(dismissed["dismissed"], true, "{dismissed}");

    // 10) i18n：sync → 查询 → 保存单条 → 状态
    client.payload_of("i18n.sync", &root, json!({}));
    let rows = client.payload_of("i18n.status", &root, json!({}));
    assert_eq!(rows["langs"].as_array().unwrap().len(), 1, "{rows}");
    let query = client.payload_of(
        "i18n.query",
        &root,
        json!({"table": "Item", "lang": "en", "page": {}}),
    );
    assert!(query["entries"].is_array(), "{query}");
    // 保存单条译文：状态由内核按 source/text/confirmed 重算
    let saved_entry = client.payload_of(
        "i18n.save",
        &root,
        json!({"table": "Item", "lang": "en", "key": "1.Name", "text": "Sword", "confirmed": true}),
    );
    assert!(
        ["translated", "orphan", "stale"].contains(&saved_entry["status"].as_str().unwrap()),
        "{saved_entry}"
    );

    // 11) cancel 语义：未知请求 / 已终态
    let cancel_unknown = client.payload_of("cancel", &root, json!({"targetRequestId": 9999}));
    assert_eq!(cancel_unknown, json!("unknown_request"), "{cancel_unknown}");
    // 已完成写任务：already_terminal（不得被误报为可重放）
    let cancel_done = client.payload_of("cancel", &root, json!({"targetRequestId": export_id}));
    assert_eq!(cancel_done, json!("already_terminal"), "{cancel_done}");

    // 12) 独立部署（未配置目标 → 0 同步）
    let deployed = client.payload_of("deploy", &root, json!({}));
    assert_eq!(deployed["synced"], 0, "{deployed}");
    assert_eq!(deployed["unchanged"], true, "{deployed}");

    // 13) shutdown：终态后进程退出
    client.request("shutdown", &root, json!({}));
    client.close_stdin();
    let status = client.child.wait().unwrap();
    assert!(status.success(), "worker 应正常退出");
}

#[test]
fn protocol_violations_are_structured() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let mut client = Client::spawn();

    // 未知方法
    let (_, code) = client.error_of("no.such.method", &root, json!({}));
    assert_eq!(code, "unknown-method", "{code}");

    // 重复 requestId
    client.next_id = 500;
    client.send_raw(&json!({
        "type": "request", "requestId": 500, "method": "workspace.open",
        "workspaceRoot": root.to_string_lossy(), "params": {}
    }));
    let (first, _) = client.await_terminal(500);
    assert!(matches!(first, Message::Result(_)), "{first:?}");
    client.send_raw(&json!({
        "type": "request", "requestId": 500, "method": "workspace.open",
        "workspaceRoot": root.to_string_lossy(), "params": {}
    }));
    let (second, _) = client.await_terminal(500);
    match second {
        Message::Error(response) => {
            assert_eq!(response.error.code.to_string(), "duplicate-request-id")
        }
        other => panic!("重复 requestId 应被拒绝: {other:?}"),
    }

    // 非法 JSON：无 requestId 的连接级错误
    client.write_line(r#"{"type":"request""#);
    let garbage = client.read_message();
    match garbage {
        Message::Error(response) => {
            assert!(response.request_id.is_none(), "{response:?}");
            assert_eq!(response.error.code.to_string(), "malformed-message");
        }
        other => panic!("非法 JSON 应回连接级错误: {other:?}"),
    }
    // 连接仍然可用（避开手动使用的 500）
    client.next_id = 600;
    client.payload_of("workspace.open", &root, json!({}));
    client.request("shutdown", &root, json!({}));
    client.close_stdin();
    client.child.wait().unwrap();
}

#[test]
fn busy_when_workspace_locked() {
    let dir = setup();
    let root = dir.path().to_path_buf();
    let _hold = ct_storage::lock::WorkspaceLock::acquire(&root).unwrap();
    let mut client = Client::spawn();
    let (_, code) = client.error_of("export", &root, json!({}));
    assert_eq!(code, "busy", "{code}");
    client.request("shutdown", &root, json!({}));
    client.close_stdin();
    client.child.wait().unwrap();
}

/// 直接按内核规则计算当前 schemaRevision（与 worker 内部一致）。
fn schema_revision(root: &Path) -> String {
    let config = ct_domain::config::GlobalConfig::load(root).unwrap();
    let sources = ct_app::schema::capture_schema_sources(&config);
    sources.revision.revision
}
