//! 有界事件队列：progress 可合并、log 可限流，issue 与终态不可丢弃。

use std::collections::HashMap;
use std::sync::mpsc::SyncSender;
use std::sync::{Arc, Mutex};

use ct_protocol::message::Message;

/// 出站消息通道（写线程消费）；可克隆并跨线程共享。
#[derive(Clone)]
pub struct Outbound {
    inner: Arc<Mutex<SyncSender<Message>>>,
    pending_progress: Arc<Mutex<HashMap<u64, Message>>>,
}

impl Outbound {
    pub fn new(sender: SyncSender<Message>) -> Self {
        Outbound {
            inner: Arc::new(Mutex::new(sender)),
            pending_progress: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn send_with(&self, message: Message, blocking: bool) {
        let guard = self.inner.lock().expect("出站通道中毒");
        if blocking {
            let _ = guard.send(message);
        } else {
            let _ = guard.try_send(message);
        }
    }

    /// 非终态事件：队列满时丢弃可再生事件（progress/log），不阻塞业务线程。
    pub fn try_send_event(&self, message: Message) {
        self.send_with(message, false);
    }

    /// 进度事件：同一请求只保留最新一条（合并），由 flush 送出。
    pub fn send_progress(&self, message: Message) {
        if let Some(request_id) = message_request_id(&message) {
            let mut pending = self.pending_progress.lock().expect("事件队列中毒");
            pending.insert(request_id, message);
        } else {
            self.try_send_event(message);
        }
    }

    /// 结构化问题事件：与终态同级，不可丢弃（队列满时阻塞）。
    pub fn send_issue(&self, message: Message) {
        self.send_with(message, true);
    }

    /// 终态：必须送达（阻塞发送；通道关闭时放弃，客户端按断连语义处理）。
    pub fn send_terminal(&self, message: Message) {
        if let Some(request_id) = message_request_id(&message) {
            let mut pending = self.pending_progress.lock().expect("事件队列中毒");
            pending.remove(&request_id);
        }
        self.send_with(message, true);
    }

    /// 刷新合并中的进度事件（阶段边界与终态前调用）。
    pub fn flush_progress(&self) {
        let drained: Vec<Message> = {
            let mut pending = self.pending_progress.lock().expect("事件队列中毒");
            pending.drain().map(|(_, message)| message).collect()
        };
        for message in drained {
            self.try_send_event(message);
        }
    }
}

fn message_request_id(message: &Message) -> Option<u64> {
    match message {
        Message::Progress(event) => Some(event.request_id),
        Message::Log(event) => Some(event.request_id),
        Message::Issue(event) => Some(event.request_id),
        Message::Result(response) => Some(response.request_id),
        Message::Error(response) => response.request_id,
        Message::Hello(_) | Message::Request(_) => None,
    }
}
