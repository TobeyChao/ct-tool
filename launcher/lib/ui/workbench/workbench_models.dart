/// 工作台的数据契约（native-flutter-workbench 任务 2.3）。
///
/// 界面样板（`mock/mock_data.dart`）与真实内核来源（`services/workbench_repository.dart`）
/// 各自实现 [WorkbenchData]，工作台壳只认这个契约：切换工作区、总览、资源列表与只读预览
/// 都可以换数据来源，不改壳层。
library;

/// 资源类别（与内核 `resources.list` 的 kind 对应）。
enum WorkbenchResourceKind { table, record, enumType }

extension WorkbenchResourceKindLabel on WorkbenchResourceKind {
  String get label => switch (this) {
    WorkbenchResourceKind.table => '表',
    WorkbenchResourceKind.record => '记录',
    WorkbenchResourceKind.enumType => '枚举',
  };
}

/// 字段行（属性区/编辑器的最小模型）。
class WorkbenchField {
  const WorkbenchField({
    required this.name,
    required this.type,
    this.role = '',
    this.constraints = '',
    this.defaultValue = '',
    this.description = '',
    this.localized = false,
    this.serverOnly = false,
    this.excelColumns,
  });

  final String name;
  final String type;
  final String role;
  final String constraints;
  final String defaultValue;
  final String description;

  /// 本地化标记（内核 i18n）。
  final bool localized;

  /// 仅服务端字段（内核 server_only）。
  final bool serverOnly;

  /// vector 展开组数（内核 excel_columns，仅声明时有值）。
  final int? excelColumns;
}

/// 一个可编辑/可查看的资源条目；表类资源可携带只读预览。
class WorkbenchResource {
  const WorkbenchResource({
    required this.name,
    required this.kind,
    required this.path,
    this.fields = const [],
    this.previewColumns = const [],
    this.previewRows = const [],
    this.dirty = false,
    this.indexes = const [],
    this.previewHasMore = false,
  });

  final String name;
  final WorkbenchResourceKind kind;
  final String path;
  final List<WorkbenchField> fields;
  final List<String> previewColumns;
  final List<List<String>> previewRows;
  final bool dirty;

  /// 已声明的查询索引 kind（取自内核 resources.list，界面不自己发明）。
  final List<String> indexes;

  /// 内核预览是否还有下一页（`nextCursor` 非空）；mock 数据恒为 false。
  final bool previewHasMore;
}

/// 任务区条目。
enum WorkbenchTaskStatus { running, success, failed, queued }

class WorkbenchTask {
  const WorkbenchTask({
    required this.id,
    required this.title,
    required this.status,
    this.progress,
    required this.detail,
    required this.duration,
  });

  final int id;
  final String title;
  final WorkbenchTaskStatus status;
  final double? progress;
  final String detail;
  final String duration;
}

/// 工作台只读视图的数据来源。
abstract class WorkbenchData {
  const WorkbenchData();

  String get workspaceName;
  String get workspacePath;

  /// 内核快照代次（`workspace.open.revision`）。
  int get schemaRevision;
  List<WorkbenchResource> get resources;
  List<WorkbenchTask> get tasks;
  int get draftCount;

  /// 有写任务在跑：界面须禁用重复提交。
  bool get busy;

  /// 候选代次已过期：保存前必须重算候选。
  bool get candidateExpired;

  /// 加载失败原因（null 表示正常）。
  String? get loadError;

  /// 数据是否为界面样板：真实内核来源必须返回 false，界面据此显示不同提示。
  bool get sampleData => true;

  /// 内核报告上次退出留下未完成的发布事务（任务 4.7 的恢复入口）。
  bool get recoveryNeeded => false;

  /// 待恢复的发布日志名，由内核给出。
  List<String> get recoveryJournals => const [];

  /// 草稿是否已原子落盘到用户目录（任务 3.5）；失败时界面要持续警告。
  bool get draftPersisted => true;

  String? get persistError => null;

  /// 用户目录里留着与当前基线不符的草稿：只提示，不自动套用。
  bool get hasDraftConflict => false;

  String? get conflictReason => null;

  /// 格式不认识或损坏的草稿文件路径（保留供查看）。
  String? get damagedDraftPath => null;
}

/// 由现成数据构成的来源（界面样板与测试替身使用）。
class StaticWorkbenchData extends WorkbenchData {
  const StaticWorkbenchData({
    required this.workspaceName,
    required this.workspacePath,
    this.schemaRevision = 0,
    this.resources = const [],
    this.tasks = const [],
    this.draftCount = 0,
    this.busy = false,
    this.candidateExpired = false,
    this.loadError,
    this.recoveryNeeded = false,
    this.recoveryJournals = const [],
  });

  @override
  final String workspaceName;
  @override
  final String workspacePath;
  @override
  final int schemaRevision;
  @override
  final List<WorkbenchResource> resources;
  @override
  final List<WorkbenchTask> tasks;
  @override
  final int draftCount;
  @override
  final bool busy;
  @override
  final bool candidateExpired;
  @override
  final String? loadError;
  @override
  final bool recoveryNeeded;
  @override
  final List<String> recoveryJournals;
}
