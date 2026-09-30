import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/log_entry.dart';
import 'settings_store.dart';

enum PanelStatus { stopped, starting, running, stopping, failed }

/// 管理 ct panel（原生子进程）：启动 / 停止 / 实时日志。
class PanelService extends ChangeNotifier {
  PanelService({required this.settings, this.onReady});

  final SettingsStore settings;
  final Future<void> Function(String url)? onReady;

  PanelStatus status = PanelStatus.stopped;
  String? failureReason;
  final List<LogEntry> logs = [];

  Process? _process;
  bool _stopping = false;
  bool _disposed = false;
  Future<void>? _starting;
  Future<void>? _stopFuture;
  bool _checkingReady = false;

  @visibleForTesting
  int? get processId => _process?.pid;

  String get baseUrl => settings.baseUrl;

  /// 内置运行时路径：应用包随附的原生 ct CLI。
  ///
  /// macOS：`.app/Contents/Resources/runtime/ct`
  /// Windows：可执行文件同级 `runtime\ct.exe`
  String? get bundledCtPath => resolveBundledCtPath(
    executablePath: Platform.resolvedExecutable,
    isMacOS: Platform.isMacOS,
    isWindows: Platform.isWindows,
  );

  /// 按平台布局解析内置运行时路径；仅当文件存在时返回。
  @visibleForTesting
  static String? resolveBundledCtPath({
    required String executablePath,
    required bool isMacOS,
    required bool isWindows,
  }) {
    final exe = File(executablePath);
    if (isMacOS) {
      // <app>.app/Contents/MacOS/<binary> → Contents/Resources/runtime/ct
      final candidate = File('${exe.parent.parent.path}/Resources/runtime/ct');
      return candidate.existsSync() ? candidate.path : null;
    }
    if (isWindows) {
      // <dir>\ct_launcher.exe → <dir>\runtime\ct.exe
      final candidate = File('${exe.parent.path}/runtime/ct.exe');
      return candidate.existsSync() ? candidate.path : null;
    }
    return null;
  }

  /// 内置优先，开发环境可明确指定原生可执行文件；不再回退 Python。
  @visibleForTesting
  static ({String executable, List<String> args})? buildLaunchCommand({
    required String? bundledCtPath,
    required String nativeRuntimePath,
    required List<String> panelArgs,
  }) {
    final path = bundledCtPath ?? nativeRuntimePath;
    if (path.isEmpty || !File(path).existsSync()) return null;
    return (executable: path, args: ['panel', ...panelArgs]);
  }

  void init() {
    _append(LogLevel.info, 'ct Launcher 就绪，点击开关启动面板服务');
  }

  Future<void> start() =>
      _starting ??= _start().whenComplete(() => _starting = null);

  Future<void> _start() async {
    if (_process != null || status == PanelStatus.starting) return;
    failureReason = null;
    _setStatus(PanelStatus.starting);
    _append(LogLevel.info, '启动面板服务…');

    final bundled = bundledCtPath;
    final launch = buildLaunchCommand(
      bundledCtPath: bundled,
      nativeRuntimePath: settings.nativeRuntimePath,
      panelArgs: _panelArgs,
    );
    if (launch == null) {
      _fail(
        '找不到可用的 ct 运行时：\n'
        '应用包内缺少内置运行时（Resources/runtime/ct 或 runtime\\ct.exe），'
        '且未配置有效原生可执行文件。\n'
        '请在设置页选择原生 ct 可执行文件。',
      );
      return;
    }

    try {
      // 禁用 ANSI 颜色输出（日志面板不解析控制字符）
      final env = Map<String, String>.from(Platform.environment)
        ..['NO_COLOR'] = '1'
        ..['TERM'] = 'dumb';
      final proc = await Process.start(
        launch.executable,
        launch.args,
        environment: env,
        runInShell: false,
      );
      _process = proc;
      _append(
        LogLevel.info,
        bundled != null
            ? '使用内置运行时启动 (PID ${proc.pid})：$bundled'
            : '使用外部原生运行时启动 (PID ${proc.pid})',
      );

      proc.stdout
          .transform(const Utf8Decoder(allowMalformed: true))
          .transform(const LineSplitter())
          .listen((line) => _onOutput(line));
      proc.stderr
          .transform(const Utf8Decoder(allowMalformed: true))
          .transform(const LineSplitter())
          .listen((line) => _onOutput(line, fromErr: true));
      unawaited(proc.exitCode.then(_onExit));
    } catch (e) {
      _fail('无法启动原生进程：$e');
    }
  }

