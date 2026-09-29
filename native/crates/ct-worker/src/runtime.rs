//! worker 主循环：hello 协商 → 请求分发 → 安全 shutdown。
//!
//! 写任务在工作线程执行，主循环继续读取控制消息（cancel/shutdown）；
//! stdin EOF 视为隐式 shutdown：等待写任务到达发布安全边界后退出。

use std::io::Write;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};

use ct_protocol::message::{Hello, Message};
use ct_protocol::request::Request;
use ct_protocol::version::{CAPABILITIES, PROTOCOL_VERSION};

use crate::control;
use crate::dispatcher::{self, Shared};
use crate::event_queue::Outbound;
use crate::session::Session;
use crate::shutdown;

/// 以当前进程的 stdin/stdout 运行 worker。
pub fn run() -> anyhow::Result<()> {
    // Stdout 本身可跨线程移动（内部已同步），不能用 StdoutLock（非 Send）
    let writer = std::io::BufWriter::new(std::io::stdout());
    run_with_io(std::io::stdin(), writer)
}

/// 可测试的 worker 主循环（读写抽象）。
pub fn run_with_io<R: std::io::Read, W: Write + Send + 'static>(
    reader: R,
    writer: W,
) -> anyhow::Result<()> {
    let shared: Shared = Arc::new(Mutex::new(Session::default()));
    let mut reader = std::io::BufReader::new(reader);
    let (sender, receiver) = mpsc::sync_channel::<Message>(256);
    let outbound = Outbound::new(sender);
    let writer_thread = std::thread::spawn(move || {
        let mut writer = writer;
        for message in receiver.iter() {
            let mut line = match serde_json::to_string(&message) {
                Ok(text) => text,
                Err(_) => continue,
            };
            line.push('\n');
            if writer.write_all(line.as_bytes()).is_err() {
                break;
            }
            let _ = writer.flush();
        }
    });

    // 1) 握手：客户端 hello 必须先到
    let first = match read_line(&mut reader) {
        Ok(Some(line)) => line,
        Ok(None) => return Ok(()), // 立即断连
        Err(message) => {
            emit_connection_error(
                &outbound,
                ct_protocol::error::ErrorCode::MalformedMessage,
                message,
            );
            return Ok(());
        }
    };
    if !handshake(&shared, &outbound, &first) {
        // 协商失败：错误已发出，关闭连接
        shutdown::wait_for_quiescence(&shared);
        drop(outbound);
        let _ = writer_thread.join();
        return Ok(());
    }

    // 2) 请求循环
    loop {
        let line = match read_line(&mut reader) {
            Ok(Some(line)) => line,
            Ok(None) => break, // EOF：隐式 shutdown
            Err(message) => {
                let code = if message == "message-too-large" {
                    ct_protocol::error::ErrorCode::MessageTooLarge
                } else {
                    ct_protocol::error::ErrorCode::MalformedMessage
                };
                emit_connection_error(&outbound, code, message);
                continue;
            }
        };
        if line.trim().is_empty() {
            continue;
        }
        let parsed: Result<Message, serde_json::Error> = serde_json::from_str(&line);
        match parsed {
            Ok(Message::Request(mut request)) => {
                ct_protocol::bigint::decode_value(&mut request.params);
                handle_one(&shared, &outbound, request);
            }
            Ok(other) => {
                // 无法归属 requestId 的入站消息：连接级错误，不带信封字段（v1.md §4）
                let message = Session::connection_error(
                    ct_protocol::error::ErrorCode::MalformedMessage,
                    format!("握手后只接受 request 消息，收到 {}", kind_of(&other)),
                );
                outbound.send_terminal(message);
            }
            Err(error) => emit_connection_error(
                &outbound,
                ct_protocol::error::ErrorCode::MalformedMessage,
                error.to_string(),
            ),
        }
        // shutdown 只挡新请求（分发器回 busy）：继续读取入站消息直到客户端关闭输入，
        // 这样在途写任务的终态与控制响应都能送达，退出仍由 EOF + 安全边界驱动。
    }

    // 3) 关闭：等写任务到达发布安全边界（不强杀、不吞终态）
    shutdown::wait_for_quiescence(&shared);
    drop(outbound);
    let _ = writer_thread.join();
    Ok(())
}

