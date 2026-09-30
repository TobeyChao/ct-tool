import 'dart:async';
import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'services/settings_store.dart';
import 'services/exit_guard.dart';
import 'services/exit_coordinator.dart';
import 'services/tray_service.dart';
import 'services/protocol/protocol.dart';
import 'services/worker_service.dart';
import 'state/desktop_state.dart';
import 'state/draft_store.dart';
import 'state/export_runner.dart';
import 'state/template_service.dart';
import 'state/translation_repository.dart';
import 'state/workbench_repository.dart';
import 'theme.dart';
import 'ui/widgets/status_badge.dart';
import 'ui/workbench/workbench_models.dart';
import 'ui/workbench/workbench_screen.dart';

/// 应用外壳：原生工作台（`ct worker`）+ 托盘 + 窗口生命周期。
///
/// 不再启动任何面板服务或解释器：内核是单个原生二进制，界面数据全部经
/// [WorkbenchRepository] 走 NDJSON 协议（任务 2.3/2.4）。
class LauncherApp extends StatefulWidget {
  const LauncherApp({super.key, required this.settings});

  final SettingsStore settings;

  @override
  State<LauncherApp> createState() => _LauncherAppState();
}

class _LauncherAppState extends State<LauncherApp> with WindowListener {
  late final WorkerService _worker;
  late final WorkbenchRepository _repo;
  late final DesktopStateRepository _desktop;

  /// 导出运行器（任务 4.4/4.6）：与工作区一一对应，断连时标为终态未知。
  ExportRunner? _runner;

  /// 翻译页数据源（任务 4.1-4.3）：筛选、分页与清理全部由内核执行。
  TemplateService? _template;

  late final TranslationRepository _translations;

  StreamSubscription<Message>? _eventSub;
  late final TrayService _tray;
  late final AppLifecycleListener _lifecycleListener;
  late final ExitCoordinator _exitCoordinator;
  final _navigatorKey = GlobalKey<NavigatorState>();
  Future<void>? _workspaceFuture;
  Future<void>? _quitFuture;
  String? _workspaceFailure;
  bool _windowMaximized = false;

  @override
  void initState() {
    super.initState();
    _worker = WorkerService(settings: widget.settings);
    _repo = WorkbenchRepository(worker: _worker, store: DraftStore());
    _desktop = DesktopStateRepository(worker: _worker);
    _translations = TranslationRepository(worker: _worker);
    // 实时事件转发给桌面状态与运行器：只接受当前工作区的归属，写任务终态后自动刷新任务/历史。
    _eventSub = _worker.events.listen(_onWorkerEvent);
    _tray = TrayService(
      worker: _worker,
      onQuit: _requestExit,
      onShowWindow: _reveal,
      onReload: () => _openWorkspace(force: true),
    );
    _exitCoordinator = ExitCoordinator(
      freezeEditing: _repo.freezeDraftEditing,
      unfreezeEditing: _repo.unfreezeDraftEditing,
      decide: () async {
        await _workspaceFuture;
        return _askExit();
      },
      flushDraft: _repo.flushDraft,
      retryDraft: _repo.persistDraft,
      discardDraft: _repo.discardDraftAndPersist,
      onPersistenceFailure: () {
        final dialogContext = _navigatorKey.currentContext;
        if (!mounted || dialogContext == null) {
          return Future.value(ExitPersistenceDecision.stay);
        }
        return confirmExitPersistenceFailure(dialogContext);
      },
      stopWorker: () async {
        _runner?.markDisconnected();
        await _worker.stop();
      },
    );
    // Cmd+Q / Dock 共用确认与 flush，但由平台完成进程退出。
    _lifecycleListener = AppLifecycleListener(
      onExitRequested: () async {
        final decision = await _exitCoordinator.request();
        if (decision == ExitDecision.hideToTray) await _hideToTray();
        return decision == ExitDecision.exitNow
            ? AppExitResponse.exit
            : AppExitResponse.cancel;
      },
    );
    windowManager.addListener(this);
    unawaited(_syncWindowMaximized());
    _tray.init();
    _worker.addListener(_onWorkerChanged);
    _openWorkspace();
  }

  /// 同一条事件流喂两处：桌面状态负责日志/任务，导出运行器负责 progress/issue。
  void _onWorkerEvent(Message message) {
    _desktop.onWorkerEvent(message);
    _runner?.onEvent(message);
  }

