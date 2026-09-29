//! NDJSON 消息信封：stdin/stdout 每行一条完整消息。

use serde::{Deserialize, Serialize};

use crate::event::{IssueEvent, LogEvent, ProgressEvent};
use crate::request::Request;
use crate::response::{ErrorResponse, ResultResponse};

/// 单条消息字节上限（默认 4 MiB），超限返回 `message-too-large`。
pub const MAX_MESSAGE_BYTES: usize = 4 * 1024 * 1024;

/// 线格式消息：以 `type` 字段区分。
///
/// `cancel`/`shutdown` 是普通方法（走 [`Request`]），不是独立消息类型。
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Message {
    Hello(Hello),
    Request(Request),
    Progress(ProgressEvent),
    Log(LogEvent),
    Issue(IssueEvent),
    Result(ResultResponse),
    Error(ErrorResponse),
}

/// 握手消息：连接建立后双向各发一条，先客户端后 worker。
///
/// 无法协商共同 `protocol_version` 时 worker 回 `protocol-mismatch`
/// 错误并关闭连接，业务请求不得执行。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Hello {
    pub protocol_version: u32,
    pub core_version: String,
    pub capabilities: Vec<String>,
}