fn kind_of(message: &Message) -> &'static str {
    match message {
        Message::Hello(_) => "hello",
        Message::Request(_) => "request",
        Message::Progress(_) => "progress",
        Message::Log(_) => "log",
        Message::Issue(_) => "issue",
        Message::Result(_) => "result",
        Message::Error(_) => "error",
    }
}

/// 读取一行；超过上限返回错误（整行丢弃，避免半条消息污染后续解析）。
fn read_line<R: std::io::BufRead>(reader: &mut R) -> Result<Option<String>, String> {
    let mut bytes = Vec::new();
    match reader.read_until(b'\n', &mut bytes) {
        Ok(0) => return Ok(None),
        Ok(_) => {}
        Err(_) => return Err("malformed-message".to_string()),
    }
    // 上限按消息体计（不含换行符）：恰好等于上限的消息必须可用
    let body_len = bytes.len() - usize::from(bytes.last() == Some(&b'\n'));
    if body_len > ct_protocol::message::MAX_MESSAGE_BYTES {
        return Err("message-too-large".to_string());
    }
    let line = String::from_utf8(bytes).map_err(|_| "malformed-message".to_string())?;
    if line.is_empty() {
        return Ok(None);
    }
    Ok(Some(line))
}

fn emit_connection_error(
    outbound: &Outbound,
    code: ct_protocol::error::ErrorCode,
    message: impl Into<String>,
) {
    let message = Session::connection_error(code, message);
    outbound.send_terminal(message);
}

/// 握手：校验协议版本与能力交集；不兼容发 protocol-mismatch 并关闭。
fn handshake(shared: &Shared, outbound: &Outbound, line: &str) -> bool {
    let parsed: Result<Hello, serde_json::Error> = match serde_json::from_str(line) {
        Ok(Message::Hello(hello)) => Ok(hello),
        Ok(other) => {
            emit_connection_error(
                outbound,
                ct_protocol::error::ErrorCode::MalformedMessage,
                format!("握手需要 hello，收到 {}", kind_of(&other)),
            );
            return false;
        }
        Err(error) => {
            emit_connection_error(
                outbound,
                ct_protocol::error::ErrorCode::MalformedMessage,
                error.to_string(),
            );
            return false;
        }
    };
    let client = match parsed {
        Ok(hello) => hello,
        Err(_) => return false,
    };
    if client.protocol_version != PROTOCOL_VERSION {
        emit_connection_error(
            outbound,
            ct_protocol::error::ErrorCode::ProtocolMismatch,
            format!(
                "客户端协议版本 {} 与 worker {} 无交集",
                client.protocol_version, PROTOCOL_VERSION
            ),
        );
        return false;
    }
    let mine = Hello {
        protocol_version: PROTOCOL_VERSION,
        core_version: env!("CARGO_PKG_VERSION").to_string(),
        capabilities: CAPABILITIES.iter().map(|s| s.to_string()).collect(),
    };
    outbound.send_terminal(Message::Hello(mine));
    let mut session = shared.lock().expect("会话中毒");
    session.push_log(
        "control",
        "info",
        &format!("握手完成：客户端 core {}", client.core_version),
        None,
    );
    true
}

/// 单条请求：控制方法就地处理，其余交给分发器。
fn handle_one(shared: &Shared, outbound: &Outbound, request: Request) {
    match request.method.as_str() {
        ct_protocol::methods::CANCEL => {
            let state = control::cancel(shared, &request.params);
            let payload = serde_json::to_value(state).unwrap_or(serde_json::Value::Null);
            let message = {
                let mut session = shared.lock().expect("会话中毒");
                session.issue_result(request.request_id, payload)
            };
            outbound.send_terminal(message);
        }
        ct_protocol::methods::SHUTDOWN => {
            control::begin_shutdown(shared);
            let message = {
                let mut session = shared.lock().expect("会话中毒");
                session.issue_result(
                    request.request_id,
                    serde_json::json!({"outcome": "shutdown"}),
                )
            };
            outbound.send_terminal(message);
        }
        _ => dispatcher::dispatch(shared, outbound, request),
    }
}
