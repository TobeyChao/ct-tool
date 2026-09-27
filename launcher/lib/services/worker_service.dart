import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/log_entry.dart';
import 'native_runtime.dart';
import 'protocol/protocol.dart';
import 'settings_store.dart';

/// worker 连接状态。
enum WorkerStatus { stopped, starting, ready, failed }

/// 协议支持的 v1 版本（与 `ct_protocol::version` 同源）。
const int kWorkerProtocolVersion = 1;

/// 请求失败：携带结构化错误码与定位明细，不解析人类日志。
final class WorkerRequestException implements Exception {
  WorkerRequestException(this.error);

  final ErrorBody error;

  String get code => error.code;
  String get message => error.message;
  List<Issue> get issues => error.issues;

  @override
  String toString() =>
      '$code: ${error.message}${issues.isEmpty ? '' : '（${issues.length} 条明细）'}';
}

/// 建立传输的工厂；生产用 [StdioWorkerTransport.start]，测试注入假传输。
typedef WorkerConnector = Future<WorkerTransport> Function();

/// 内核只读入口的最小抽象：真实 [WorkerService] 与测试替身共用同一形状。
abstract interface class KernelGateway {
  /// 发一次只读请求并等终态 payload。
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  });

  /// 最近一次消息的工作区归属 id。
  String? get lastWorkspaceId;

  /// 连接状态。
  WorkerStatus get status;

  /// 不可用原因（未连接或协商失败时给界面直接展示）。
  String? get failureReason;
}

/// stdio NDJSON 传输：进程生命周期、stdout 协议流与 stderr 诊断分离。
final class StdioWorkerTransport implements WorkerTransport {
  StdioWorkerTransport._(this._process) {
    _process.stderr
        .transform(const Utf8Decoder(allowMalformed: true))
        .transform(const LineSplitter())
        .listen((line) {
          final text = line.trim();
          if (text.isNotEmpty) stderrLines.add(text);
        });
  }

  static Future<StdioWorkerTransport> start({
    required String executable,
    List<String> arguments = const ['worker'],
    String? workingDirectory,
  }) async {
    final process = await Process.start(
      executable,
      arguments,
      workingDirectory: workingDirectory,
    );
    return StdioWorkerTransport._(process);
  }

  final Process _process;

  /// worker 的 stderr 行（不属于协议；仅用于诊断与「错误架构」类失败定位）。
  final List<String> stderrLines = [];

  Stream<Message>? _messages;

  @override
  Stream<Message> get messages => _messages ??= NdjsonCodec()
      .decodeStream(_process.stdout)
      .asBroadcastStream();

  @override
  void send(Message message) {
    _process.stdin.add(utf8.encode(NdjsonCodec().encodeLine(message)));
  }

  /// 关闭：先冲掉待发，再关 stdin（v1.md §6：shutdown 后 worker 会读到 EOF 才退出），
  /// 等待正在执行的发布收尾，不以超时强杀代替安全关闭。
  @override
  Future<void> close() async {
    try {
      await _process.stdin.flush();
    } catch (_) {
      // 管道可能已被对端关闭
    }
    try {
      await _process.stdin.close();
    } catch (_) {}
    await _process.exitCode;
  }

  Future<int> get exitCode => _process.exitCode;
}

/// `ct worker` 客户端：握手、请求关联、事件转发、写入口门禁与安全关闭
/// （native-flutter-workbench 任务 2.1）。
class WorkerService extends ChangeNotifier implements KernelGateway {
  WorkerService({required this.settings, WorkerConnector? connect})
    : _connectOverride = connect;

  final SettingsStore settings;
  final WorkerConnector? _connectOverride;

  @override
  WorkerStatus status = WorkerStatus.stopped;
  @override
  String? failureReason;
  NativeRuntime? runtime;

  /// 最近一次消息携带的 workspaceId（内核按工作区归属分配，切换后必然变化）。
  @override
  String? get lastWorkspaceId => _lastWorkspaceId;
  String? _lastWorkspaceId;

