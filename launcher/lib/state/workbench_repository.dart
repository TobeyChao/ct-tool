/// 真实内核驱动的工作台数据（native-flutter-workbench 任务 2.3/3.1/3.4）。
///
/// 只读链路：切换工作区 → `workspace.open` → `resources.list` → 按需 `table.preview`。
/// 编辑链路：把用户动作拼成内核词表里的命令入草稿（3.1），用 `schema.candidate` 让内核
/// 判定，再以双守卫 `schema.save` 落盘 YAML（3.4）。
/// 两条硬约束：**旧工作区的回包与事件不得进入当前视图**（代次 + workspaceId 双重校验）；
/// **任何保存拒绝都保留草稿**，只作废候选。
library;

import 'dart:collection';

import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';
import 'draft_store.dart';
import '../ui/workbench/workbench_models.dart';
import 'schema_draft.dart';

/// 工作台数据仓库。
class WorkbenchRepository extends ChangeNotifier implements WorkbenchData {
  /// [store] 为 null 时不碰用户目录（界面样板与单测默认不落盘）：
  /// 持久化由壳层显式开启，避免测试环境去问平台通道要目录。
  WorkbenchRepository({required this.worker, this.store});

  final KernelGateway worker;
  final DraftStore? store;

  int _generation = 0;
  String _root = '';
  String? _workspaceId;
  WorkspaceSnapshot? _snapshot;
  List<ResourceEntry> _entries = const [];
  final Map<String, TablePreviewResult> _previews = {};
  final Set<String> _pendingPreviews = {};
  String? _error;
  String? _previewError;
  bool _loading = false;

  final CommandLog _log = CommandLog();
  String _schemaBaseline = '';
  int _draftGeneration = 0;
  SchemaCandidateResult? _candidate;

  /// 候选被内核直接拒掉时回传的结构化问题（用于定位，不丢弃）。
  List<Issue> _rejectedProblems = const [];
  String? _draftError;
  bool _candidateBusy = false;

  bool _saving = false;
  String? _saveError;
  String? _refreshError;
  SchemaSaveResult? _lastSave;
  String? _recoveryNote;

  bool _draftPersisted = true;
  String? _persistError;
  DateTime? _draftSavedAt;
  Future<void>? _pendingPersist;
  DraftEnvelope? _conflictingDraft;
  String? _conflictReason;
  String? _damagedPath;
  String? _damagedReason;

  // ---- 只读视图 ----

  String get workspaceRoot => _root;

  int get generation => _generation;

  String? get workspaceId => _workspaceId;

  bool get loading => _loading;

  /// 草稿基线（sha256）：来自 `resources.list`，候选与保存守卫都用它。
  String get schemaBaseline => _schemaBaseline;

  /// 内核快照代次。
  @override
  int get schemaRevision => _snapshot?.revision ?? 0;

  @override
  String get workspaceName =>
      _root.isEmpty ? '' : _root.split(RegExp(r'[\\/]')).last;

  @override
  String get workspacePath => _root;

  @override
  List<WorkbenchTask> get tasks => const [];

  @override
  int get draftCount => _log.active.length;

  @override
  bool get busy =>
      _loading ||
      _saving ||
      _pendingPreviews.isNotEmpty ||
      worker.status == WorkerStatus.starting;

  @override
  bool get candidateExpired => false;

  @override
  String? get loadError => _error;

  @override
  bool get sampleData => false;

  @override
  bool get draftPersisted => store == null || _draftPersisted;

  @override
  String? get persistError => _persistError;

  @override
  bool get hasDraftConflict => _conflictingDraft != null;

  @override
  String? get conflictReason => _conflictReason;

  @override
  String? get damagedDraftPath => _damagedPath;

  /// 投影缓存防止重复构造清单；预览行由 _PreviewRows 按可见索引转换，
  /// 翻页时不再同步格式化整张预览表。
  String? _resourcesKey;
  List<WorkbenchResource>? _resourcesCache;

  String _resourcesCacheKey() {
    var previewCells = 0;
    var previewRevisionSum = 0;
    for (final preview in _previews.values) {
      previewCells += preview.rows.length;
      previewRevisionSum += preview.revision;
    }
    final names = StringBuffer();
    for (final entry in _entries) {
      names
        ..write(entry.name)
        ..write(':')
        ..write(entry.kind.wire)
        ..write('|');
    }
    return '$names${_previews.length}|$previewCells|$previewRevisionSum'
        '|${_log.commands.length}|${_log.cursor}|$_schemaBaseline';
  }

  @override
  List<WorkbenchResource> get resources {
    final key = _resourcesCacheKey();
    final cached = _resourcesCache;
    if (cached != null && _resourcesKey == key) return cached;
    final computed = _computeResources();
    _resourcesKey = key;
    _resourcesCache = computed;
    return computed;
  }

  List<WorkbenchResource> _computeResources() {
    final nodes = <_DraftNode>[
      for (final entry in _entries)
        _DraftNode.fromEntry(
          entry,
          // 字段行优先取内核清单自带的 schema 定义（枚举成员顺序即 ordinal）；
          // 清单没给时才退回预览列，草稿命令随后覆盖这份种子。
          fields: entry.fields != null || entry.values != null
              ? _fieldsOf(entryShapeOf(entry))
              : _fieldsFromColumns(_previews[entry.name]?.columns ?? const []),
        ),
    ];
    for (final command in _log.active) {
      _applyToNodes(nodes, command);
    }
    return nodes
        .map((node) => node.toResource(_previews))
        .toList(growable: false);
  }

