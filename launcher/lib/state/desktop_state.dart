import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';

/// 任务问题的一页（含分页令牌）。
class TaskIssuesPage {
  const TaskIssuesPage({
    required this.issues,
    this.revision = 0,
    this.nextCursor,
  });

  final List<Issue> issues;
  final int revision;
  final String? nextCursor;
}

/// 桌面状态查询（native-flutter-workbench 任务 4.5/4.8）。
///
/// 覆盖 `logs.list`（模块/级别筛选 + 游标翻页）、`history.list`（最新在前最多 5 条、跨重启保留）、
/// `tasks.list` / `tasks.issues` / `tasks.dismiss`。与工作台仓库同一套竞态守卫：**切工作区后
/// 旧请求的回包与旧工作区的事件都不得进入当前视图**。
class DesktopStateRepository extends ChangeNotifier {
  DesktopStateRepository({required this.worker});

  final KernelGateway worker;

  static const int logPageSize = 200;
  static const int issuePageSize = 50;

  int _generation = 0;
  String _root = '';
  String? _workspaceId;

  List<RemoteLogEntry> _logs = const [];
  String? _logsCursor;
  bool _logsTruncated = false;
  String? _logModule;
  String? _logLevel;

  List<HistoryEntry> _history = const [];
  List<TaskInfo> _tasks = const [];
  final Map<String, TaskIssuesPage> _issues = {};
  final Set<String> _loadingIssues = {};

  String? _error;
  bool _busy = false;

  List<RemoteLogEntry> get logs => _logs;

  List<HistoryEntry> get history => _history;

  List<TaskInfo> get tasks => _tasks;

  String? get logModule => _logModule;

  String? get logLevel => _logLevel;

  /// 服务端还有更多页（游标非空）。
  bool get logsHasMore => _logsCursor != null;

  /// 首页只取 `logPageSize` 条，界面据此提示「已截断」。
  bool get logsTruncated => _logsTruncated;

  String? get error => _error;

  bool get busy => _busy;

  int get generation => _generation;

  String get workspaceRoot => _root;

  TaskIssuesPage? issuesOf(String taskId) => _issues[taskId];

  bool issuesLoading(String taskId) => _loadingIssues.contains(taskId);

  int get undismissedCount => _tasks.where((task) => !task.dismissed).length;

  /// 绑定工作区：清空旧视图状态再全量刷新；旧回包一律丢弃。
  Future<void> bind(String root) async {
    final generation = ++_generation;
    _root = root;
    _workspaceId = null;
    _logs = const [];
    _logsCursor = null;
    _logsTruncated = false;
    _history = const [];
    _tasks = const [];
    _issues.clear();
    _loadingIssues.clear();
    _error = null;
    if (root.isEmpty) {
      notifyListeners();
      return;
    }
    _busy = true;
    notifyListeners();
    try {
      await Future.wait(<Future<void>>[
        _loadLogs(generation: generation, append: false),
        _loadHistory(generation),
        _loadTasks(generation),
      ]);
    } finally {
      if (_isCurrent(generation)) {
        _busy = false;
        notifyListeners();
      }
    }
  }

  /// 全量刷新（界面「重新读取」）。
  Future<void> refresh() => bind(_root);

  /// 模块/级别筛选：改变筛选即回到第一页，避免混用旧游标。
  Future<void> setLogFilter({String? module, String? level}) async {
    _logModule = module;
    _logLevel = level;
    final generation = _generation;
    _logs = const [];
    _logsCursor = null;
    _logsTruncated = false;
    notifyListeners();
    await _loadLogs(generation: generation, append: false);
  }

  /// 追加下一页日志（有界列表：界面滚动加载，而不是一次性堆几万行）。
  Future<void> loadMoreLogs() async {
    if (_logsCursor == null) return;
    await _loadLogs(generation: _generation, append: true);
  }

