/// 方法名常量：与 native/crates/ct-protocol/src/methods.rs 一致。
///
/// 同名测试会拿这里的集合与 docs/protocol/schema/protocol.v1.json 对照。
library;

abstract final class Methods {
  static const workspaceOpen = 'workspace.open';
  static const workspaceSnapshot = 'workspace.snapshot';
  static const workspaceStatus = 'workspace.status';
  static const workspaceRecover = 'workspace.recover';
  static const resourcesList = 'resources.list';
  static const tablePreview = 'table.preview';
  static const schemaCandidate = 'schema.candidate';
  static const schemaSave = 'schema.save';
  static const templatePlan = 'template.plan';
  static const templateGenerate = 'template.generate';
  static const validate = 'validate';
  static const export = 'export';
  static const deploy = 'deploy';
  static const i18nQuery = 'i18n.query';
  static const i18nSave = 'i18n.save';
  static const i18nSync = 'i18n.sync';
  static const i18nStatus = 'i18n.status';
  static const i18nCompact = 'i18n.compact';
  static const historyList = 'history.list';
  static const logsList = 'logs.list';
  static const tasksList = 'tasks.list';
  static const tasksIssues = 'tasks.issues';
  static const tasksDismiss = 'tasks.dismiss';
  static const cancel = 'cancel';
  static const shutdown = 'shutdown';

  /// 需要工作区锁、可能产生事件流的写方法；终态需要进入广播流。
  static const write = <String>{
    workspaceRecover,
    schemaSave,
    templateGenerate,
    export,
    deploy,
    i18nSave,
    i18nSync,
    i18nCompact,
    tasksDismiss,
  };

  static const all = <String>[
    workspaceOpen,
    workspaceSnapshot,
    workspaceStatus,
    workspaceRecover,
    resourcesList,
    tablePreview,
    schemaCandidate,
    schemaSave,
    templatePlan,
    templateGenerate,
    validate,
    export,
    deploy,
    i18nQuery,
    i18nSave,
    i18nSync,
    i18nStatus,
    i18nCompact,
    historyList,
    logsList,
    tasksList,
    tasksIssues,
    tasksDismiss,
    cancel,
    shutdown,
  ];
}
