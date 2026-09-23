import 'package:flutter/foundation.dart';

import '../services/protocol/protocol.dart';
import '../services/worker_service.dart';

/// 导出/部署运行的阶段。
enum RunnerPhase {
  idle('空闲'),
  running('运行中'),
  succeeded('成功'),
  cancelled('已取消'),
  failed('失败'),

  /// 断连且没拿到终态：不猜成败，也不自动重放写请求。
  unknown('终态未知');

  const RunnerPhase(this.label);

  final String label;
}

/// 一次运行留下的结果快照，界面直接渲染，不再二次推断。
class RunSummary {
  const RunSummary({
    required this.kind,
    required this.phase,
    this.result,
    this.deploy,
    this.message,
    this.issues = const [],
  });

  /// `export` 或 `deploy`。
  final String kind;
  final RunnerPhase phase;
  final ExportResult? result;
  final DeployResult? deploy;
  final String? message;
  final List<Issue> issues;
}

/// 导出与独立部署的运行器（native-flutter-workbench 任务 4.4/4.6）。
///
/// 它负责三件事：把过滤条件拼成 `export` 参数、把 `progress`/`issue` 事件汇成实时视图；
/// 提供 `cancel`（只转达意图，终态仍以内核回包为准——发布之后再取消不会把成功改写成取消）；
/// 以及断连时标成 `unknown` 且**不自动重放**写请求。
/// 桌面导出不自动部署：部署是显式的 `deploy` 调用。
class ExportRunner extends ChangeNotifier {
  ExportRunner({required this.worker, required this.workspaceRoot});

  final KernelGateway worker;
  final String workspaceRoot;

  /// 运行期日志行的有界条数。
  static const int logHistory = 12;

  /// 实时问题事件的有界条数。
  static const int issueHistory = 50;

  String? table;
  String? lang;
  bool all = false;

  RunnerPhase phase = RunnerPhase.idle;
  int? runningRequestId;
  ProgressEvent? progress;
  final List<IssueEvent> liveIssues = [];
  final List<String> logLines = [];
  RunSummary? last;
  String? error;

  /// `cancel` 的内核回执：cancelling / already_terminal / unknown_request。
  String? cancelState;

  bool get running => phase == RunnerPhase.running;

  bool get canStart => !running;

  /// 断连后要不要把决定权交回用户（不自动重放）。
  bool get needsUserDecision => phase == RunnerPhase.unknown;

  ExportResult? get result => last?.result;

  DeployResult? get deploy => last?.deploy;

  List<StageStat> get stages => last?.result?.stages ?? const [];

  CacheStat? get cache => last?.result?.cache;

  int get durationMs => last?.result?.durationMs ?? 0;

  int get exportedTables => last?.result?.tables ?? 0;

  List<Issue> get issues => last?.issues ?? const [];

  /// `export` 参数：只带用户真正选中的过滤条件，`all` 始终显式送。
  Map<String, Object?> get exportParams => {
    if (table != null && table!.isNotEmpty) 'table': table,
    if (lang != null && lang!.isNotEmpty) 'lang': lang,
    'all': all,
  };

  void _note(String line) {
    logLines.add(line);
    if (logLines.length > logHistory) logLines.removeAt(0);
  }

  /// 发起导出。返回 false 表示没能启动（内核忙等），原状态保留给界面提示。
  /// [forced] 非空时先切换增量/强制全量模式；不传则沿用当前模式（状态层兼容入口）。
  Future<bool> startExport({bool? forced}) {
    if (forced != null) all = forced;
    return _run(
      kind: Methods.export,
      params: exportParams,
      onPayload: _acceptExport,
    );
  }

  /// 独立部署：导出不会顺带做它。
  Future<bool> startDeploy() => _run(
    kind: Methods.deploy,
    params: const {'forBuild': false},
    onPayload: _acceptDeploy,
  );

