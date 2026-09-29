//! 结构化错误码：不靠解析人类可读日志定位问题。

use serde::{Deserialize, Serialize};

/// 协议级错误码；业务错误码由 ct-app 诊断系统定义并经 DTO 透传。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ErrorCode {
    ProtocolMismatch,
    MalformedMessage,
    MessageTooLarge,
    UnknownMethod,
    DuplicateRequestId,
    StalePage,
    Busy,
    RecoveryNeeded,
    Internal,
}

impl ErrorCode {
    /// 稳定的 kebab-case 码名（与线格式一致）。
    pub fn as_str(self) -> &'static str {
        match self {
            ErrorCode::ProtocolMismatch => "protocol-mismatch",
            ErrorCode::MalformedMessage => "malformed-message",
            ErrorCode::MessageTooLarge => "message-too-large",
            ErrorCode::UnknownMethod => "unknown-method",
            ErrorCode::DuplicateRequestId => "duplicate-request-id",
            ErrorCode::StalePage => "stale-page",
            ErrorCode::Busy => "busy",
            ErrorCode::RecoveryNeeded => "recovery-needed",
            ErrorCode::Internal => "internal",
        }
    }
}

impl std::fmt::Display for ErrorCode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

/// 结构化错误载体。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorBody {
    pub code: ErrorCode,
    pub message: String,
    /// 业务失败定位明细（客户端据此跳转，不解析人类可读日志）。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub issues: Vec<crate::event::Issue>,
}