  Future<void> _loadLogs({
    required int generation,
    required bool append,
  }) async {
    final params = <String, Object?>{
      'page': {
        'limit': logPageSize,
        if (append && _logsCursor != null) 'cursor': _logsCursor,
      },
      if (_logModule != null) 'module': _logModule,
      if (_logLevel != null) 'level': _logLevel,
    };
    try {
      final payload = await worker.query(
        Methods.logsList,
        params: params,
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      final map = _asMap(payload);
      final page = ((map['entries'] as List?) ?? const [])
          .map((e) => RemoteLogEntry.fromJson(e! as Map<String, Object?>))
          .toList();
      _logs = append ? <RemoteLogEntry>[..._logs, ...page] : page;
      _logsCursor = map['nextCursor'] as String?;
      if (!append) {
        _logsTruncated = _logsCursor != null || page.length >= logPageSize;
      }
      _workspaceId ??= worker.lastWorkspaceId;
    } on WorkerRequestException catch (e) {
      // 游标过期（stale-page）：回到第一页重查，不谎称丢事件。
      if (!_isCurrent(generation)) return;
      if (append && e.code == ProtocolErrorCodes.stalePage) {
        _logsCursor = null;
        await _loadLogs(generation: generation, append: false);
        return;
      }
      _error = '读取日志失败：${e.code}';
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '读取日志失败：$e';
    } finally {
      if (_isCurrent(generation)) notifyListeners();
    }
  }

  Future<void> _loadHistory(int generation) async {
    try {
      final payload = await worker.query(
        Methods.historyList,
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      _history = ((_asMap(payload)['entries'] as List?) ?? const [])
          .map((e) => HistoryEntry.fromJson(e! as Map<String, Object?>))
          .toList();
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '读取历史失败：$e';
    }
  }

  Future<void> _loadTasks(int generation) async {
    try {
      final payload = await worker.query(
        Methods.tasksList,
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      _tasks = ((_asMap(payload)['tasks'] as List?) ?? const [])
          .map((e) => TaskInfo.fromJson(e! as Map<String, Object?>))
          .toList();
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '读取任务失败：$e';
    }
  }

  /// 任务问题按需分页（终态明细也可能很大）。
  Future<void> loadIssues(String taskId, {bool append = false}) async {
    final generation = _generation;
    if (_loadingIssues.contains(taskId)) return;
    final cursor = append ? _issues[taskId]?.nextCursor : null;
    if (append && cursor == null) return;
    _loadingIssues.add(taskId);
    notifyListeners();
    try {
      final payload = await worker.query(
        Methods.tasksIssues,
        params: {
          'taskId': taskId,
          'page': {'limit': issuePageSize, 'cursor': ?cursor},
        },
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      final map = _asMap(payload);
      final page = TaskIssuesPage(
        issues: ((map['issues'] as List?) ?? const [])
            .map((e) => Issue.fromJson(e! as Map<String, Object?>))
            .toList(),
        revision: (map['revision'] as num?)?.toInt() ?? 0,
        nextCursor: map['nextCursor'] as String?,
      );
      final previous = _issues[taskId];
      _issues[taskId] = append && previous != null
          ? TaskIssuesPage(
              issues: [...previous.issues, ...page.issues],
              revision: page.revision,
              nextCursor: page.nextCursor,
            )
          : page;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '读取任务问题失败：${e.code}';
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '读取任务问题失败：$e';
    } finally {
      _loadingIssues.remove(taskId);
      if (_isCurrent(generation)) notifyListeners();
    }
  }

  /// 关闭通知：内核记住状态，重连后不复活。
  Future<void> dismiss(String taskId) async {
    final generation = _generation;
    try {
      await worker.query(
        Methods.tasksDismiss,
        params: {'taskId': taskId},
        workspaceRoot: _root,
      );
      if (!_isCurrent(generation)) return;
      await _loadTasks(generation);
    } on Object catch (e) {
      if (!_isCurrent(generation)) return;
      _error = '关闭通知失败：$e';
    }
  }

  /// 实时事件：只接受当前工作区的，且写任务终态后自动刷新任务/历史/日志。
  Future<void> onWorkerEvent(Message message) async {
    if (_root.isEmpty) return;
    final id = switch (message) {
      final LogEvent e => e.workspaceId,
      final ProgressEvent e => e.workspaceId,
      final IssueEvent e => e.workspaceId,
      final ResultMessage e => e.workspaceId,
      final ErrorMessage e => e.workspaceId,
      _ => null,
    };
    if (id == null) return;
    if (_workspaceId != null && id != _workspaceId) return;
    _workspaceId ??= id;
    if (message is LogEvent) {
      // 实时日志直接进列表；超过上界就丢掉最早的，保证有界。
      _logs = <RemoteLogEntry>[
        ..._logs.take(logPageSize * 5),
        RemoteLogEntry(
          ts: '',
          module: message.module,
          level: message.level,
          message: message.message,
          requestId: message.requestId,
        ),
      ];
      notifyListeners();
      return;
    }
    if (message is ResultMessage || message is ErrorMessage) {
      final generation = _generation;
      await Future.wait(<Future<void>>[
        _loadTasks(generation),
        _loadHistory(generation),
      ]);
    }
  }

  bool _isCurrent(int generation) => generation == _generation;

  static Map<String, Object?> _asMap(Object? payload) =>
      payload is Map<String, Object?>
      ? payload
      : throw StateError('payload 形状异常');
}
