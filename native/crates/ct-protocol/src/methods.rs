//! 方法名常量：线格式唯一准绳，Dart 客户端按同名实现。

pub const WORKSPACE_OPEN: &str = "workspace.open";
pub const WORKSPACE_SNAPSHOT: &str = "workspace.snapshot";
pub const WORKSPACE_STATUS: &str = "workspace.status";
pub const WORKSPACE_RECOVER: &str = "workspace.recover";
pub const RESOURCES_LIST: &str = "resources.list";
pub const TABLE_PREVIEW: &str = "table.preview";
pub const SCHEMA_CANDIDATE: &str = "schema.candidate";
pub const SCHEMA_SAVE: &str = "schema.save";
pub const TEMPLATE_PLAN: &str = "template.plan";
pub const TEMPLATE_GENERATE: &str = "template.generate";
pub const VALIDATE: &str = "validate";
pub const EXPORT: &str = "export";
pub const DEPLOY: &str = "deploy";
pub const I18N_QUERY: &str = "i18n.query";
pub const I18N_SAVE: &str = "i18n.save";
pub const I18N_SYNC: &str = "i18n.sync";
pub const I18N_STATUS: &str = "i18n.status";
pub const I18N_COMPACT: &str = "i18n.compact";
pub const HISTORY_LIST: &str = "history.list";
pub const LOGS_LIST: &str = "logs.list";
pub const TASKS_LIST: &str = "tasks.list";
pub const TASKS_ISSUES: &str = "tasks.issues";
pub const TASKS_DISMISS: &str = "tasks.dismiss";
pub const CANCEL: &str = "cancel";
pub const SHUTDOWN: &str = "shutdown";

/// 协议 v1 全部方法。
pub const ALL: &[&str] = &[
    WORKSPACE_OPEN,
    WORKSPACE_SNAPSHOT,
    WORKSPACE_STATUS,
    WORKSPACE_RECOVER,
    RESOURCES_LIST,
    TABLE_PREVIEW,
    SCHEMA_CANDIDATE,
    SCHEMA_SAVE,
    TEMPLATE_PLAN,
    TEMPLATE_GENERATE,
    VALIDATE,
    EXPORT,
    DEPLOY,
    I18N_QUERY,
    I18N_SAVE,
    I18N_SYNC,
    I18N_STATUS,
    I18N_COMPACT,
    HISTORY_LIST,
    LOGS_LIST,
    TASKS_LIST,
    TASKS_ISSUES,
    TASKS_DISMISS,
    CANCEL,
    SHUTDOWN,
];
