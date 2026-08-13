import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/log_entry.dart';
import 'settings_store.dart';

enum PanelStatus { stopped, starting, running, failed }

/// 管理 ct panel（Flask 子进程）：启动 / 停止 / 实时日志。
class PanelService extends ChangeNotifier {
  PanelService({required this.settings});

  final SettingsStore settings;

  PanelStatus status = PanelStatus.stopped;
  String? failureReason;
  final List<LogEntry> logs = [];

  Process? _process;
  bool _stopping = false;

  String get baseUrl => settings.baseUrl;

  /// 内置运行时路径：应用包随附的冻结 ct CLI。
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
      final candidate = File(
        '${exe.parent.parent.path}/Resources/runtime/ct',
      );
      return candidate.existsSync() ? candidate.path : null;
    }
    if (isWindows) {
      // <dir>\ct_launcher.exe → <dir>\runtime\ct.exe
      final candidate = File('${exe.parent.path}/runtime/ct.exe');
      return candidate.existsSync() ? candidate.path : null;
    }
    return null;
  }

  /// 按「内置优先 → 工具目录 CLI → venv python」顺序构造启动命令；
  /// 三者都不可用时返回 null（调用方负责报错）。
  @visibleForTesting
  static ({String executable, List<String> args})? buildLaunchCommand({
    required String? bundledCtPath,
    required String ctCliPath,
    required String pythonPath,
    required List<String> panelArgs,
  }) {
    if (bundledCtPath != null) {
      return (executable: bundledCtPath, args: ['panel', ...panelArgs]);
    }
    if (File(ctCliPath).existsSync()) {
      return (executable: ctCliPath, args: ['panel', ...panelArgs]);
    }
    if (File(pythonPath).existsSync()) {
      return (
        executable: pythonPath,
        args: ['-m', 'ct.cli', 'panel', ...panelArgs],
      );
    }
    return null;
  }

  void init() {
    _append(LogLevel.info, 'ct Launcher 就绪，点击开关启动面板服务');
  }

  Future<void> start() async {
    if (_process != null || status == PanelStatus.starting) return;
    _setStatus(PanelStatus.starting);
    _append(LogLevel.info, '启动面板服务…');

    final bundled = bundledCtPath;
    final launch = buildLaunchCommand(
      bundledCtPath: bundled,
      ctCliPath: settings.ctCliPath,
      pythonPath: settings.pythonPath,
      panelArgs: _panelArgs,
    );
    if (launch == null) {
      _fail(
        '找不到可用的 ct 运行时：\n'
        '应用包内缺少内置运行时（Resources/runtime/ct 或 runtime\\ct.exe），'
        '且工具目录未配置有效入口。\n'
        '请在设置页配置工具目录（含 .venv 的 ct 源码目录）。',
      );
      return;
    }

    try {
      // 禁用 Werkzeug/click 的 ANSI 颜色输出（日志面板不解析控制字符）
      final env = Map<String, String>.from(Platform.environment)
        ..['NO_COLOR'] = '1'
        ..['TERM'] = 'dumb';
      final proc = await Process.start(
        launch.executable,
        launch.args,
        workingDirectory: settings.toolDir.isNotEmpty
            ? settings.toolDir
            : settings.workspacePath,
        environment: env,
        runInShell: false,
      );
      _process = proc;
      _append(
        LogLevel.info,
        bundled != null
            ? '使用内置运行时启动 (PID ${proc.pid})：$bundled'
            : '使用工具目录运行时启动 (PID ${proc.pid})',
      );

      proc.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) => _onOutput(line));
      proc.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) => _onOutput(line, fromErr: true));
      unawaited(proc.exitCode.then(_onExit));
    } catch (e) {
      _fail('无法启动 Python 进程：$e');
    }
  }

  List<String> get _panelArgs => [
    '--root', settings.workspacePath,
    '--host', '127.0.0.1',
    '--port', '${settings.port}',
    '--no-browser',
  ];

  Future<void> stop() async {
    final proc = _process;
    if (proc == null) {
      if (status != PanelStatus.stopped) _setStatus(PanelStatus.stopped);
      return;
    }
    _stopping = true;
    _append(LogLevel.warn, '收到暂停指令，正在停止面板服务…');
    proc.kill(ProcessSignal.sigterm);
    // 等待退出，5 秒未退出则强杀
    try {
      await proc.exitCode.timeout(const Duration(seconds: 5));
    } on TimeoutException {
      proc.kill(ProcessSignal.sigkill);
      await proc.exitCode;
    }
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
      if (status == PanelStatus.starting) {
        _setStatus(PanelStatus.running);
        _append(LogLevel.info, '面板服务运行中：$baseUrl');
      }
    }
  }

  static final _ansiRe = RegExp(r'\x1B\[[0-9;]*[A-Za-z]');

  static String _stripAnsi(String input) => input.replaceAll(_ansiRe, '');

  Future<void> _onExit(int code) async {
    _process = null;
    if (_stopping) {
      _stopping = false;
      _append(LogLevel.info, 'ct panel 已退出 (PID 释放)，端口 ${settings.port} 已释放');
      _setStatus(PanelStatus.stopped);
      return;
    }
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
    notifyListeners();
  }

  void _append(LogLevel level, String message) {
    logs.add(LogEntry(level, message));
    if (logs.length > 500) logs.removeRange(0, logs.length - 500);
    notifyListeners();
  }

  void clearLogs() {
    logs.clear();
    notifyListeners();
  }

  String get logText => logs.map((e) => '${e.timestamp} ${e.message}').join('\n');

  @override
  void dispose() {
    _process?.kill(ProcessSignal.sigkill);
    super.dispose();
  }
}
