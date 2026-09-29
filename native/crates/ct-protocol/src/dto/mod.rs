//! 业务方法 DTO：字段命名与 `docs/protocol/v1.md` 同源维护。
//!
//! 约定：结构体字段一律 camelCase（`rename_all = "camelCase"`），
//! 枚举值一律 snake_case；可选字段缺省即缺省键（不发 null）。

pub mod deploy;
pub mod excel;
pub mod export;
pub mod history;
pub mod i18n;
pub mod logs;
pub mod resources;
pub mod schema;
pub mod tasks;
pub mod workspace;