  void _onWorkerChanged() {
    // 连接不可用而写任务还在跑：标为终态未知，明确不自动重放（任务 4.6）。
    if (_worker.status != WorkerStatus.ready) _runner?.markDisconnected();
    if (mounted) setState(() {});
  }

  Future<void> _syncWindowMaximized() async {
    try {
      final maximized = await windowManager.isMaximized();
      if (mounted && maximized != _windowMaximized) {
        setState(() => _windowMaximized = maximized);
      }
    } catch (_) {
      // 平台窗口尚未就绪时保持默认值，后续由窗口事件同步。
    }
  }

  Future<void> _minimizeWindow() => windowManager.minimize();

  Future<void> _toggleWindowMaximized() async {
    if (_windowMaximized) {
      await windowManager.unmaximize();
    } else {
      await windowManager.maximize();
    }
  }

  Future<void> _closeWindow() => windowManager.close();

  /// 壳层操作串行：退出冻结后不接受新的切换、重载或运行时修改。
  Future<void> _workspaceOperation(Future<void> Function() operation) {
    if (_exitCoordinator.pending || _repo.editingFrozen) {
      return Future.value();
    }
    final pending = _workspaceFuture;
    if (pending != null) return pending;
    final result = Completer<void>();
    _workspaceFuture = result.future;
    if (mounted) setState(() => _workspaceFailure = null);
    unawaited(() async {
      try {
        await operation();
      } catch (error) {
        _workspaceFailure = '工作区操作失败：$error';
      } finally {
        _workspaceFuture = null;
        if (mounted) setState(() {});
        result.complete();
      }
    }());
    return result.future;
  }

  /// 启动/重连先排空草稿，避免重载清空尚未落盘的内存历史。
  Future<void> _openWorkspace({
    bool force = false,
    String? runtimePath,
    bool useInferredRuntime = false,
  }) => _workspaceOperation(() async {
    final root = _repo.workspaceRoot.isNotEmpty
        ? _repo.workspaceRoot
        : widget.settings.workspacePath;
    _repo.freezeDraftEditing();
    try {
      if (!await _repo.flushDraft()) return;
      if (useInferredRuntime) {
        await widget.settings.useInferredRuntimePath();
      }
      if (runtimePath != null) {
        await widget.settings.setRuntimePath(runtimePath);
      }
      if (force && _worker.status != WorkerStatus.stopped) {
        await _worker.stop();
      }
      if (root.isNotEmpty) await _worker.start(workspaceRoot: root);
    } finally {
      _repo.unfreezeDraftEditing();
    }
    if (_exitCoordinator.pending) return;
    if (!await _repo.switchWorkspace(root)) return;
    await _bindWorkspace(root);
  });

  Future<void> _changeWorkspace(String root) => _workspaceOperation(() async {
    // 未绑定时也需要可用的 worker 才能读取候选工作区。
    await _worker.start(workspaceRoot: _repo.workspaceRoot);
    if (_exitCoordinator.pending) return;
    var accepted = false;
    try {
      await switchShellWorkspace(
        root,
        switchWorkspace: _repo.switchWorkspace,
        onAccepted: () async {
          accepted = true;
          _repo.freezeDraftEditing();
          // B 已生效：在偏好/连接等待期间也不能留下 A 的写入口。
          _rebuildRunner('');
          await _desktop.bind('');
          await _translations.bind('');
        },
        persistWorkspace: widget.settings.setWorkspacePath,
        connectWorkspace: (root) async {
          await _worker.stop();
          if (root.isNotEmpty) {
            await _worker.start(workspaceRoot: root);
            if (_worker.status != WorkerStatus.ready) {
              throw StateError(_worker.failureReason ?? '内核连接失败');
            }
          }
          await _bindWorkspace(root);
        },
        onFailure: (stage, error) {
          final message = stage == 'preferences'
              ? '工作区已切换，但偏好未保存：$error'
              : '工作区已切换，但内核连接未完成：$error';
          _workspaceFailure = [
            _workspaceFailure,
            message,
          ].whereType<String>().join('；');
        },
      );
    } finally {
      if (accepted) _repo.unfreezeDraftEditing();
    }
  });