  /// worker 握手回显的核心版本与能力表。
  String coreVersion = '';
  int protocolVersion = 0;
  List<String> capabilities = const [];

  /// 有界日志缓冲（与面板旧行为一致，上限 500 条）。
  final List<LogEntry> logs = [];
  static const int logLimit = 500;

  final StreamController<Message> _events =
      StreamController<Message>.broadcast();
  StreamSubscription<Message>? _sub;
  StdioWorkerTransport? _stdio;
  WorkerTransport? _transport;
  final Map<int, Completer<Message>> _pending = {};
  final Map<int, String> _pendingMethods = {};
  final Set<int> _sentIds = {};
  int _nextRequestId = 0;
  bool _stopping = false;
  Future<void>? _starting;
  Future<void>? _stopFuture;

  /// progress/log/issue 事件流；写方法终态也进入这里以驱动任务/历史刷新。
  Stream<Message> get events => _events.stream;

  bool get isRunning => status == WorkerStatus.ready;

  /// 协议协商是否成功；不兼容时所有写入口必须禁用。
  bool get protocolCompatible =>
      protocolVersion == kWorkerProtocolVersion && capabilities.isNotEmpty;

  /// 写入口是否应被禁用，以及原因（供按钮 disabled + 提示复用）。
  String? writeBlockReason({String? method}) {
    if (status != WorkerStatus.ready) return '内核未就绪（当前状态 $status）';
    if (!protocolCompatible) {
      return 'worker 协议版本不兼容（回显 $protocolVersion，要求 $kWorkerProtocolVersion），写入口已禁用';
    }
    if (method != null && method.isNotEmpty && !capabilities.contains(method)) {
      return '内核能力缺失：$method，写入口已禁用';
    }
    return null;
  }

  /// 运行时发现 + 启动 + 握手；失败只报可操作原因，绝不回退 Python。
  Future<void> start({String? workspaceRoot}) => _starting ??= _start(
    workspaceRoot: workspaceRoot,
  ).whenComplete(() => _starting = null);

  Future<void> _start({String? workspaceRoot}) async {
    if (status == WorkerStatus.starting || status == WorkerStatus.ready) return;
    _setStatus(WorkerStatus.starting);
    failureReason = null;
    _hello = Completer<Hello>();
    _lastWorkspaceId = null;
    _append(LogLevel.info, '启动原生内核 worker…');

    final discovered = await NativeRuntimeLocator.discover(
      executablePath: Platform.resolvedExecutable,
      explicitPath: settings.runtimePath,
    );
    if (discovered == null) {
      _fail('找不到可用的原生运行时：请安装带运行时的桌面包，或在设置里指定 ct 可执行文件路径。（不使用 Python 回退）');
      return;
    }
    runtime = discovered;
    for (final note in discovered.reasons) {
      _append(LogLevel.info, note);
    }

    try {
      final transport = _connectOverride != null
          ? await _connectOverride()
          : await StdioWorkerTransport.start(
              executable: discovered.path,
              // 空字符串会被 CreateProcess 判为非法目录：未绑定工作区时继承当前目录即可。
              workingDirectory: _orNull(
                workspaceRoot ?? settings.workspacePath,
              ),
            );
      await _attach(transport);
    } catch (e) {
      // 错误架构 / 权限不足等系统级失败在此落地：进程起不来就是可诊断错误。
      _fail('无法启动原生运行时 ${discovered.path}：$e');
      final err = _stdio?.stderrLines;
      if (err != null) {
        for (final line in err.take(5)) {
          _append(LogLevel.error, 'worker stderr: $line');
        }
      }
    }
  }

