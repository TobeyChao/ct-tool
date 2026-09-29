//! 连接会话状态：workspaceId 绑定、seq、快照代次、请求 ID 去重、分页令牌。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use ct_protocol::error::{ErrorBody, ErrorCode};
use ct_protocol::event::Issue;
use ct_protocol::message::Message;
use ct_protocol::response::{ErrorResponse, ResultResponse};

use crate::task::TaskRecord;

/// 连接内会话状态（工作线程与主循环共享）。
#[derive(Default)]
pub struct Session {
    pub workspace_id: Option<String>,
    pub root: Option<PathBuf>,
    /// 快照代次：工作区内容变化（内部写入或外部修改）后递增，分页令牌绑定它。
    pub snapshot_revision: u64,
    /// 输入签名：config/excel/i18n 的相对路径+大小+mtime 摘要，用于发现外部修改。
    pub input_signature: String,
    pub seq: u64,
    pub seen_request_ids: HashSet<u64>,
    pub tasks: Vec<TaskRecord>,
    /// 连接内日志环形缓冲（logs.list 查询源）。
    pub logs: Vec<ct_protocol::dto::logs::LogEntry>,
    pub dismissed: HashSet<String>,
    /// 不透明分页令牌 → 生成时的快照代次。
    pub page_tokens: HashMap<String, u64>,
    pub shutting_down: bool,
}

impl Session {
    /// 规范化 workspaceId：绝对路径 + 大小写折叠（Windows/macOS 语义）。
    /// 重复打开同一工作区不推进代次（不得无谓作废既有分页令牌）。
    pub fn bind(&mut self, root: &Path) -> String {
        let absolute = if root.is_absolute() {
            root.to_path_buf()
        } else {
            std::env::current_dir().unwrap_or_default().join(root)
        };
        let root = ct_app::schema::normalize_path(&absolute);
        let text = root.to_string_lossy().replace('\\', "/");
        let id = ct_domain::hashing::sha256_hex(text.as_bytes())[..16].to_string();
        self.workspace_id = Some(id.clone());
        if self.root.as_deref() != Some(root.as_path()) {
            self.root = Some(root.clone());
            self.invalidate_pages();
        }
        self.input_signature = input_signature(&root);
        id
    }

    /// 用输入签名同步代次：外部改动使既有分页令牌失效（v1.md §9）。
    pub fn sync_revision(&mut self, root: &Path) {
        let signature = input_signature(root);
        if self.input_signature.is_empty() {
            self.input_signature = signature;
            return;
        }
        if signature != self.input_signature {
            self.input_signature = signature;
            self.invalidate_pages();
        }
    }

    /// 写成功后的收敛：输入未变且无未消费令牌时不无谓推进代次。
    pub fn after_write(&mut self, root: &Path) {
        let signature = input_signature(root);
        let changed = signature != self.input_signature;
        self.input_signature = signature;
        if changed || !self.page_tokens.is_empty() {
            self.invalidate_pages();
        }
    }

    pub fn workspace_id(&self) -> String {
        self.workspace_id.clone().unwrap_or_default()
    }

    pub fn root(&self) -> Option<PathBuf> {
        self.root.clone()
    }

    /// 事件序号分配（工作线程发事件时使用）。
    pub fn next_seq_public(&mut self) -> u64 {
        self.next_seq()
    }

    fn next_seq(&mut self) -> u64 {
        self.seq += 1;
        self.seq
    }

    /// 会话日志（同时供 logs.list 查询）。
    pub fn push_log(&mut self, module: &str, level: &str, message: &str, request_id: Option<u64>) {
        self.logs.push(ct_protocol::dto::logs::LogEntry {
            ts: ct_protocol::dto::logs::now_rfc3339(),
            module: module.to_string(),
            level: level.to_string(),
            message: message.to_string(),
            request_id,
        });
        const LOG_CAP: usize = 2000;
        if self.logs.len() > LOG_CAP {
            let excess = self.logs.len() - LOG_CAP;
            self.logs.drain(..excess);
        }
    }