  Future<void> _bindWorkspace(String root) async {
    // 先刷新运行器，日志和翻译的加载失败不能把导出页卡在 MOCK。
    _rebuildRunner(root);
    await _desktop.bind(root);
    await _translations.bind(root);
  }

  /// 运行器随工作区重建：上一个工作区的运行状态不带进新连接。
  void _rebuildRunner(String root) {
    _runner?.dispose();
    _runner = root.isEmpty
        ? null
        : ExportRunner(worker: _worker, workspaceRoot: root);
    _template?.dispose();
    _template = root.isEmpty
        ? null
        : TemplateService(worker: _worker, workspaceRoot: root);
    if (mounted) setState(() {});
  }

  Future<void> _reveal() async {
    await windowManager.setSkipTaskbar(false);
    await windowManager.show();
    await windowManager.focus();
  }

  Future<void> _quit() => _quitFuture ??= () async {
    await windowManager.destroy();
    exit(0);
  }();

  /// 窗口/设置/托盘适配：只有协调器成功落盘并停止 worker 后才销毁窗口。
  Future<void> _requestExit() async {
    switch (await _exitCoordinator.request()) {
      case ExitDecision.stay:
        return;
      case ExitDecision.hideToTray:
        await _hideToTray();
      case ExitDecision.exitNow:
        await _quit();
    }
  }

  /// 守卫的问题本身：没有草稿也没有在跑任务时直接放行，不打扰。
  Future<ExitDecision> _askExit() {
    final dialogContext = _navigatorKey.currentContext;
    if (!mounted || dialogContext == null) {
      return Future.value(ExitDecision.stay);
    }
    return confirmExit(
      dialogContext,
      hasDraft: _repo.hasDraftHistory,
      runningTask: _runner?.running ?? false,
      draftNotPersisted: !_repo.draftPersisted,
      trayResident: widget.settings.trayResident,
    );
  }

  /// 托盘常驻：隐藏窗口并从任务栏消失（对齐 FlClash 顺序）。
  Future<void> _hideToTray() async {
    await windowManager.hide();
    try {
      await windowManager.setSkipTaskbar(true);
    } catch (_) {
      // 个别平台不支持跳过任务栏时忽略
    }
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    _lifecycleListener.dispose();
    _worker.removeListener(_onWorkerChanged);
    _tray.dispose();
    _eventSub?.cancel();
    _desktop.dispose();
    _translations.dispose();
    _template?.dispose();
    _runner?.dispose();
    _repo.dispose();
    _worker.dispose();
    super.dispose();
  }

  @override
  void onWindowClose() async {
    if (widget.settings.trayResident) {
      // 关闭窗口只是隐藏：不动数据、不杀 worker，因此不弹确认。
      await _hideToTray();
      return;
    }
    // 不常驻时关闭窗口等于退出：必须走同一个守卫。
    await _requestExit();
  }

  @override
  void onWindowMaximize() {
    if (mounted) setState(() => _windowMaximized = true);
  }

  @override
  void onWindowUnmaximize() {
    if (mounted) setState(() => _windowMaximized = false);
  }

