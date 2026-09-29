//! worker 协议契约夹具：在**进程内**驱动 worker（内存管道，不启动子进程、不依赖 Flutter）。
//!
//! 语义权威定义见 `native/docs/protocol/v1.md`；这里只负责把线格式消息送进
//! `ct_worker::run_with_io` 并取回消息，供任务 6.3/6.11 的契约测试复用。

use std::collections::VecDeque;
use std::io::{self, ErrorKind, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use ct_protocol::message::Message;
use ct_protocol::version::{CAPABILITIES, PROTOCOL_VERSION};
use serde_json::{json, Value};
use tempfile::TempDir;

/// 单次等待上限：契约测试全在内存管道上跑，超时即视为 worker 卡死。
pub const IDLE: Duration = Duration::from_secs(60);
/// 判定"没有更多消息"用的短等待。
pub const QUIET: Duration = Duration::from_millis(400);

// ---------------------------------------------------------------------------
// 单向字节管道
// ---------------------------------------------------------------------------

#[derive(Default)]
struct PipeState {
    bytes: Mutex<VecDeque<u8>>,
    changed: Condvar,
    writers: AtomicUsize,
    readers: AtomicUsize,
}

/// 新建一条单向管道。
pub fn pipe() -> (PipeWriter, PipeReader) {
    let state = Arc::new(PipeState {
        writers: AtomicUsize::new(1),
        readers: AtomicUsize::new(1),
        ..PipeState::default()
    });
    (
        PipeWriter {
            state: Arc::clone(&state),
        },
        PipeReader { state },
    )
}

/// 写端：读端全部释放后写入报错（模拟对端断开）。
pub struct PipeWriter {
    state: Arc<PipeState>,
}

/// 读端：写端全部释放后返回 EOF；也可随时释放以模拟断连。
pub struct PipeReader {
    state: Arc<PipeState>,
}

impl PipeReader {
    fn state(&self) -> Arc<PipeState> {
        Arc::clone(&self.state)
    }
}

impl Write for PipeWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        if self.state.readers.load(Ordering::SeqCst) == 0 {
            return Err(io::Error::new(ErrorKind::BrokenPipe, "读端已关闭"));
        }
        {
            let mut guard = self.state.bytes.lock().expect("管道中毒");
            guard.extend(buf);
        }
        self.state.changed.notify_all();
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl Drop for PipeWriter {
    fn drop(&mut self) {
        self.state.writers.fetch_sub(1, Ordering::SeqCst);
        self.state.changed.notify_all();
    }
}

impl Read for PipeReader {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let mut guard = self.state.bytes.lock().expect("管道中毒");
        while guard.is_empty() {
            if self.state.writers.load(Ordering::SeqCst) == 0 {
                return Ok(0); // EOF
            }
            guard = self.state.changed.wait(guard).expect("管道中毒");
        }
        let taken = buf.len().min(guard.len());
        for slot in buf.iter_mut().take(taken) {
            *slot = guard.pop_front().expect("管道内容竞争");
        }
        Ok(taken)
    }
}

impl Drop for PipeReader {
    fn drop(&mut self) {
        self.state.readers.fetch_sub(1, Ordering::SeqCst);
        self.state.changed.notify_all();
    }
}

// ---------------------------------------------------------------------------
// 协议客户端
// ---------------------------------------------------------------------------

/// 连接内协议客户端：NDJSON 行收发 + requestId 分配。
pub struct Wire {
    worker: Option<JoinHandle<anyhow::Result<()>>>,
    to_worker: Option<PipeWriter>,
    from_worker: Arc<PipeState>,
    reader_keepalive: Option<PipeReader>,
    spill: Vec<u8>,
    next_id: u64,
    root: Option<PathBuf>,
    /// 已收到的原始行（含无法解析的行），供诊断与"逐字节检查线格式"使用。
    pub received: Vec<String>,
}

impl Wire {
    /// 启动 worker（尚未握手）。
    pub fn start() -> Wire {
        let (stdin_writer, stdin_reader) = pipe();
        let (stdout_writer, stdout_reader) = pipe();
        let from_worker = stdout_reader.state();
        let worker = std::thread::spawn(move || {
            ct_worker::runtime::run_with_io(stdin_reader, stdout_writer)
        });
        Wire {
            worker: Some(worker),
            to_worker: Some(stdin_writer),
            from_worker,
            reader_keepalive: Some(stdout_reader),
            spill: Vec::new(),
            next_id: 1,
            root: None,
            received: Vec::new(),
        }
    }

    /// 启动并完成 v1 握手。
    pub fn connected() -> Wire {
        let mut wire = Wire::start();
        wire.hello(PROTOCOL_VERSION);
        match wire.message() {
            Message::Hello(ack) => {
                assert_eq!(ack.protocol_version, PROTOCOL_VERSION, "握手协议版本");
                assert!(!ack.capabilities.is_empty(), "worker 必须声明能力");
            }
            other => panic!("握手应返回 hello，实际 {other:?}"),
        }
        wire
    }

