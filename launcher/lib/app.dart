import 'dart:async';
import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'services/settings_store.dart';
import 'services/exit_guard.dart';
import 'services/tray_service.dart';
import 'services/protocol/protocol.dart';
import 'services/worker_service.dart';
import 'state/desktop_state.dart';
import 'state/draft_store.dart';
import 'state/export_runner.dart';
import 'state/validate_runner.dart';
import 'state/template_service.dart';
import 'state/translation_repository.dart';
import 'state/workbench_repository.dart';
import 'theme.dart';
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
  ValidateRunner? _validate;

  /// 翻译页数据源（任务 4.1-4.3）：筛选、分页与清理全部由内核执行。
  TemplateService? _template;

  late final TranslationRepository _translations;

  /// 导出过滤用的语言清单（内核 `i18n.status`）。
  List<String> _exportLanguages = const [];

  StreamSubscription<Message>? _eventSub;
  late final TrayService _tray;
  late final AppLifecycleListener _lifecycleListener;
  Future<void>? _shutdownFuture;
  bool _exiting = false;

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
    // Cmd+Q / Dock 退出：先过退出守卫，再给 worker 发 shutdown，避免留下未完成的写任务。
    _lifecycleListener = AppLifecycleListener(
      onExitRequested: () async {
        if (await _askExit() == ExitDecision.stay) {
          return AppExitResponse.cancel;
        }
        await _shutdown();
        return AppExitResponse.exit;
      },
    );
    windowManager.addListener(this);
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

  /// 启动/重连内核并加载当前工作区。[force] 时先停旧连接再起。
  Future<void> _openWorkspace({bool force = false}) async {
    final root = widget.settings.workspacePath;
    if (root.isEmpty) {
      await _repo.switchWorkspace('');
      _desktop.bind('');
      await _translations.bind('');
      _rebuildRunner('');
      return;
    }
    if (force && _worker.status != WorkerStatus.stopped) {
      await _worker.stop();
    }
    await _worker.start(workspaceRoot: root);
    await _repo.switchWorkspace(root);
    await _desktop.bind(root);
    await _translations.bind(root);
    _rebuildRunner(root);
    await _loadExportLanguages();
  }

  /// 运行器随工作区重建：上一个工作区的运行状态不带进新连接。
  void _rebuildRunner(String root) {
    _runner?.dispose();
    _runner = root.isEmpty
        ? null
        : ExportRunner(worker: _worker, workspaceRoot: root);
    _validate?.dispose();
    _validate = root.isEmpty
        ? null
        : ValidateRunner(worker: _worker, workspaceRoot: root);
    _template?.dispose();
    _template = root.isEmpty
        ? null
        : TemplateService(worker: _worker, workspaceRoot: root);
  }

  /// 导出过滤语言清单：取内核 `i18n.status`；拿不到就退回自由输入，不猜语言。
  Future<void> _loadExportLanguages() async {
    var langs = const <String>[];
    try {
      final payload = await _worker.query(
        Methods.i18nStatus,
        workspaceRoot: widget.settings.workspacePath,
      );
      if (payload is Map<String, Object?>) {
        langs = [
          for (final item in (payload['langs'] as List? ?? const []))
            if (item is Map<String, Object?> && item['lang'] is String)
              item['lang']! as String,
        ];
      }
    } on Object catch (_) {
      langs = const [];
    }
    if (mounted) setState(() => _exportLanguages = langs);
  }

  Future<void> _reveal() async {
    await windowManager.setSkipTaskbar(false);
    await windowManager.show();
    await windowManager.focus();
  }

  /// 所有退出入口等待同一次关闭；发布未完成时不得超时退出或强杀。
  Future<void> _shutdown() => _shutdownFuture ??= _worker.stop();

  Future<void> _quit() async {
    await _shutdown();
    await windowManager.destroy();
    exit(0);
  }

  /// 退出意图的唯一入口（托盘「退出」、设置里的「退出应用」、关闭窗口都走这里）。
  Future<void> _requestExit() async {
    if (_exiting) return;
    _exiting = true;
    try {
      final decision = await _askExit();
      switch (decision) {
        case ExitDecision.stay:
          return;
        case ExitDecision.hideToTray:
          await _hideToTray();
          return;
        case ExitDecision.exitNow:
          break;
      }
      // 用户确认退出：在途任务从此没有终态，标为未知而不是假装取消/成功。
      _runner?.markDisconnected();
      await _quit();
    } finally {
      _exiting = false;
    }
  }

  /// 守卫的问题本身：没有草稿也没有在跑任务时直接放行，不打扰。
  Future<ExitDecision> _askExit() {
    if (!mounted) return Future.value(ExitDecision.exitNow);
    return confirmExit(
      context,
      hasDraft: _repo.draftCount > 0,
      runningTask: _runner?.running ?? false,
      draftNotPersisted: _repo.draftCount > 0 && !_repo.draftPersisted,
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
  Widget build(BuildContext context) {
    final banner = _bannerLabel();
    return MaterialApp(
      title: 'ct 工作台',
      theme: buildCtTheme(),
      debugShowCheckedModeBanner: false,
      home: WorkbenchScreen(
        data: _repo,
        refresh: Listenable.merge([_repo, _worker, widget.settings]),
        onResourceSelected: (name) => _repo.loadPreview(name),
        desktop: _desktop,
        settings: widget.settings,
        onWorkspaceChanged: (root) async {
          await widget.settings.setWorkspacePath(root);
          await _openWorkspace();
        },
        onRuntimeChanged: (path) async {
          await widget.settings.setRuntimePath(path);
          await _openWorkspace(force: true);
        },
        onReloadWorkspace: () => _openWorkspace(force: true),
        onExitRequested: _requestExit,
        kernelSummary: _kernelSummary(),
        draft: _repo,
        runner: _runner,
        validate: _validate,
        translations: _translations,
        template: _template,
        exportLanguages: _exportLanguages,
        writeBlockReason: _worker.writeBlockReason(method: Methods.export),
        bannerLabel: banner,
        workspaceKey: _repo.workspaceRoot.isEmpty
            ? 'unbound'
            : _repo.workspaceRoot,
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
    return lines;
  }

  String _bannerLabel() {
    if (_repo.workspaceRoot.isEmpty) return '尚未绑定工作区 · 在「设置」里选择配表工作区';
    return switch (_worker.status) {
      WorkerStatus.ready =>
        '已连接原生内核 · ${_worker.coreVersion} · Schema 保存/导出/部署已接入',
      WorkerStatus.starting => '正在连接原生内核…',
      WorkerStatus.failed => '内核未就绪：${_worker.failureReason ?? '未知原因'}',
      WorkerStatus.stopped => '内核已断开',
    };
  }
}

/// 便于测试断言：工作台是否仍在用样板数据。
bool isSampleData(WorkbenchData data) => data.sampleData;