    /// 快照内容变化：推进代次并使既有分页令牌失效。
    pub fn invalidate_pages(&mut self) {
        self.snapshot_revision += 1;
        self.page_tokens.clear();
    }

    /// 终态 result：payload 出站前递归应用大整数规则（v1.md §10）。
    pub fn issue_result(&mut self, request_id: u64, payload: serde_json::Value) -> Message {
        let mut payload = payload;
        ct_protocol::bigint::encode_value(&mut payload);
        let seq = self.next_seq();
        let workspace_id = self.workspace_id();
        Message::Result(ResultResponse {
            request_id,
            workspace_id,
            seq,
            payload,
        })
    }

    pub fn issue_error(
        &mut self,
        request_id: Option<u64>,
        code: ErrorCode,
        message: impl Into<String>,
        issues: Vec<Issue>,
    ) -> Message {
        let seq = self.next_seq();
        let workspace_id = self.workspace_id();
        Message::Error(ErrorResponse {
            request_id,
            workspace_id: Some(workspace_id),
            seq: Some(seq),
            error: ErrorBody {
                code,
                message: message.into(),
                issues,
            },
        })
    }

    /// 连接级错误（无法归属 requestId 时不带信封字段）。
    pub fn connection_error(code: ErrorCode, message: impl Into<String>) -> Message {
        Message::Error(ErrorResponse {
            request_id: None,
            workspace_id: None,
            seq: None,
            error: ErrorBody {
                code,
                message: message.into(),
                issues: Vec::new(),
            },
        })
    }

    /// 分配分页令牌（绑定当前快照代次）。
    pub fn page_token(&mut self, offset: usize) -> String {
        let token = format!("{}.{}", self.snapshot_revision, offset);
        self.page_tokens
            .insert(token.clone(), self.snapshot_revision);
        token
    }

    /// 解析令牌；代次不匹配返回 stale-page。
    pub fn resolve_page(&mut self, token: Option<&str>) -> Result<usize, ErrorCode> {
        let Some(token) = token else {
            return Ok(0);
        };
        match self.page_tokens.get(token) {
            Some(revision) if *revision == self.snapshot_revision => token
                .rsplit('.')
                .next()
                .and_then(|v| v.parse::<usize>().ok())
                .ok_or(ErrorCode::StalePage),
            Some(_) => Err(ErrorCode::StalePage),
            None => Err(ErrorCode::StalePage),
        }
    }
}

/// 输入签名：config/excel/i18n 下所有文件的「相对路径:大小:mtime」。
/// 只做目录遍历，不读文件内容；用于发现工作区被外部修改。
fn input_signature(root: &Path) -> String {
    let mut entries: Vec<String> = Vec::new();
    for dir in ["config", "excel", "i18n"] {
        collect_signature(&root.join(dir), root, &mut entries);
    }
    entries.sort();
    ct_domain::hashing::sha256_hex(entries.join("\n").as_bytes())[..16].to_string()
}

fn collect_signature(dir: &Path, base: &Path, out: &mut Vec<String>) {
    let Ok(read_dir) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in read_dir.flatten() {
        let Ok(meta) = entry.metadata() else {
            continue;
        };
        let path = entry.path();
        if meta.is_dir() {
            collect_signature(&path, base, out);
            continue;
        }
        let relative = match path.strip_prefix(base) {
            Ok(rest) => rest.to_path_buf(),
            Err(_) => path.clone(),
        };
        let name = relative.to_string_lossy().replace('\\', "/");
        let modified = match meta.modified() {
            Ok(at) => at
                .duration_since(SystemTime::UNIX_EPOCH)
                .map(|span| format!("{}", span.as_nanos()))
                .unwrap_or_else(|_| "unknown".to_string()),
            Err(_) => "unknown".to_string(),
        };
        out.push(format!("{name}:{}:{modified}", meta.len()));
    }
}