  WorkbenchResource? resourceNamed(String name) {
    for (final resource in resources) {
      if (resource.name == name) return resource;
    }
    return null;
  }

  TablePreviewResult? previewOf(String table) => _previews[table];

  List<String> columnsOf(String table) =>
      (_previews[table]?.columns ?? const []).map((c) => c.name).toList();

  // ---- 工作区与预览 ----

  /// 清空当前工作区（未绑定或用户移除目录）：不发请求，视图回到空态。
  void clearWorkspace() {
    _generation++;
    _root = '';
    _workspaceId = null;
    _snapshot = null;
    _entries = const [];
    _previews.clear();
    _pendingPreviews.clear();
    _schemaBaseline = '';
    _error = null;
    _loading = false;
    notifyListeners();
  }

  /// 切换工作区：先清空旧视图与草稿，再读快照与清单；旧请求的回包一律丢弃。
  Future<void> switchWorkspace(String root) async {
    final generation = ++_generation;
    _root = root;
    _workspaceId = null;
    _snapshot = null;
    _entries = const [];
    _previews.clear();
    _pendingPreviews.clear();
    _schemaBaseline = '';
    _error = null;
    _previewError = null;
    _log.clear();
    _candidate = null;
    _rejectedProblems = const [];
    _draftError = null;
    _saveError = null;
    _refreshError = null;
    _lastSave = null;
    _loading = root.isNotEmpty;
    notifyListeners();
    if (root.isEmpty) return;
    try {
      await _reload(generation: generation, clearDraft: true);
      if (_isCurrent(generation)) await restoreDraft();
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = _readFailure(e);
    } finally {
      if (_isCurrent(generation)) {
        _loading = false;
        notifyListeners();
      }
    }
  }

  // ---- 异常退出恢复（任务 4.7） ----

  /// 内核报告上次退出留下未完成的发布事务：总览必须给出恢复入口。
  @override
  bool get recoveryNeeded => _snapshot?.recovery.needed ?? false;

  /// 待恢复的发布日志名，原样取自 `workspace.open`。
  @override
  List<String> get recoveryJournals => _snapshot?.recovery.journals ?? const [];

  /// 上一次恢复的结果说明（内核 `detail`，不自行编造）。
  String? get recoveryNote => _recoveryNote;