    /// 发送任意原始行（不含换行）。
    pub fn send_line(&mut self, raw: &str) {
        let writer = self.to_worker.as_mut().expect("输入端已关闭");
        writer
            .write_all(raw.as_bytes())
            .and_then(|_| writer.write_all(b"\n"))
            .and_then(|_| writer.flush())
            .expect("写入 worker stdin");
    }

    /// 发送原始字节（含非法 UTF-8 夹具）。
    pub fn send_bytes(&mut self, bytes: &[u8]) {
        let writer = self.to_worker.as_mut().expect("输入端已关闭");
        writer
            .write_all(bytes)
            .and_then(|_| writer.write_all(b"\n"))
            .and_then(|_| writer.flush())
            .expect("写入 worker stdin");
    }

    /// 尝试写入一行：连接已被对端关闭时返回 false（不断言 panic）。
    pub fn try_send_line(&mut self, raw: &str) -> bool {
        let Some(writer) = self.to_worker.as_mut() else {
            return false;
        };
        writer
            .write_all(raw.as_bytes())
            .and_then(|_| writer.write_all(b"\n"))
            .is_ok()
    }

    /// 发送一条 JSON 消息。
    pub fn send(&mut self, value: &Value) {
        let text = value.to_string();
        self.send_line(&text);
    }

    /// 发送 hello（可指定版本以触发协商失败）。
    pub fn hello(&mut self, protocol_version: u32) {
        self.send(&json!({
            "type": "hello",
            "protocolVersion": protocol_version,
            "coreVersion": "contract-fixture",
            "capabilities": CAPABILITIES,
        }));
    }

    /// 分配下一个 requestId。
    pub fn take_id(&mut self) -> u64 {
        let id = self.next_id;
        self.next_id += 1;
        id
    }

    /// 发送请求（自动分配 id），返回该 id。
    pub fn call(&mut self, method: &str, params: Value) -> u64 {
        let id = self.take_id();
        self.request(id, method, params);
        id
    }

    /// 用指定 id 发送请求。
    pub fn request(&mut self, id: u64, method: &str, params: Value) {
        let root = self
            .root
            .as_ref()
            .map(|root| root.to_string_lossy().to_string())
            .unwrap_or_default();
        self.send(&json!({
            "type": "request",
            "requestId": id,
            "method": method,
            "workspaceRoot": root,
            "params": params,
        }));
    }

