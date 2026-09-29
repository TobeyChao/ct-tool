//! 缓存与账本分离：`artifacts`/`fingerprint` 可丢弃，`state` 只在成功后推进。

pub mod artifacts;
pub mod fingerprint;
pub mod state;