  /// 显式恢复：三种结局（recovered / noop / blocked）原样交给界面，成功后重读快照与清单。
  Future<RecoverResult?> recover() async {
    final generation = _generation;
    _loading = true;
    _error = null;
    _recoveryNote = null;
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.workspaceRecover,
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return null;
      final result = RecoverResult.fromJson(payload! as Map<String, Object?>);
      _recoveryNote = '${result.outcome.wire}：${result.detail}';
      await _reload(generation: generation, clearDraft: false);
      return result;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      _error = '${e.code}：${e.message}';
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      _error = '恢复失败：$e';
      return null;
    } finally {
      if (_isCurrent(generation)) {
        _loading = false;
        notifyListeners();
      }
    }
  }

  /// 重读快照与资源清单。[clearDraft] 为真时连草稿一起清（切换工作区/保存成功）。
  Future<void> _reload({
    required int generation,
    required bool clearDraft,
  }) async {
    final openPayload = await worker.query(
      Methods.workspaceOpen,
      workspaceRoot: _root,
    );
    final listPayload = await worker.query(
      Methods.resourcesList,
      workspaceRoot: _root,
    );
    if (!_isCurrent(generation)) return;
    _snapshot = WorkspaceSnapshot.fromJson(_map(openPayload));
    final listed = ResourcesListResult.fromJson(_map(listPayload));
    _entries = listed.resources;
    _schemaBaseline = listed.schemaRevision;
    _workspaceId = worker.lastWorkspaceId;
    _candidate = null;
    _rejectedProblems = const [];
    if (clearDraft) {
      _log.clear();
      _previews.clear();
      _draftError = null;
    }
  }

  /// 模板生成/迁移之后必须刷新该表预览：缓存的旧列会让界面继续显示迁移前的结构。
  Future<void> reloadPreview(String table) {
    _previews.remove(table);
    return loadPreview(table, force: true);
  }

  /// 按需拉一页只读预览；同一张表不重复请求。
  /// 预览每页行数：与内核默认一致，界面不自己放大页数。
  static const int previewPageLimit = 50;

  Future<void> loadPreview(
    String table, {
    int limit = previewPageLimit,
    bool force = false,
  }) async {
    final generation = _generation;
    final isTable = _entries.any(
      (entry) => entry.name == table && entry.kind == ResourceKind.table,
    );
    if (!isTable ||
        _pendingPreviews.contains(table) ||
        (!force && _previews.containsKey(table))) {
      return;
    }
    _pendingPreviews.add(table);
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.tablePreview,
        params: {
          'table': table,
          'page': {'limit': limit},
        },
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      _previews[table] = TablePreviewResult.fromJson(_map(payload));
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      // 预览失败只影响预览区，不覆盖工作区级别的原因。
      _previewError = '预览 $table 失败：${_detail(e)}';
    } finally {
      _pendingPreviews.remove(table);
      if (_isCurrent(generation)) notifyListeners();
    }
  }

  /// 预览是否还有下一页（内核游标非空）。
  bool previewHasMore(String table) =>
      _previews[table]?.nextCursor?.isNotEmpty ?? false;

  /// 该表预览是否正在取页（首页或续页）。
  bool previewLoading(String table) => _pendingPreviews.contains(table);

  /// 预览续页：内核给 `nextCursor` 才能继续，**追加**而不是替换，已看过的行不跳。
  /// 快照代次变了就整页重查——不把两版行混在同一张表里。
  Future<void> loadMorePreview(String table) async {
    final current = _previews[table];
    final cursor = current?.nextCursor;
    if (current == null || cursor == null || cursor.isEmpty) return;
    if (_pendingPreviews.contains(table)) return;
    final generation = _generation;
    var staleRevision = false;
    _pendingPreviews.add(table);
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.tablePreview,
        params: {
          'table': table,
          'page': {'limit': previewPageLimit, 'cursor': cursor},
        },
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      final next = TablePreviewResult.fromJson(_map(payload));
      if (next.revision != current.revision) {
        // 快照代次变了：等自己让出「在途」标记后再整页重查——
        // 在持标记期间嵌套调用会被 loadPreview 自己的去重挡掉（真缺陷，测试抓到）。
        staleRevision = true;
      } else {
        _previews[table] = TablePreviewResult(
          revision: next.revision,
          columns: current.columns,
          rows: [...current.rows, ...next.rows],
          nextCursor: next.nextCursor,
        );
      }
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _previewError = '预览 $table 续页失败：${_detail(e)}';
    } finally {
      _pendingPreviews.remove(table);
      if (_isCurrent(generation)) notifyListeners();
    }
    if (staleRevision && _isCurrent(generation)) {
      await loadPreview(table, force: true);
    }
  }

  bool acceptsEvent(String? eventWorkspaceId) =>
      eventWorkspaceId != null &&
      _workspaceId != null &&
      eventWorkspaceId == _workspaceId;

  /// 实时事件映射为视图刷新；旧工作区的迟到事件直接丢弃。
  void onWorkerEvent(Message message) {
    final id = switch (message) {
      final LogEvent e => e.workspaceId,
      final ProgressEvent e => e.workspaceId,
      final IssueEvent e => e.workspaceId,
      final ResultMessage e => e.workspaceId,
      final ErrorMessage e => e.workspaceId,
      _ => null,
    };
    if (!acceptsEvent(id)) return;
    notifyListeners();
  }

  // ---- 草稿（3.1）----

  List<SchemaCommand> get commands => _log.commands;

  /// 撤销游标：指向下一条待执行命令（恢复时要原样回来）。
  int get cursor => _log.cursor;

  bool get canUndo => _log.canUndo;

  /// 逐步回退到第 `target` 步（保留重做分支）：跨模块草稿条的「撤回到此处」用它。
  bool undoTo(int target) {
    if (_frozenWhileSaving()) return false;
    final moved = _log.undoTo(target);
    if (!moved) return false;
    _schedulePersist();
    _candidate = null;
    _rejectedProblems = const [];
    notifyListeners();
    return true;
  }

  /// 草稿条目的可读标签（含游标位置），供草稿条与历史面板展示。
  List<(int, String, bool)> get draftOutline {
    final commands = _log.commands;
    return [
      for (var i = 0; i < commands.length; i++)
        (i + 1, describeCommand(commands[i]), i < _log.cursor),
    ];
  }

  int get draftCursor => _log.cursor;

  bool get canRedo => _log.canRedo;

  bool get hasDraft => _log.active.isNotEmpty;

  SchemaCandidateResult? get candidate => _candidate;

  String? get draftError => _draftError;

  bool get candidateBusy => _candidateBusy;

  /// 保存进行中禁止编辑：否则保存请求携带的命令集与提交后的状态不一致，
  /// 用户会看到"已保存"却又冒出新的草稿。
  bool get editingFrozen => _saving;

  String? get refreshError => _refreshError;

  void _schedulePersist() {
    _pendingPersist = persistDraft();
  }

  bool _frozenWhileSaving() {
    if (!_saving) return false;
    _draftError = '保存进行中，编辑已冻结（等本次提交结束）';
    notifyListeners();
    return true;
  }

  void _enqueue(SchemaCommand command) {
    if (_frozenWhileSaving()) return;
    _log.append(command);
    _candidate = null;
    _rejectedProblems = const [];
    _draftError = null;
    _schedulePersist();
    notifyListeners();
  }

  void createTable(String name) => _enqueue(SchemaCommands.addTable(name));

  void createRecord(String name) => _enqueue(SchemaCommands.addRecord(name));

  void createEnum(String name) => _enqueue(SchemaCommands.addEnum(name));

  void renameResource(String from, String to) =>
      _enqueue(SchemaCommands.renameResource(from, to));

  void deleteResource(String id) => _enqueue(SchemaCommands.deleteResource(id));

  void addField(
    String owner,
    String name,
    String type, {
    bool i18n = false,
    String? ref,
  }) => _enqueue(
    SchemaCommands.addField(owner, name, type, i18n: i18n, ref: ref),
  );

  void renameField(String owner, String from, String to) =>
      _enqueue(SchemaCommands.renameField(owner, from, to));

  void deleteField(String owner, String name) =>
      _enqueue(SchemaCommands.deleteField(owner, name));

  void setFieldComment(String owner, String field, String comment) =>
      _enqueue(SchemaCommands.setProperty(owner, field, 'comment', comment));

  void setFieldI18n(String owner, String field, bool value) =>
      _enqueue(SchemaCommands.setProperty(owner, field, 'i18n', value));

  void setEnumValues(String name, List<String> values) =>
      _enqueue(SchemaCommands.setEnumValues(name, values));

  /// 改字段类型：类型表达式交给内核解析，客户端不校验合法性。
  void setFieldType(String owner, String field, String typeText) =>
      _enqueue(SchemaCommands.setType(owner, field, typeText));

  /// 属性名走内核白名单（comment / i18n / server_only / excel_columns / ref）：
  /// 客户端不做第二套校验，非法组合由内核候选报错。
  void setFieldProperty(
    String owner,
    String field,
    String property,
    Object? value,
  ) => _enqueue(SchemaCommands.setProperty(owner, field, property, value));

  void setFieldServerOnly(String owner, String field, bool value) =>
      _enqueue(SchemaCommands.setProperty(owner, field, 'server_only', value));

  /// ref 传空串即移除声明（内核按 null 处理）。
  void setFieldRef(String owner, String field, String value) =>
      _enqueue(SchemaCommands.setProperty(owner, field, 'ref', value));

  /// 传 null 移除展开组数（内核要求正整数或 null）。
  void setFieldExcelColumns(String owner, String field, int? value) => _enqueue(
    SchemaCommands.setProperty(owner, field, 'excel_columns', value),
  );

  void moveField(String owner, String field, int to) =>
      _enqueue(SchemaCommands.moveField(owner, field, to));

  /// 覆盖式声明表索引；空集合即移除全部索引声明。
  ///
  /// [tableId] 用内核资源 id（`table:Item`），与候选合并索引时的查表键一致。
  void setTableIndexes(String tableId, List<String> kinds) =>
      _enqueue(SchemaCommands.setIndexes(tableId, kinds));

  void renameEnumItem(
    String name,
    String oldName,
    String newName,
    int originalOrdinal,
  ) => _enqueue(
    SchemaCommands.renameEnumItem(name, oldName, newName, originalOrdinal),
  );

  /// 当前可展示的候选问题：无阻塞时来自候选结果，被拒时来自错误明细。
  List<Issue> get candidateProblems =>
      _candidate?.problems ?? _rejectedProblems;

  /// 内核候选问题里属于某个资源/字段的部分（原文展示，不改写不补造）。
  List<Issue> problemsFor(String resourceName, {String? fieldName}) {
    final problems = candidateProblems;
    if (resourceName.isEmpty) return const [];
    return [
      for (final issue in problems)
        if (_locates(issue.resource, resourceName, fieldName)) issue,
    ];
  }

  /// 内核 location 形态是 `资源 ID` 或 `资源 ID/字段名`。
  static bool _locates(String? location, String resource, String? field) {
    if (location == null || location.isEmpty) return false;
    if (field != null) {
      return location.endsWith('/$field') && location.contains(resource);
    }
    return location == resource ||
        location.contains('$resource/') ||
        location.contains(resource);
  }

  void undoDraft() {
    if (_frozenWhileSaving()) return;
    _log.undo();
    _schedulePersist();
    _candidate = null;
    _rejectedProblems = const [];
    notifyListeners();
  }

  void redoDraft() {
    if (_frozenWhileSaving()) return;
    _log.redo();
    _schedulePersist();
    _candidate = null;
    _rejectedProblems = const [];
    notifyListeners();
  }

  void discardDraft() {
    if (_frozenWhileSaving()) return;
    _log.clear();
    _schedulePersist();
    _candidate = null;
    _rejectedProblems = const [];
    _draftError = null;
    _saveError = null;
    notifyListeners();
  }

  /// 让内核按同一批命令算候选：有阻塞问题时界面须禁用保存。
  Future<SchemaCandidateResult?> requestCandidate() async {
    if (_root.isEmpty || _schemaBaseline.isEmpty) return null;
    final generation = _generation;
    final baseline = _schemaBaseline;
    final sentGeneration = ++_draftGeneration;
    final params = SchemaCandidateParams(
      schemaRevision: baseline,
      commands: _log.commands,
      cursor: '${_log.cursor}',
      draftGeneration: sentGeneration,
    );
    _candidateBusy = true;
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.schemaCandidate,
        params: params.toJson(),
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation) || _schemaBaseline != baseline) {
        return _candidate;
      }
      final result = SchemaCandidateResult.fromJson(
        payload! as Map<String, Object?>,
      );
      // 两层校验：既要等于本次请求发出的代次（内核回声），也要等于仓库当前
      // 最新代次——否则「旧请求晚到」会把新编辑算出的候选覆盖回旧结论。
      if (result.draftGeneration != sentGeneration ||
          sentGeneration != _draftGeneration) {
        return _candidate;
      }
      _candidate = result;
      _rejectedProblems = const [];
      _draftError = null;
      return result;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      _draftError = '${e.code}：${e.message}';
      _candidate = null;
      // 内核对非法草稿是「拒绝候选」而不是返回空候选：
      // 问题明细必须留下，否则界面无法定位到字段。
      _rejectedProblems = e.issues;
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      _draftError = '候选计算失败：$e';
      _candidate = null;
      _rejectedProblems = const [];
      return null;
    } finally {
      if (_isCurrent(generation)) {
        _candidateBusy = false;
        notifyListeners();
      }
    }
  }

  // ---- 保存（3.4：双守卫 + YAML-only）----

  bool get saving => _saving;

  String? get saveError => _saveError;

  String? get previewError => _previewError;

  SchemaSaveResult? get lastSave => _lastSave;

  /// 有草稿、候选已算出且无阻塞问题、净差异非零、基线非空、当前没在忙——才允许保存。
  /// （候选计算中与净差异为零也要禁：前者结论未出，后者是空事务，不该占用一次保存。
  bool get canSave {
    final found = _candidate;
    if (found == null || _saving || _candidateBusy || _loading) return false;
    final diff = found.netDiff;
    return hasDraft &&
        found.problems.isEmpty &&
        _schemaBaseline.isNotEmpty &&
        !(diff.added.isEmpty && diff.removed.isEmpty && diff.changed.isEmpty);
  }

  /// 双守卫保存：成功即清草稿并重读内核状态；任何拒绝都保留草稿、只作废候选。
  Future<SchemaSaveResult?> saveDraft() async {
    final found = _candidate;
    if (!canSave || found == null) return null;
    final generation = _generation;
    final baseline = _schemaBaseline;
    final params = SchemaSaveParams(
      schemaRevision: baseline,
      candidateHash: found.candidateHash,
      commands: _log.commands,
      cursor: '${_log.cursor}',
    );
    _saving = true;
    _saveError = null;
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.schemaSave,
        params: params.toJson(),
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return null;
      _lastSave = SchemaSaveResult.fromJson(payload! as Map<String, Object?>);
      // 提交已经发生：先把结果落地（清草稿、换基线、清候选），再做状态刷新。
      // 刷新失败只报「状态暂不可用」，绝不把已提交的草稿恢复回去、也不要求重复保存。
      _log.clear();
      _candidate = null;
      _rejectedProblems = const [];
      _draftError = null;
      _saveError = null;
      _schemaBaseline = _lastSave!.schemaRevision;
      _schedulePersist();
      notifyListeners();
      if (!_isCurrent(generation)) return _lastSave;
      try {
        await _reload(generation: generation, clearDraft: false);
        if (_isCurrent(generation)) _refreshError = null;
      } on Object catch (e) {
        if (!_isCurrent(generation)) return _lastSave;
        _refreshError = 'YAML 已保存，但状态刷新失败：${_detail(e)}';
        _error = _refreshError;
      }
      return _lastSave;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return null;
      _saveError = '${e.code}：${e.message}';
      _candidate = null;
      _rejectedProblems = const [];
      // 基线可能已被外部改动：刷新基线好让界面重算候选，草稿原样保留。
      try {
        await _reload(generation: generation, clearDraft: false);
      } on Object {
        // 刷新失败不覆盖保存被拒的原因
      }
      return null;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return null;
      _saveError = '保存失败：$e';
      _candidate = null;
      _rejectedProblems = const [];
      return null;
    } finally {
      if (_isCurrent(generation)) {
        _saving = false;
        notifyListeners();
      }
    }
  }

  // ---- 投影辅助：只做形状变化，语义判断交给内核 ----

  static _DraftNode? _findNode(List<_DraftNode> nodes, String owner) {
    for (final node in nodes) {
      if (node.id == owner || node.name == owner) return node;
    }
    return null;
  }

  void _applyToNodes(List<_DraftNode> nodes, SchemaCommand command) {
    final payload = command.payload;
    switch (command.kind) {
      case 'add_resource':
        final kind = (payload['kind'] as String? ?? 'table').trim();
        final resource =
            (payload['resource'] as Map<String, Object?>?) ?? const {};
        final name = ((resource['table'] ?? resource['name']) as String? ?? '')
            .trim();
        if (name.isEmpty) return;
        final id = '$kind:$name';
        if (_findNode(nodes, id) != null) return;
        nodes.add(
          _DraftNode(
            name: name,
            kind: _kindOf(kind),
            path: '草稿 · 保存后由内核落盘',
            draft: true,
            fields: _fieldsOf(resource),
          ),
        );
      case 'delete_resource':
        final doomed = (payload['name'] as String? ?? '').trim();
        if (doomed.isEmpty) return;
        nodes.removeWhere((node) => node.id == doomed || node.name == doomed);
      case 'rename_resource':
        final from = (payload['old'] as String? ?? '').trim();
        final to = (payload['new'] as String? ?? '').trim();
        final node = _findNode(nodes, from);
        if (node == null || to.isEmpty) return;
        node
          ..name = to
          ..draft = true;
      case 'add_field':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final field = payload['field'] as Map<String, Object?>?;
        if (node == null || field == null) return;
        node
          ..fields.addAll(
            _fieldsOf({
              'fields': [field],
            }),
          )
          ..draft = true;
      case 'rename_field':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final from = (payload['old'] as String? ?? '').trim();
        final to = (payload['new'] as String? ?? '').trim();
        if (node == null || to.isEmpty) return;
        node
          ..fields = [
            for (final field in node.fields)
              if (field.name == from) _renamed(field, to) else field,
          ]
          ..draft = true;
      case 'delete_field':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final name = (payload['name'] as String? ?? '').trim();
        if (node == null || name.isEmpty) return;
        node
          ..fields = node.fields.where((f) => f.name != name).toList()
          ..draft = true;
      case 'set_type':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final name = (payload['name'] as String? ?? '').trim();
        final typeText = (payload['type_text'] as String? ?? '').trim();
        if (node == null || typeText.isEmpty) return;
        node
          ..fields = [
            for (final field in node.fields)
              if (field.name == name) _retyped(field, typeText) else field,
          ]
          ..draft = true;
      case 'set_property':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final name = (payload['name'] as String? ?? '').trim();
        final property = (payload['property'] as String? ?? '').trim();
        final value = payload['value'];
        if (node == null) return;
        node
          ..fields = [
            for (final field in node.fields)
              if (field.name == name)
                _withProperty(field, property, value)
              else
                field,
          ]
          ..draft = true;
      case 'move_field':
        final node = _findNode(nodes, (payload['owner'] as String? ?? ''));
        final name = (payload['name'] as String? ?? '').trim();
        final to = payload['to'] is int ? payload['to']! as int : -1;
        if (node == null || name.isEmpty || to < 0) return;
        node
          ..fields = () {
            final moved = List<WorkbenchField>.of(node.fields);
            final from = moved.indexWhere((f) => f.name == name);
            if (from < 0) return moved;
            final field = moved.removeAt(from);
            moved.insert(to.clamp(0, moved.length), field);
            return moved;
          }()
          ..draft = true;
      case 'set_indexes':
        // 命令里是资源 id，_findNode 同时认 id 与裸名。
        final table = (payload['table'] as String? ?? '').trim();
        final node = _findNode(nodes, table);
        if (node == null) return;
        node
          ..indexes = [
            for (final item in (payload['indexes'] as List? ?? const []))
              if (item is Map<String, Object?>)
                if ((item['kind'] as String? ?? '').trim().isNotEmpty)
                  (item['kind'] as String? ?? '').trim(),
          ]
          ..draft = true;
      case 'rename_enum_item':
        final name = (payload['name'] as String? ?? '').trim();
        final oldName = (payload['oldName'] as String? ?? '').trim();
        final newName = (payload['newName'] as String? ?? '').trim();
        final ordinal = payload['originalOrdinal'] is int
            ? payload['originalOrdinal']! as int
            : -1;
        final node = _findNode(nodes, name) ?? _findNode(nodes, 'enum:$name');
        if (node == null || newName.isEmpty || ordinal < 0) return;
        node
          ..fields = [
            for (var i = 0; i < node.fields.length; i++)
              if (i == ordinal && node.fields[i].name == oldName)
                _copy(node.fields[i], name: newName)
              else
                node.fields[i],
          ]
          ..draft = true;
      case 'set_enum_values':
        final node = _findNode(nodes, (payload['name'] as String? ?? ''));
        final values = payload['values'] as List?;
        if (node == null || values == null) return;
        node
          ..fields = _fieldsOf({
            'values': [
              for (final item in values)
                if (item is Map<String, Object?>) item else {'name': '$item'},
            ],
          })
          ..draft = true;
    }
  }

  static WorkbenchResourceKind _kindOf(String wire) => switch (wire) {
    'table' => WorkbenchResourceKind.table,
    'record' => WorkbenchResourceKind.record,
    _ => WorkbenchResourceKind.enumType,
  };

  /// 内核预览列 → 界面字段行：属性一律取自 `table.preview`，缺席即未声明。
  static List<WorkbenchField> _fieldsFromColumns(List<PreviewColumn> columns) =>
      [
        for (final column in columns)
          WorkbenchField(
            name: column.name,
            type: column.typeExpr,
            role: column.role == 'primary' ? 'primary' : '',
            constraints: column.ref ?? '',
            description: column.comment,
            localized: column.i18n,
            serverOnly: column.serverOnly,
            excelColumns: column.excelColumns,
          ),
      ];

  static WorkbenchField _copy(
    WorkbenchField field, {
    String? name,
    String? type,
    String? constraints,
    String? description,
    bool? localized,
    bool? serverOnly,
    Object? excelColumns = _unset,
  }) => WorkbenchField(
    name: name ?? field.name,
    type: type ?? field.type,
    role: field.role,
    constraints: constraints ?? field.constraints,
    defaultValue: field.defaultValue,
    description: description ?? field.description,
    localized: localized ?? field.localized,
    serverOnly: serverOnly ?? field.serverOnly,
    excelColumns: excelColumns == _unset
        ? field.excelColumns
        : excelColumns == null
        ? null
        : excelColumns as int,
  );

  static const Object _unset = Object();

  static WorkbenchField _renamed(WorkbenchField field, String to) =>
      _copy(field, name: to);

  static WorkbenchField _retyped(WorkbenchField field, String typeText) =>
      _copy(field, type: typeText);

  /// 属性投影与内核 `set_property` 白名单一致：
  /// comment / i18n / server_only / excel_columns / ref。
  static WorkbenchField _withProperty(
    WorkbenchField field,
    String property,
    Object? value,
  ) => switch (property) {
    'ref' => _copy(field, constraints: value is String ? value : ''),
    'comment' => _copy(field, description: value is String ? value : ''),
    'i18n' => _copy(field, localized: value is bool ? value : false),
    'server_only' => _copy(field, serverOnly: value is bool ? value : false),
    'excel_columns' => _copy(field, excelColumns: value is int ? value : null),
    _ => field,
  };

  /// 资源文档的 fields/values → 界面字段行（枚举把成员列成行，共用一套 UI）。
  /// 清单条目 → 文档形态（同 YAML 词表），交给 `_fieldsOf` 统一投影。
  static Map<String, Object?> entryShapeOf(ResourceEntry entry) => {
    if (entry.fields != null) 'fields': entry.fields,
    if (entry.values != null) 'values': entry.values,
    if (entry.primary != null) 'primary': entry.primary,
  };

  static List<WorkbenchField> _fieldsOf(Map<String, Object?> resource) {
    if (resource['fields'] case final List<dynamic> list) {
      final primary = (resource['primary'] as String? ?? '').trim();
      return [
        for (final raw in list)
          if (raw is Map<String, Object?>)
            WorkbenchField(
              name: (raw['name'] as String? ?? '').trim(),
              type: (raw['type'] as String? ?? '').trim(),
              role: (raw['name'] as String? ?? '') == primary ? 'primary' : '',
              constraints: (raw['ref'] as String? ?? ''),
              description: (raw['comment'] as String? ?? ''),
              localized: raw['i18n'] == true,
              serverOnly: raw['server_only'] == true,
              excelColumns: raw['excel_columns'] is int
                  ? raw['excel_columns']! as int
                  : null,
            ),
      ];
    }
    if (resource['values'] case final List<dynamic> list) {
      return [
        for (final (index, raw) in list.indexed)
          if (raw is Map<String, Object?>)
            WorkbenchField(
              name: (raw['name'] as String? ?? '').trim(),
              type: '枚举项',
              constraints: 'ordinal $index',
              description: (raw['comment'] as String? ?? ''),
            ),
      ];
    }
    return const [];
  }

  // ---- 草稿持久化与恢复（任务 3.5）----

  /// 用户目录里的草稿文件按工作区身份隔离；这里用规范化后的绝对路径做身份。
  String get draftKey =>
      _root.replaceAll(String.fromCharCode(92), String.fromCharCode(47));

  DateTime? get draftSavedAt => _draftSavedAt;

  /// 基线已变而保留下来的草稿（不自动套用，也不删除）。
  DraftEnvelope? get conflictingDraft => _conflictingDraft;

  /// 损坏原因（界面与日志都会带上内核无法解析的原文摘要）。

  String? get damagedReason => _damagedReason;

  /// 一句话说明草稿落盘状态：界面与退出守卫都用它，不各自拼文案。
  String get draftPersistLabel {
    if (store == null) return '未开启用户目录持久化';
    if (!_draftPersisted) {
      return "未落盘：${_persistError ?? '未知原因'}";
    }
    if (_log.commands.isEmpty) return '无草稿';
    final at = _draftSavedAt;
    if (at == null) return '待落盘';
    final hh = at.hour.toString().padLeft(2, '0');
    final mm = at.minute.toString().padLeft(2, '0');
    return "已落盘 $hh:$mm";
  }

  /// 等最近一次落盘结束（测试与界面用）。
  Future<void> get persistSettled => _pendingPersist ?? Future.value();

  /// 落盘当前草稿：空草稿删除文件；失败只警告，不清内存编辑、不谎称已保留。
  Future<void> persistDraft() async {
    final sink = store;
    if (sink == null || draftKey.isEmpty) return;
    final commands = _log.commands;
    if (commands.isEmpty) {
      try {
        await sink.clear(draftKey);
        if (draftPersistedChanged(true)) notifyListeners();
      } on Object catch (e) {
        _persistError = '$e';
        _draftPersisted = false;
        notifyListeners();
      }
      return;
    }
    final envelope = DraftEnvelope(
      formatVersion: DraftEnvelope.currentFormat,
      workspaceKey: draftKey,
      baseline: _schemaBaseline,
      commands: commands,
      cursor: _log.cursor,
      savedAt: DateTime.now(),
    );
    try {
      await sink.save(envelope);
      _draftSavedAt = envelope.savedAt;
      _persistError = null;
      _draftPersisted = true;
      notifyListeners();
    } on Object catch (e) {
      // 内存草稿仍在，界面持续显示未持久化警告。
      _persistError = '$e';
      _draftPersisted = false;
      notifyListeners();
    }
  }

  bool draftPersistedChanged(bool value) {
    if (_draftPersisted == value && _persistError == null) return false;
    _draftPersisted = value;
    _persistError = null;
    return true;
  }

  /// 重启/换工作区后尝试恢复：只有工作区与基线都匹配才套用；
  /// 基线不同或格式不认识一律保留原文件并提示，绝不静默套用或删除。
  Future<DraftOutcome> restoreDraft() async {
    _conflictingDraft = null;
    _conflictReason = null;
    _damagedPath = null;
    _damagedReason = null;
    final sink = store;
    if (sink == null || draftKey.isEmpty) return DraftOutcome.none;
    final loaded = await sink.load(
      workspaceKey: draftKey,
      baseline: _schemaBaseline,
    );
    switch (loaded.outcome) {
      case DraftOutcome.none:
        // 读不到目录不等于「没有草稿」：要说成「没能持久化」，否则用户会以为
        // 内存里的编辑已经安全落盘。
        if (loaded.reason != null) {
          _persistError = loaded.reason;
          _draftPersisted = false;
          notifyListeners();
        }
        return DraftOutcome.none;
      case DraftOutcome.restored:
        final envelope = loaded.envelope!;
        _log.restore(envelope.commands, envelope.cursor);
        _draftSavedAt = envelope.savedAt;
        _draftPersisted = true;
        _persistError = null;
        _candidate = null;
        notifyListeners();
        return DraftOutcome.restored;
      case DraftOutcome.conflict:
        _conflictingDraft = loaded.envelope;
        _conflictReason = loaded.reason;
        notifyListeners();
        return DraftOutcome.conflict;
      case DraftOutcome.damaged:
        _damagedPath = loaded.path;
        _damagedReason = loaded.reason;
        notifyListeners();
        return DraftOutcome.damaged;
    }
  }

  /// 用户显式丢弃保留的草稿文件（冲突或损坏）；不删掉就不算处理完。
  Future<void> discardStoredDraft() async {
    final sink = store;
    _conflictingDraft = null;
    _conflictReason = null;
    _damagedPath = null;
    _damagedReason = null;
    // 状态先落地重绘，文件操作在后台完成：界面不能停在旧提示上。
    notifyListeners();
    try {
      if (sink != null) await sink.clear(draftKey);
    } on Object catch (e) {
      _persistError = '$e';
    }
    notifyListeners();
  }

  String _readFailure(Object error) {
    final reason = worker.failureReason;
    if (reason != null) return '内核未就绪：$reason';
    return '读取工作区失败：$error';
  }

  String _detail(Object error) => worker.failureReason ?? '$error';

  bool _isCurrent(int generation) => generation == _generation;

  static Map<String, Object?> _map(Object? payload) =>
      payload is Map<String, Object?>
      ? payload
      : throw StateError('payload 形状异常');
}

