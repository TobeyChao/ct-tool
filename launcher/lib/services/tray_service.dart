import 'dart:io';

import 'package:tray_manager/tray_manager.dart';

import 'worker_service.dart';

/// 系统托盘：菜单反映内核连接状态（对齐 FlClash 的左键显示/右键菜单）。
class TrayService with TrayListener {
  TrayService({
    required this.worker,
    required this.onQuit,
    this.onShowWindow,
    this.onReload,
  });

  final WorkerService worker;
  final Future<void> Function() onQuit;
  final Future<void> Function()? onShowWindow;

  /// 重新连接内核并重载当前工作区。
  final Future<void> Function()? onReload;

  bool _initialized = false;

  Future<void> init() async {
    if (_initialized) return;
    _initialized = true;
    trayManager.addListener(this);
    try {
      await trayManager.setIcon(
        Platform.isWindows
            ? 'assets/icons/tray_icon.ico'
            : 'assets/icons/tray_icon.png',
        isTemplate: Platform.isMacOS,
      );
      await trayManager.setToolTip('ct 工作台');
    } catch (_) {
      // 托盘初始化失败不阻塞主界面
    }
    worker.addListener(_syncMenu);
    await _syncMenu();
  }

  String get _statusLabel => switch (worker.status) {
    WorkerStatus.ready => '内核就绪',
    WorkerStatus.starting => '连接中',
    WorkerStatus.failed => '内核异常',
    WorkerStatus.stopped => '内核未连接',
  };

  Future<void> _syncMenu() async {
    if (!_initialized) return;
    await trayManager.setToolTip('ct 工作台 · $_statusLabel');
    await trayManager.setContextMenu(
      Menu(
        items: [
          MenuItem(
            key: 'show',
            label: '显示主窗口',
            onClick: (_) => onShowWindow?.call(),
          ),
          MenuItem(
            key: 'reload',
            label: '重新加载工作区',
            onClick: (_) => onReload?.call(),
          ),
          MenuItem(key: 'status', label: _statusLabel, onClick: (_) {}),
          MenuItem.separator(),
          MenuItem(key: 'quit', label: '退出', onClick: (_) => onQuit()),
        ],
      ),
    );
  }

  @override
  void onTrayIconMouseDown() {
    onShowWindow?.call();
  }

  @override
  void onTrayIconRightMouseDown() {
    // ignore: deprecated_member_use
    trayManager.popUpContextMenu(bringAppToFront: true);
  }

  void dispose() {
    trayManager.removeListener(this);
    worker.removeListener(_syncMenu);
  }
}
