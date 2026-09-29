//! 请求路由：method → `ct-app` 用例。读方法同步返回；写方法派发到工作线程，
//! 主循环继续读取控制消息（cancel/shutdown）。

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use ct_protocol::error::ErrorCode;
use ct_protocol::event::{Issue, IssueEvent};
use ct_protocol::message::Message;
use ct_protocol::request::Request;

use crate::event_queue::Outbound;
use crate::methods;
use crate::session::Session;
use crate::task::{CancelFlag, TaskRecord};

pub type Shared = Arc<Mutex<Session>>;

/// 业务/协议失败：结构化码 + 可选 Issue 明细。
pub struct Failure {
    pub code: ErrorCode,
    pub message: String,
    pub issues: Vec<Issue>,
}

impl Failure {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Failure {
            code,
            message: message.into(),
            issues: Vec::new(),
        }
    }

    pub fn with_issues(message: impl Into<String>, issues: Vec<Issue>) -> Self {
        Failure {
            code: ErrorCode::Internal,
            message: message.into(),
            issues,
        }
    }
}

pub type HandlerResult = Result<serde_json::Value, Failure>;

/// 写任务的事件出口（工作线程使用）。
#[derive(Clone)]
pub struct Emitter {
    shared: Shared,
    outbound: Outbound,
    request_id: u64,
}

impl Emitter {
    fn new(shared: Shared, outbound: Outbound, request_id: u64) -> Self {
        Emitter {
            shared,
            outbound,
            request_id,
        }
    }

    pub fn log(&self, module: &str, message: &str) {
        let seq = {
            let mut session = self.shared.lock().expect("会话中毒");
            session.push_log(module, "info", message, Some(self.request_id));
            session.next_seq_public()
        };
        let workspace_id = self.workspace_id();
        self.outbound
            .try_send_event(Message::Log(ct_protocol::event::LogEvent {
                request_id: self.request_id,
                workspace_id,
                seq,
                module: module.to_string(),
                level: "info".to_string(),
                message: message.to_string(),
            }));
    }

    pub fn progress(&self, stage: &str, done: u64, total: u64) {
        let seq = {
            let session = self.shared.lock().expect("会话中毒");
            let mut next = session.seq;
            next += 1;
            next
        };
        let workspace_id = self.workspace_id();
        self.outbound
            .send_progress(Message::Progress(ct_protocol::event::ProgressEvent {
                request_id: self.request_id,
                workspace_id,
                seq,
                stage: stage.to_string(),
                done,
                total,
            }));
    }

    fn workspace_id(&self) -> String {
        self.shared.lock().expect("会话中毒").workspace_id()
    }

    /// 结构化问题事件：终态之前逐条送达，队列满时阻塞（不可丢弃）。
    /// 同一批问题也随终态 `error.issues[]` 携带，客户端可二选一消费。
    pub fn emit_issues(&self, issues: &[Issue]) {
        let workspace_id = self.workspace_id();
        for issue in issues {
            let seq = self.shared.lock().expect("会话中毒").next_seq_public();
            self.outbound.send_issue(Message::Issue(IssueEvent {
                request_id: self.request_id,
                workspace_id: workspace_id.clone(),
                seq,
                issue: issue.clone(),
            }));
        }
    }
}

/// 分发一条已解析请求。
pub fn dispatch(shared: &Shared, outbound: &Outbound, request: Request) {
    let request_id = request.request_id;
    let method = request.method.clone();
    let root = PathBuf::from(&request.workspace_root);

    // 连接内 requestId 去重：写请求不会被执行两次
    {
        let mut session = shared.lock().expect("会话中毒");
        if session.shutting_down {
            let message = session.issue_error(
                Some(request_id),
                ErrorCode::Busy,
                "worker 正在关闭，不再接受新请求",
                Vec::new(),
            );
            outbound.send_terminal(message);
            return;
        }
        if !session.seen_request_ids.insert(request_id) {
            let message = session.issue_error(
                Some(request_id),
                ErrorCode::DuplicateRequestId,
                format!("requestId {request_id} 在本连接内已使用"),
                Vec::new(),
            );
            outbound.send_terminal(message);
            return;
        }
        if session.root.is_none() {
            session.bind(&root);
        }
    }

    if methods::is_write_method(&method) {
        spawn_write(shared.clone(), outbound.clone(), request);
        return;
    }

    let outcome = {
        let mut session = shared.lock().expect("会话中毒");
        let bound_root = session.root().unwrap_or_else(|| root.clone());
        session.sync_revision(&bound_root);
        methods::handle_read(&mut session, &bound_root, &method, &request.params)
    };
    respond(shared, outbound, request_id, outcome);
}

/// 写方法：登记任务 → 工作线程执行 → 终态由线程发出。
fn spawn_write(shared: Shared, outbound: Outbound, request: Request) {
    let request_id = request.request_id;
    let method = request.method.clone();
    let cancel = CancelFlag::new();
    {
        let mut session = shared.lock().expect("会话中毒");
        let id = format!("{method}#{request_id}");
        session
            .tasks
            .push(TaskRecord::new(id, request_id, &method, cancel.clone()));
        if session.tasks.len() > 200 {
            let cutoff = session.tasks.len() - 200;
            session.tasks.drain(..cutoff);
        }
    }
    let emitter = Emitter::new(shared.clone(), outbound.clone(), request_id);
    let root = shared
        .lock()
        .expect("会话中毒")
        .root()
        .unwrap_or_else(|| PathBuf::from(&request.workspace_root));
    std::thread::spawn(move || {
        let outcome =
            methods::run_write(&shared, &root, &method, &request.params, &cancel, &emitter);
        {
            let mut session = shared.lock().expect("会话中毒");
            if let Some(task) = session
                .tasks
                .iter_mut()
                .find(|t| t.request_id == request_id)
            {
                match &outcome {
                    Ok(value) if value["outcome"] == "cancelled" => {
                        task.status = ct_protocol::dto::tasks::TaskStatus::Cancelled
                    }
                    Ok(_) => task.status = ct_protocol::dto::tasks::TaskStatus::Success,
                    Err(failure) => {
                        task.status = ct_protocol::dto::tasks::TaskStatus::Error;
                        task.message = failure.message.clone();
                        task.issues = failure.issues.clone();
                    }
                }
            }
        }
        if outcome.is_ok() {
            shared.lock().expect("会话中毒").after_write(&root);
        }
        outbound.flush_progress();
        if let Err(failure) = &outcome {
            emitter.emit_issues(&failure.issues);
        }
        respond(&shared, &outbound, request_id, outcome);
    });
}

fn respond(shared: &Shared, outbound: &Outbound, request_id: u64, outcome: HandlerResult) {
    let message = {
        let mut session = shared.lock().expect("会话中毒");
        match outcome {
            Ok(payload) => session.issue_result(request_id, payload),
            Err(failure) => session.issue_error(
                Some(request_id),
                failure.code,
                failure.message,
                failure.issues,
            ),
        }
    };
    outbound.send_terminal(message);
}

/// 供 runtime 使用的路径规范化入口。
pub fn normalize_root(root: &Path) -> PathBuf {
    ct_app::schema::normalize_path(root)
}
