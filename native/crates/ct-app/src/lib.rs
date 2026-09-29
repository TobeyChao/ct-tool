//! 用例编排（对应 Python `ct/app/`）：组合领域模型与基础设施完成业务。
//!
//! CLI 与 worker 都必须通过这里的用例进入业务逻辑，禁止新增平行业务链路。

pub mod deploy;
pub mod export;
pub mod export_inputs;
pub mod history;
pub mod i18n;
pub mod memdiag;
pub mod panel;
pub mod schema;
pub mod snapshot;
pub mod status;
pub mod task;
pub mod template;
pub mod validate;
pub mod workspace;

pub mod panel_tasks;
