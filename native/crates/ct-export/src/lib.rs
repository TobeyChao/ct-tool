//! 生成器与部署：所有影响产物字节的行为变更必须提升 [`CODEGEN_VERSION`]。

pub mod accessor;
pub mod accessor_csharp;
pub mod accessor_lua;
pub mod accessor_model;
pub mod binary;
pub mod bundle;
pub mod deploy;
pub mod fbs;
pub mod flat_builder;
pub mod i18n;
pub mod json;

/// 生成器版本，对应 Python `ct/app/exporting/build.py` 的 CODEGEN_VERSION。
/// 任何影响产物字节的行为变更必须提升它（与缓存键同源）。
pub const CODEGEN_VERSION: &str = "incremental/2-schema-layout";