  Future<bool> _run({
    required String kind,
    required Map<String, Object?> params,
    required void Function(Object? payload) onPayload,
  }) async {
    if (!canStart) return false;
    final before = phase;
    final generation = ++_generation;
    phase = RunnerPhase.running;
    runningRequestId = null;
    progress = null;
    cancelState = null;
    error = null;
    _lastSeq = null;
    liveIssues.clear();
    logLines.clear();
    notifyListeners();
    try {
      final payload = await worker.query(
        kind,
        params: params,
        workspaceRoot: workspaceRoot,
      );
      if (!_isCurrent(generation)) return true;
      onPayload(payload);
      return true;
    } on WorkerRequestException catch (e) {
      if (!_isCurrent(generation)) return false;
      if (e.code == ProtocolErrorCodes.busy) {
        // 工作区被别的写任务占用：不是本次失败，状态原样保留，只给提示。
        phase = before;
        error = '内核忙等：${e.message}';
        _note('忙等：未提交任务');
        return false;
      }
      phase = RunnerPhase.failed;
      error = '${e.code}：${e.message}';
      last = RunSummary(
        kind: kind,
        phase: RunnerPhase.failed,
        message: e.message,
        issues: e.issues,
      );
      return false;
    } on Object catch (e) {
      if (!_isCurrent(generation)) return false;
      phase = RunnerPhase.failed;
      error = '$kind 失败：$e';
      return false;
    } finally {
      if (_isCurrent(generation)) {
        runningRequestId = null;
        progress = null;
        notifyListeners();
      }
    }
  }

  void _acceptExport(Object? payload) {
    final result = ExportResult.fromJson(payload! as Map<String, Object?>);
    final done = result.outcome == TaskOutcome.cancelled
        ? RunnerPhase.cancelled
        : RunnerPhase.succeeded;
    last = RunSummary(
      kind: Methods.export,
      phase: done,
      result: result,
      issues: result.issues,
    );
    phase = done;
    _note(
      '${result.outcome.wire}：${result.tables} 张表 · ${result.durationMs}ms'
      ' · 缓存命中 ${result.cache?.hits ?? 0} / 未命中 ${result.cache?.misses ?? 0}',
    );
  }

  void _acceptDeploy(Object? payload) {
    final result = DeployResult.fromJson(payload! as Map<String, Object?>);
    last = RunSummary(
      kind: Methods.deploy,
      phase: RunnerPhase.succeeded,
      deploy: result,
      message: result.unchanged ? '目标已是最新，未写入' : '已同步 ${result.synced} 个文件',
    );
    phase = RunnerPhase.succeeded;
    _note(last!.message!);
  }

  /// 取消当前写任务：只转达意图。终态若是成功，界面仍显示成功。
  Future<void> cancel() async {
    final target = runningRequestId;
    if (!running || target == null) return;
    try {
      final payload = await worker.query(
        Methods.cancel,
        params: {'targetRequestId': target},
        workspaceRoot: workspaceRoot,
      );
      cancelState = switch (payload) {
        final Map<String, Object?> map => '${map['state'] ?? ''}',
        final String text => text,
        _ => '',
      };
      _note('取消请求已转达内核（$cancelState）');
      notifyListeners();
    } on Object catch (e) {
      error = '取消失败：$e';
      notifyListeners();
    }
  }

  /// 连接断开：标为 `unknown`，并作废在途请求的后续回填（不自动重放写请求）。
  void markDisconnected() {
    if (!running) return;
    _generation++;
    phase = RunnerPhase.unknown;
    runningRequestId = null;
    progress = null;
    last = RunSummary(
      kind: last?.kind ?? Methods.export,
      phase: RunnerPhase.unknown,
      message: '连接已断开，任务终态未知；未自动重放写请求，请先查看工作区状态再重试',
    );
    _note('连接断开：终态未知，未自动重放');
    notifyListeners();
  }

  /// 转发 worker 事件：按任务归属与 seq 单调过滤，非运行期一律丢弃。
  void onEvent(Message message) {
    if (!running) return;
    var changed = false;
    switch (message) {
      case final ProgressEvent event:
        if (!_accept(event.requestId, event.seq)) break;
        progress = event;
        _note('${event.stage} ${event.done}/${event.total}');
        changed = true;
      case final IssueEvent event:
        if (!_accept(event.requestId, event.seq)) break;
        liveIssues.add(event);
        if (liveIssues.length > issueHistory) liveIssues.removeAt(0);
        _note('问题：${event.issue.message}');
        changed = true;
      case final ErrorMessage event:
        runningRequestId ??= event.requestId;
      default:
        break;
    }
    if (changed) notifyListeners();
  }

  /// 任务归属 + seq 单调：旧连接回声与乱序事件不进当前视图。
  bool _accept(int requestId, int seq) {
    runningRequestId ??= requestId;
    if (runningRequestId != requestId) return false;
    if (_lastSeq != null && seq <= _lastSeq!) return false;
    _lastSeq = seq;
    return true;
  }

  int _generation = 0;
  int? _lastSeq;

  bool _isCurrent(int generation) => generation == _generation;
}