  List<String> get _panelArgs => [
    '--root',
    settings.workspacePath,
    '--host',
    '127.0.0.1',
    '--port',
    '${settings.port}',
    '--no-browser',
    '--shutdown-on-stdin-eof',
  ];

  Future<void> stop() =>
      _stopFuture ??= _stop().whenComplete(() => _stopFuture = null);

  Future<void> _stop() async {
    await _starting;
    final proc = _process;
    if (proc == null) {
      if (status != PanelStatus.stopped) _setStatus(PanelStatus.stopped);
      return;
    }
    _stopping = true;
    _setStatus(PanelStatus.stopping);
    _append(LogLevel.warn, '正在安全停止面板，等待正在执行的写入完成…');
    // EOF 是跨平台关闭协议；服务等待当前请求与发布结束后退出。
    await proc.stdin.close();
    await proc.exitCode;
  }

  void _onOutput(String line, {bool fromErr = false}) {
    // 兜底清理残留的 ANSI 转义序列
    final text = _stripAnsi(line.trim());
    if (text.isEmpty) return;
    final lower = text.toLowerCase();
    final isError =
        fromErr &&
        (lower.contains('error') ||
            lower.contains('traceback') ||
            lower.contains('exception'));
    _append(isError ? LogLevel.error : LogLevel.info, text);
    if (!fromErr && (text.contains('面板已启动') || text.contains('已监听'))) {
      final proc = _process;
      if (status == PanelStatus.starting && !_checkingReady && proc != null) {
        _checkingReady = true;
        unawaited(_confirmReady(proc));
      }
    }
  }

  Future<void> _confirmReady(Process proc) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await client.getUrl(Uri.parse('$baseUrl/api/service'));
      final response = await request.close().timeout(
        const Duration(seconds: 5),
      );
      final body = await response
          .transform(utf8.decoder)
          .join()
          .timeout(const Duration(seconds: 5));
      final envelope = jsonDecode(body) as Map<String, dynamic>;
      if (response.statusCode != 200 ||
          envelope['ok'] != true ||
          envelope['data']['kernel'] != 'native') {
        throw const FormatException('就绪地址未提供原生服务');
      }
      if (_disposed || _process != proc || status != PanelStatus.starting) {
        return;
      }
      _setStatus(PanelStatus.running);
      _append(LogLevel.info, '面板服务运行中：$baseUrl');
      try {
        await onReady?.call(baseUrl);
      } catch (e) {
        _append(LogLevel.warn, '服务已就绪，但无法自动打开浏览器：$e');
      }
    } catch (e) {
      if (_process == proc && status == PanelStatus.starting) {
        _fail('无法确认原生服务就绪：$e');
        await proc.stdin.close();
      }
    } finally {
      client.close(force: true);
    }
  }

  static final _ansiRe = RegExp(r'\x1B\[[0-9;]*[A-Za-z]');

  static String _stripAnsi(String input) => input.replaceAll(_ansiRe, '');

  Future<void> _onExit(int code) async {
    _process = null;
    _checkingReady = false;
    if (_stopping) {
      _stopping = false;
      _append(LogLevel.info, 'ct panel 已退出 (PID 释放)，端口 ${settings.port} 已释放');
      _setStatus(PanelStatus.stopped);
      return;
    }
    if (status == PanelStatus.failed) return;
    if (status == PanelStatus.starting) {
      _fail('服务启动失败（退出码 $code）');
    } else {
      _fail('服务意外退出（退出码 $code）');
    }
  }

  void _fail(String reason) {
    failureReason = reason;
    _append(LogLevel.error, reason);
    _setStatus(PanelStatus.failed);
  }

  void _setStatus(PanelStatus next) {
    status = next;
    if (!_disposed) notifyListeners();
  }

  void _append(LogLevel level, String message) {
    logs.add(LogEntry(level, message));
    if (logs.length > 500) logs.removeRange(0, logs.length - 500);
    if (!_disposed) notifyListeners();
  }

  void clearLogs() {
    logs.clear();
    if (!_disposed) notifyListeners();
  }

  String get logText =>
      logs.map((e) => '${e.timestamp} ${e.message}').join('\n');

  @override
  void dispose() {
    _disposed = true;
    unawaited(stop());
    super.dispose();
  }
}
