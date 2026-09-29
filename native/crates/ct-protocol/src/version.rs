//! 协议版本与能力协商。

/// 当前协议主版本。不兼容变更必须递增并更新 `docs/protocol/v1.md`。
pub const PROTOCOL_VERSION: u32 = 1;

/// hello 握手中声明的能力标记；缺失能力的入口由客户端显式禁用。
pub const CAPABILITIES: &[&str] = &[
    "workspace",
    "schema",
    "template",
    "validate",
    "export",
    "deploy",
    "i18n",
    "history",
    "logs",
    "tasks",
    "cancel",
    "shutdown",
];