  @override
  Widget build(BuildContext context) {
    final banner = _bannerLabel();
    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'ct 工作台',
      theme: buildCtTheme(),
      debugShowCheckedModeBanner: false,
      home: AbsorbPointer(
        absorbing: _workspaceFuture != null,
        child: ExcludeFocus(
          excluding: _workspaceFuture != null,
          child: WorkbenchScreen(
            data: _repo,
            refresh: Listenable.merge([_repo, _worker, widget.settings]),
            desktop: _desktop,
            settings: widget.settings,
            onWorkspaceChanged: _changeWorkspace,
            onRuntimeChanged: (path) =>
                _openWorkspace(force: true, runtimePath: path),
            onUseInferredRuntime: () =>
                _openWorkspace(force: true, useInferredRuntime: true),
            onReloadWorkspace: () => _openWorkspace(force: true),
            onExitRequested: _requestExit,
            kernelSummary: _kernelSummary(),
            draft: _repo,
            runner: _runner,
            translations: _translations,
            template: _template,
            writeBlockReason: _workspaceFuture != null
                ? '正在切换或重连工作区'
                : _worker.writeBlockReason(method: Methods.export),
            bannerLabel: banner,
            bannerTone: _workspaceFailure != null
                ? CtBadgeTone.danger
                : switch (_worker.status) {
                    WorkerStatus.ready => CtBadgeTone.ok,
                    WorkerStatus.starting => CtBadgeTone.busy,
                    WorkerStatus.failed => CtBadgeTone.danger,
                    WorkerStatus.stopped => CtBadgeTone.warn,
                  },
            workspaceKey: _repo.workspaceRoot.isEmpty
                ? 'unbound'
                : _repo.workspaceRoot,
            showDesktopTitleBar: Platform.isWindows || Platform.isMacOS,
            windowMaximized: _windowMaximized,
            showWindowControls: Platform.isWindows,
            titleBarLeadingInset: Platform.isMacOS ? 80 : 0,
            onWindowMinimize: _minimizeWindow,
            onWindowToggleMaximize: _toggleWindowMaximized,
            onWindowClose: _closeWindow,
          ),
        ),
      ),
    );
  }

  /// 设置模块里的内核面板：来源、路径、状态与失败原因。
  List<String> _kernelSummary() {
    final runtime = _worker.runtime;
    final lines = <String>[
      _worker.status == WorkerStatus.ready
          ? '内核状态：已连接（core ${_worker.coreVersion}）'
          : '内核状态：${_worker.status.name}',
    ];
    // 关于对话框直接读这份清单：协议与能力数必须是握手回显的真实值。
    lines.add(
      'worker 协议版本：${_worker.protocolVersion}'
      '（要求 $kWorkerProtocolVersion，'
      '${_worker.protocolCompatible ? '兼容' : '不兼容：写入口已禁用'}）',
    );
    lines.add('内核能力：${_worker.capabilities.length} 项（握手回显）');
    if (runtime != null) {
      lines.add(
        runtime.isBundled
            ? '运行时来源：应用包内置 ${runtime.path}'
            : '运行时来源：显式配置 ${runtime.path}',
      );
    } else if (_worker.status != WorkerStatus.ready) {
      lines.add('运行时来源：未找到（安装内置运行时的桌面包，或在上方指定开发期 ct 可执行文件）');
    }
    final failure = _worker.failureReason;
    if (failure != null) lines.add('最近失败：$failure');
    if (_workspaceFailure != null) lines.add(_workspaceFailure!);
    return lines;
  }

  String _bannerLabel() {
    if (_workspaceFailure != null) return _workspaceFailure!;
    if (_workspaceFuture != null) return '正在切换或重连工作区…';
    if (_repo.workspaceRoot.isEmpty) return '尚未绑定工作区 · 在「设置」里选择配表工作区';
    return switch (_worker.status) {
      WorkerStatus.ready => '原生内核已连接 · ${_worker.coreVersion} · 可保存、导出',
      WorkerStatus.starting => '正在连接原生内核…',
      WorkerStatus.failed => '内核未就绪：${_worker.failureReason ?? '未知原因'}',
      WorkerStatus.stopped => '内核已断开',
    };
  }
}

/// 仓库确认出站草稿安全后，才提交偏好并重连对应 worker。
Future<bool> switchShellWorkspace(
  String root, {
  required Future<bool> Function(String) switchWorkspace,
  required Future<void> Function(String) persistWorkspace,
  required Future<void> Function(String) connectWorkspace,
  Future<void> Function()? onAccepted,
  void Function(String stage, Object error)? onFailure,
}) async {
  if (!await switchWorkspace(root)) return false;
  await onAccepted?.call();
  Object? failure;
  StackTrace? failureStack;
  try {
    await persistWorkspace(root);
  } catch (error, stack) {
    failure = error;
    failureStack = stack;
    onFailure?.call('preferences', error);
  }
  // Repository already displays B. Even a preference error must finish binding
  // B instead of leaving A's write services attached to the new view.
  try {
    await connectWorkspace(root);
  } catch (error, stack) {
    failure ??= error;
    failureStack ??= stack;
    onFailure?.call('connection', error);
  }
  if (failure != null) {
    if (onFailure == null) Error.throwWithStackTrace(failure, failureStack!);
    return false;
  }
  return true;
}

/// 便于测试断言：工作台是否仍在用样板数据。
bool isSampleData(WorkbenchData data) => data.sampleData;
