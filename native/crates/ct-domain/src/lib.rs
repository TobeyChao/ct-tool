//! Schema 领域模型：类型系统、资源图、命令、候选与净差异。
//!
//! 纯领域层：不读文件系统、不解析 Excel、不格式化诊断文本。

pub mod candidate;
pub mod commands;
pub mod config;
pub mod diagnostics;
pub mod graph;
pub mod hashing;
pub mod indexes;
pub mod name_validation;
pub mod naming;
pub mod netdiff;
pub mod repository;
pub mod schema;
pub mod types;
