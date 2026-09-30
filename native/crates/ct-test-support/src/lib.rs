//! 测试支持：所有测试必须使用本 crate 构造的临时工作区，不得触碰真实 gd/。

pub mod excel_builder;
pub mod fixture_archive;
pub mod i18n_builder;
pub mod journal_builder;
pub mod protocol_client;
pub mod schema_builder;
pub mod temp_workspace;
pub mod workspace_builder;
pub mod xlsx_semantics;