/// 草稿里的资源节点（新增/改名后的形态）。
class _DraftNode {
  _DraftNode({
    required this.name,
    required this.kind,
    required this.path,
    required this.draft,
    List<WorkbenchField> fields = const [],
    List<String> indexes = const [],
  }) : fields = List.of(fields),
       indexes = List.of(indexes);

  factory _DraftNode.fromEntry(
    ResourceEntry entry, {
    List<WorkbenchField> fields = const [],
  }) => _DraftNode(
    name: entry.name,
    kind: switch (entry.kind) {
      ResourceKind.table => WorkbenchResourceKind.table,
      ResourceKind.record => WorkbenchResourceKind.record,
      ResourceKind.enum_ => WorkbenchResourceKind.enumType,
    },
    path: entry.sourcePath,
    draft: false,
    fields: fields,
    indexes: entry.indexes,
  );

  String name;
  final WorkbenchResourceKind kind;
  String path;
  bool draft;
  List<WorkbenchField> fields;

  /// 已声明的索引 kind（内核给出；set_indexes 是覆盖式声明）。
  List<String> indexes = const [];

  String get kindWire => switch (kind) {
    WorkbenchResourceKind.table => 'table',
    WorkbenchResourceKind.record => 'record',
    WorkbenchResourceKind.enumType => 'enum',
  };