  Future<void> _attach(WorkerTransport transport) async {
    _transport = transport;
    if (transport is StdioWorkerTransport) _stdio = transport;
    _sub = transport.messages.listen(
      _onMessage,
      onDone: _onClosed,
      onError: (Object e) => _fail('协议流异常：$e'),
    );
    transport.send(
      const Hello(
        protocolVersion: kWorkerProtocolVersion,
        coreVersion: 'launcher',
        capabilities: [],
      ),
    );
    final reply = await _awaitHello();
    if (reply == null) {
      if (failureReason == null) _fail('握手超时：worker 未回 hello');
      await _detach();
      return;
    }
    if (status != WorkerStatus.starting) {
      // 例如协议版本不兼容已被 _fail 关闭：只读可见，写入口保持禁用。
      await _detach();
      return;
    }
    _setStatus(WorkerStatus.ready);
    _append(
      LogLevel.info,
      'worker 就绪（core ${reply.coreVersion}，协议 ${reply.protocolVersion}，'
      '能力 ${reply.capabilities.length} 项）',
    );
  }

  /// 等 worker 的 hello；超时或对端先报错都返回 null，由调用方落原因。
  Future<Hello?> _awaitHello() async {
    final waiting = _hello;
    if (waiting == null) return null;
    try {
      return await waiting.future.timeout(const Duration(seconds: 15));
    } on TimeoutException {
      return null;
    }
  }

  /// 断开当前传输：终态未知的请求统一按连接断开处理。
  Future<void> _detach() async {
    await _sub?.cancel();
    _sub = null;
    _transport = null;
    _stdio = null;
    _failPending();
  }

  void _failPending() {
    for (final completer in _pending.values) {
      if (!completer.isCompleted) {
        completer.complete(
          ErrorMessage(
            error: ErrorBody(
              code: 'transport-closed',
              message: 'worker 连接已断开，请求终态未知',
            ),
          ),
        );
      }
    }
    _pending.clear();
    _pendingMethods.clear();
  }

  /// 本次握手的 hello 投递点；每次 [start] 重建，避免重启后卡在旧 completer。
  Completer<Hello>? _hello;

  void _onMessage(Message message) {
    _noteWorkspaceId(message);
    switch (message) {
      case final Hello hello:
        coreVersion = hello.coreVersion;
        protocolVersion = hello.protocolVersion;
        capabilities = hello.capabilities;
        if (_hello case final waiting? when !waiting.isCompleted) {
          waiting.complete(hello);
        }
        if (hello.protocolVersion != kWorkerProtocolVersion) {
          _fail(
            'worker 协议版本不兼容：对端 ${hello.protocolVersion}，本机要求 $kWorkerProtocolVersion；写入口已禁用',
          );
        }
      case final LogEvent log:
        _append(_levelOf(log.level), '[${log.module}] ${log.message}');
        _events.add(log);
      case final ProgressEvent progress:
        _events.add(progress);
      case final IssueEvent issue:
        _append(LogLevel.warn, '问题：${issue.issue.message}');
        _events.add(issue);
      case final ResultMessage result:
        // 只广播写方法终态；只读终态不得再次触发刷新，否则会形成请求回环。
        if (Methods.write.contains(_pendingMethods[result.requestId])) {
          _events.add(result);
        }
        _settle(result.requestId, result);
      case final ErrorMessage error:
        final id = error.requestId;
        if (id == null) {
          // 连接级错误：没有 requestId，只能整体上报。
          _events.add(error);
          _fail('连接级协议错误：${error.error.code} ${error.error.message}');
          return;
        }
        if (Methods.write.contains(_pendingMethods[id])) {
          _events.add(error);
        }
        _settle(id, error);
      case Request():
      // worker 不会回发 request；忽略以保证前向兼容。
    }
  }

  /// 去掉空路径（含纯空白），供子进程 workingDirectory 使用。
  static String? _orNull(String path) {
    final trimmed = path.trim();
    return trimmed.isEmpty ? null : trimmed;
  }

  /// 从任意带 workspaceId 的消息里记录归属；旧工作区的迟到消息由上层据此丢弃。
  void _noteWorkspaceId(Message message) {
    final id = switch (message) {
      final LogEvent e => e.workspaceId,
      final ProgressEvent e => e.workspaceId,
      final IssueEvent e => e.workspaceId,
      final ResultMessage e => e.workspaceId,
      final ErrorMessage e => e.workspaceId,
      _ => null,
    };
    if (id != null) _lastWorkspaceId = id;
  }

