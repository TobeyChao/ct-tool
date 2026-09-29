//! 分页契约：令牌绑定快照 revision，输入变化返回 stale-page。

use serde::{Deserialize, Serialize};

/// 分页请求参数。
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PageRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cursor: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub limit: Option<u32>,
}

/// 分页响应：不混合两个 revision 的行数据。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Page<T> {
    pub items: Vec<T>,
    pub revision: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub next_cursor: Option<String>,
}
