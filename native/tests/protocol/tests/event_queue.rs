//! 有界事件队列（任务 6.3）：progress 可合并、log 可限流、issue 与终态不可丢弃。

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::time::{Duration, Instant};

use ct_protocol::error::{ErrorBody, ErrorCode};
use ct_protocol::event::{Issue, IssueEvent, LogEvent, ProgressEvent};
use ct_protocol::message::Message;
use ct_protocol::response::{ErrorResponse, ResultResponse};
use ct_worker::event_queue::Outbound;
use serde_json::json;

fn log_event(text: &str) -> Message {
    Message::Log(LogEvent {
        request_id: 1,
        workspace_id: "ws".to_string(),
        seq: 0,
        module: "test".to_string(),
        level: "info".to_string(),
        message: text.to_string(),
    })
}

fn progress_event(stage: &str, done: u64) -> Message {
    Message::Progress(ProgressEvent {
        request_id: 1,
        workspace_id: "ws".to_string(),
        seq: 0,
        stage: stage.to_string(),
        done,
        total: 10,
    })
}

fn issue_event(code: &str) -> Message {
    Message::Issue(IssueEvent {
        request_id: 1,
        workspace_id: "ws".to_string(),
        seq: 0,
        issue: Issue {
            code: code.to_string(),
            message: "夹具问题".to_string(),
            resource: Some("Item".to_string()),
            field_path: Some("Id".to_string()),
            excel_row: Some(7),
            file: None,
        },
    })
}

fn terminal(request_id: u64) -> Message {
    Message::Result(ResultResponse {
        request_id,
        workspace_id: "ws".to_string(),
        seq: 1,
        payload: json!({"outcome": "succeeded"}),
    })
}

fn connection_error() -> Message {
    Message::Error(ErrorResponse {
        request_id: None,
        workspace_id: None,
        seq: None,
        error: ErrorBody {
            code: ErrorCode::Internal,
            message: "连接级错误".to_string(),
            issues: Vec::new(),
        },
    })
}

fn types(messages: Vec<Message>) -> Vec<&'static str> {
    messages
        .iter()
        .map(|message| match message {
            Message::Progress(_) => "progress",
            Message::Log(_) => "log",
            Message::Issue(_) => "issue",
            Message::Result(_) => "result",
            Message::Error(_) => "error",
            Message::Hello(_) => "hello",
            Message::Request(_) => "request",
        })
        .collect()
}

#[test]
fn logs_are_dropped_when_the_queue_is_full() {
    let (sender, receiver) = mpsc::sync_channel::<Message>(2);
    let outbound = Outbound::new(sender);
    for index in 0..10 {
        outbound.try_send_event(log_event(&index.to_string()));
    }
    let drained: Vec<Message> = receiver.iter().take(2).collect();
    assert_eq!(drained.len(), 2, "有界队列只接收 2 条可丢弃事件");
    assert_eq!(types(drained), ["log", "log"]);
}

#[test]
fn progress_merges_to_the_latest_per_request() {
    let (sender, receiver) = mpsc::sync_channel::<Message>(8);
    let outbound = Outbound::new(sender);
    for done in 1..=5 {
        outbound.send_progress(progress_event("JSON", done));
    }
    assert!(
        matches!(receiver.try_recv(), Err(mpsc::TryRecvError::Empty)),
        "进度必须先合并、不即时下发"
    );
    outbound.flush_progress();
    let flushed: Vec<Message> = receiver.try_iter().collect();
    assert_eq!(flushed.len(), 1, "同一请求只保留最新一条进度");
    match &flushed[0] {
        Message::Progress(event) => {
            assert_eq!(event.done, 5, "必须保留最新进度");
            assert_eq!(event.stage, "JSON");
        }
        other => panic!("应为 progress，实际 {other:?}"),
    }
}

#[test]
fn terminal_drops_unflushed_progress() {
    let (sender, receiver) = mpsc::sync_channel::<Message>(8);
    let outbound = Outbound::new(sender);
    outbound.send_progress(progress_event("JSON", 3));
    outbound.send_terminal(terminal(1));
    let left: Vec<Message> = receiver.try_iter().collect();
    assert_eq!(types(left), ["result"], "终态前未 flush 的合并进度不得迟到");
}

#[test]
fn issue_events_block_instead_of_being_dropped() {
    let (sender, receiver) = mpsc::sync_channel::<Message>(1);
    let outbound = Outbound::new(sender);
    outbound.try_send_event(log_event("占满队列"));
    let sender_thread = {
        let clone = outbound.clone();
        std::thread::spawn(move || {
            clone.send_issue(issue_event("duplicate-primary-key"));
            clone.send_issue(issue_event("type-mismatch"));
        })
    };
    let first = receiver
        .recv_timeout(Duration::from_secs(10))
        .expect("日志");
    assert_eq!(types(vec![first]), ["log"]);
    for code in ["duplicate-primary-key", "type-mismatch"] {
        let message = receiver
            .recv_timeout(Duration::from_secs(10))
            .expect("issue 不得被丢弃");
        match message {
            Message::Issue(event) => assert_eq!(event.issue.code, code),
            other => panic!("应为 issue，实际 {other:?}"),
        }
    }
    sender_thread.join().expect("发送线程不得 panic");
}

#[test]
fn terminal_waits_for_queue_space_and_arrives_last() {
    let (sender, receiver) = mpsc::sync_channel::<Message>(1);
    let outbound = Outbound::new(sender);
    outbound.try_send_event(log_event("占满队列"));
    outbound.send_progress(progress_event("JSON", 1));
    outbound.flush_progress(); // 队列满：可再生事件被丢弃
    let done = Arc::new(AtomicBool::new(false));
    {
        let clone = outbound.clone();
        let flag = Arc::clone(&done);
        std::thread::spawn(move || {
            clone.send_terminal(terminal(7));
            flag.store(true, Ordering::SeqCst);
        });
    }
    std::thread::sleep(Duration::from_millis(150));
    assert!(!done.load(Ordering::SeqCst), "队列未腾空时终态必须阻塞等待");
    assert_eq!(
        types(vec![receiver
            .recv_timeout(Duration::from_secs(10))
            .expect("日志")]),
        ["log"]
    );
    assert_eq!(
        types(vec![receiver
            .recv_timeout(Duration::from_secs(10))
            .expect("终态必须送达")]),
        ["result"]
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while !done.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(done.load(Ordering::SeqCst), "终态发送线程必须完成");
}
#[test]
fn messages_are_still_delivered_after_the_reader_disappears() {
    // 断连：终态/issue 发送失败但不得 panic，也不得阻塞关闭路径
    let (sender, receiver) = mpsc::sync_channel::<Message>(1);
    drop(receiver);
    let outbound = Outbound::new(sender);
    outbound.send_terminal(connection_error());
    outbound.send_issue(issue_event("any"));
    outbound.try_send_event(log_event("any"));
    outbound.flush_progress();
}