  LogLevel _levelOf(String level) => switch (level.toLowerCase()) {
    'error' => LogLevel.error,
    'warn' || 'warning' => LogLevel.warn,
    _ => LogLevel.info,
  };

  void _settle(int requestId, Message message) {
    _pendingMethods.remove(requestId);
    final completer = _pending.remove(requestId);
    if (completer != null && !completer.isCompleted) {
      completer.complete(message);
    }
  }

  int _newRequestId() {
    int id;
    do {
      id = ++_nextRequestId;
    } while (_sentIds.contains(id));
    _sentIds.add(id);
    return id;
  }

  /// 发一条请求并等终态；返回 result.payload，失败抛 [WorkerRequestException]。
  Future<Object?> request(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
    Duration? timeout,
  }) async {
    final transport = _transport;
    if (transport == null || status != WorkerStatus.ready) {
      throw StateError('worker 未就绪');
    }
    final id = _newRequestId();
    final completer = Completer<Message>();
    _pending[id] = completer;
    _pendingMethods[id] = method;
    transport.send(
      Request(
        requestId: id,
        method: method,
        workspaceRoot: workspaceRoot ?? settings.workspacePath,
        params: params,
      ),
    );
    final future = timeout == null
        ? completer.future
        : completer.future.timeout(
            timeout,
            onTimeout: () => ErrorMessage(
              requestId: id,
              error: ErrorBody(
                code: 'client-timeout',
                message: '$method 在 $timeout 内没有终态',
              ),
            ),
          );
    final reply = await future;
    if (reply is ErrorMessage) throw WorkerRequestException(reply.error);
    return (reply as ResultMessage).payload;
  }

  /// 只读请求：不受写入口门禁影响。
  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) => request(method, params: params, workspaceRoot: workspaceRoot);

  /// 取消正在跑的任务（终态仍以 result.outcome == cancelled 表达）。
  Future<void> cancel(int requestId) async {
    final transport = _transport;
    if (transport == null) return;
    transport.send(
      Request(
        requestId: _newRequestId(),
        method: Methods.cancel,
        workspaceRoot: settings.workspacePath,
        params: {'targetRequestId': requestId},
      ),
    );
  }

  /// 安全关闭：shutdown 请求 → 关 stdin → 等发布完成与进程退出。
  /// 启动中退出和重复退出都等待同一次关闭，不遗留晚启动的子进程。
  Future<void> stop() =>
      _stopFuture ??= _stop().whenComplete(() => _stopFuture = null);

  Future<void> _stop() async {
    await _starting;
    final transport = _transport;
    if (transport == null) {
      if (status != WorkerStatus.stopped) _setStatus(WorkerStatus.stopped);
      return;
    }
    _stopping = true;
    _append(LogLevel.info, '正在关闭 worker…');
    try {
      await request(Methods.shutdown, timeout: const Duration(seconds: 5));
    } catch (e) {
      _append(LogLevel.warn, 'shutdown 未得到终态（按关闭处理）：$e');
    }
    await transport.close();
    await _sub?.cancel();
    _sub = null;
    _transport = null;
    _stdio = null;
    _pending.clear();
    _hello = null;
    _setStatus(WorkerStatus.stopped);
    _stopping = false;
  }

  void _onClosed() {
    if (_stopping) return;
    _failPending();
    if (status == WorkerStatus.ready || status == WorkerStatus.starting) {
      _fail('worker 进程已退出');
    }
  }

  void _fail(String reason) {
    failureReason = reason;
    _setStatus(WorkerStatus.failed);
    _append(LogLevel.error, reason);
  }

  void _setStatus(WorkerStatus next) {
    status = next;
    notifyListeners();
  }

  void _append(LogLevel level, String message) {
    logs.add(LogEntry(level, message));
    if (logs.length > logLimit) logs.removeRange(0, logs.length - logLimit);
    notifyListeners();
  }

  @override
  void dispose() {
    _sub?.cancel();
    _events.close();
    super.dispose();
  }
}