  /// 内核资源 id：随改名自动跟随。
  String get id => '$kindWire:$name';

  WorkbenchResource toResource(Map<String, TablePreviewResult> previews) {
    final preview = previews[name];
    final columns = preview?.columns ?? const [];
    return WorkbenchResource(
      name: name,
      kind: kind,
      path: path,
      dirty: draft,
      fields: fields,
      indexes: indexes,
      previewColumns: columns.map((c) => c.name).toList(),
      previewRows: preview == null ? const [] : _PreviewRows(preview.rows),
      previewHasMore: (preview?.nextCursor ?? '').isNotEmpty,
    );
  }
}

/// 只转换当前 ListView 请求的预览行；同一页滚动返回时复用已经格式化的行。
class _PreviewRows extends ListBase<List<String>> {
  _PreviewRows(this._raw);

  final List<List<Object?>> _raw;
  final Map<int, List<String>> _formatted = {};

  @override
  int get length => _raw.length;

  @override
  set length(int value) => throw UnsupportedError('只读预览');

  @override
  List<String> operator [](int index) {
    RangeError.checkValidIndex(index, this);
    return _formatted.putIfAbsent(
      index,
      () => List<String>.unmodifiable(_raw[index].map(_cellText)),
    );
  }

  @override
  void operator []=(int index, List<String> value) =>
      throw UnsupportedError('只读预览');

  static String _cellText(Object? cell) => switch (cell) {
    null => '',
    final num n => n.toString(),
    final BigInt b => b.toString(),
    _ => '$cell',
  };
}