    /// 读取一条原始行；超时或写端已关闭返回 None。
    pub fn line_within(&mut self, timeout: Duration) -> Option<String> {
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(position) = self.spill.iter().position(|byte| *byte == b'\n') {
                let line: Vec<u8> = self.spill.drain(..=position).collect();
                let text = String::from_utf8_lossy(&line[..position]).into_owned();
                self.received.push(text.clone());
                return Some(text);
            }
            let remaining = deadline.checked_duration_since(Instant::now())?;
            let mut guard = self.from_worker.bytes.lock().expect("管道中毒");
            if guard.is_empty() {
                if self.from_worker.writers.load(Ordering::SeqCst) == 0 {
                    return None; // worker 已退出
                }
                let (next, waited) = self
                    .from_worker
                    .changed
                    .wait_timeout(guard, remaining)
                    .expect("管道中毒");
                guard = next;
                if waited.timed_out() && guard.is_empty() {
                    continue;
                }
            }
            self.spill.extend(guard.drain(..));
        }
    }

    /// 读取一条原始行（默认超时，超时即 panic）。
    pub fn line(&mut self) -> String {
        let timeout = IDLE;
        self.line_within(timeout).unwrap_or_else(|| {
            panic!(
                "等待 worker 消息超时（缓冲 {} 字节）；已收到 {} 条：{:?}",
                self.spill.len(),
                self.received.len(),
                self.received
            )
        })
    }

    /// 读取一条可解析消息。
    pub fn message(&mut self) -> Message {
        let raw = self.line();
        match serde_json::from_str::<Message>(&raw) {
            Ok(message) => message,
            Err(error) => panic!("收到非法协议消息: {error} / {raw}"),
        }
    }

    /// 读取直到某个 requestId 的终态，返回终态与之前的全部事件。
    pub fn until_terminal(&mut self, id: u64) -> (Message, Vec<Message>) {
        let mut events = Vec::new();
        loop {
            let message = self.message();
            let matched = match &message {
                Message::Result(response) => response.request_id == id,
                Message::Error(response) => response.request_id == Some(id),
                _ => false,
            };
            if matched {
                return (message, events);
            }
            events.push(message);
        }
    }

    /// 断言某请求已终结后不再有第二个终态。
    pub fn assert_no_second_terminal(&mut self, id: u64) {
        while let Some(raw) = self.line_within(QUIET) {
            let Ok(message) = serde_json::from_str::<Message>(&raw) else {
                continue;
            };
            let second = match &message {
                Message::Result(response) => response.request_id == id,
                Message::Error(response) => response.request_id == Some(id),
                _ => false,
            };
            assert!(!second, "请求 #{id} 出现第二个终态：{message:?}");
        }
    }

    /// 请求并断言成功，返回 payload。
    pub fn payload(&mut self, method: &str, params: Value) -> Value {
        let id = self.take_id();
        self.request(id, method, params);
        let (terminal, _) = self.until_terminal(id);
        match terminal {
            Message::Result(response) => response.payload,
            other => panic!("{method} 应成功，实际 {other:?}"),
        }
    }

    /// 请求并断言失败，返回错误码。
    pub fn error_code(&mut self, method: &str, params: Value) -> String {
        let id = self.take_id();
        self.request(id, method, params);
        let (terminal, _) = self.until_terminal(id);
        match terminal {
            Message::Error(response) => response.error.code.to_string(),
            other => panic!("{method} 应失败，实际 {other:?}"),
        }
    }

    /// 绑定工作区根（后续请求都携带它）。
    pub fn bind_root(&mut self, root: &Path) {
        self.root = Some(root.to_path_buf());
    }

    /// 打开工作区并返回快照。
    pub fn open(&mut self, root: &Path) -> Value {
        self.bind_root(root);
        self.payload("workspace.open", json!({}))
    }

    /// 模拟客户端断连（worker 视为隐式 shutdown）。
    pub fn close_input(&mut self) {
        self.to_worker = None;
    }

    /// 关闭输出读端：worker 后续写出失败（无终态可送达）。
    pub fn close_output(&mut self) {
        self.reader_keepalive = None;
    }

    /// 等待 worker 主循环退出。
    pub fn wait_exit(&mut self) -> anyhow::Result<()> {
        let handle = self
            .worker
            .take()
            .expect("worker 句柄已回收（只能等待一次）");
        match handle.join() {
            Ok(inner) => inner,
            Err(_) => anyhow::bail!("worker 线程 panic"),
        }
    }

    /// 显式 shutdown 并确认干净退出。
    pub fn shutdown(mut self) {
        let id = self.take_id();
        self.request(id, "shutdown", json!({}));
        let (terminal, _) = self.until_terminal(id);
        assert!(
            matches!(terminal, Message::Result(_)),
            "shutdown 应返回 result，实际 {terminal:?}"
        );
        self.close_input();
        self.wait_exit().expect("worker 应正常退出");
    }
}

impl Drop for Wire {
    fn drop(&mut self) {
        self.to_worker = None;
        if let Some(handle) = self.worker.take() {
            let _ = handle.join();
        }
    }
}

// ---------------------------------------------------------------------------
// 工作区夹具
// ---------------------------------------------------------------------------

/// 最小可导出工作区：一张 Item 表（无数据行，模板由 worker 生成）。
pub fn minimal_workspace() -> TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    write(
        &dir.path().join("config/global.yaml"),
        "primary_lang: zh\nsecondary_langs:\n  - en\n",
    );
    write(
        &dir.path().join("config/schemas/item.yaml"),
        "table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\n  - name: Name\n    type: string\n    i18n: true\nindexes:\n  - kind: codename\n",
    );
    dir
}

/// 富工作区：与 Python golden 同源的多行表 + 枚举 + 译文。
pub fn rich_workspace() -> TempDir {
    let dir = tempfile::tempdir().expect("临时目录");
    copy_dir(&fixture_dir().join("workspace"), dir.path());
    dir
}

/// 导出流水线夹具目录（`native/fixtures/export_pipeline`）。
pub fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/export_pipeline")
}

/// 写文件（统一 LF，与 Python 夹具一致）。
pub fn write(path: &Path, content: &str) {
    std::fs::create_dir_all(path.parent().expect("父目录")).expect("创建目录");
    let normalized = content.replace("\r\n", "\n");
    std::fs::write(path, normalized).expect("写入文件");
}

fn copy_dir(src: &Path, dst: &Path) {
    std::fs::create_dir_all(dst).expect("创建目录");
    for entry in std::fs::read_dir(src).expect("读取夹具目录").flatten() {
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), &target).expect("复制夹具文件");
        }
    }
}

/// 按内核规则计算当前 schemaRevision（schema 源文件集合的 sha256）。
pub fn schema_revision(root: &Path) -> String {
    let config = ct_domain::config::GlobalConfig::load(root).expect("全局配置");
    ct_app::schema::capture_schema_sources(&config)
        .revision
        .revision
}
