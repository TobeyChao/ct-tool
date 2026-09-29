//! stdio worker 协议 v1：NDJSON 消息、DTO、版本协商与错误码。
//!
//! 本 crate 只定义传输契约，不依赖业务实现；Dart 客户端与 Rust worker
//! 消费同源 schema 与 golden samples（见 `native/docs/protocol/`）。
//!
//! 语义权威文档：`native/docs/protocol/v1.md`。

pub mod bigint;
pub mod dto;
pub mod error;
pub mod event;
pub mod message;
pub mod methods;
pub mod pagination;
pub mod request;
pub mod response;
pub mod version;
