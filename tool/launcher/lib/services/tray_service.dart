import 'dart:io';

import 'package:tray_manager/tray_manager.dart';

import 'panel_service.dart';

/// 系统托盘：菜单随面板状态联动。
class TrayService with TrayListener {
  TrayService({
    required this.panel,
    required this.onQuit,
    this.onShowWindow,
    this.onOpenPanel,
  });

  final PanelService panel;
  final Future<void> Function() onQuit;

  final Future<void> Function()? onShowWindow;
  final Future<void> Function()? onOpenPanel;

  bool _initialized = false;

  Future<void> init() async {
    if (_initialized) return;
    _initialized = true;
    trayManager.addListener(this);
    try {
      await trayManager.setIcon(
        Platform.isWindows ? 'assets/icons/tray_icon.ico' : 'assets/icons/tray_icon.png',
        isTemplate: Platform.isMacOS,
      );
      await trayManager.setToolTip('ct Launcher');
    } catch (_) {
      // 托盘初始化失败不阻塞主界面
    }
    panel.addListener(_syncMenu);
    await _syncMenu();
  }

  Future<void> _syncMenu() async {
    if (!_initialized) return;
    final running = panel.status == PanelStatus.running;
    await trayManager.setContextMenu(
      Menu(
        items: [
          MenuItem(
            key: 'open_panel',
            label: '打开面板',
            onClick: (_) => onOpenPanel?.call(),
          ),
          MenuItem(
            key: 'toggle',
            label: running ? '暂停服务' : '启动服务',
            onClick: (_) {
              if (running) {
                panel.stop();
              } else {
                panel.start();
              }
            },
          ),
          MenuItem(
            key: 'show',
            label: '显示启动器',
            onClick: (_) => onShowWindow?.call(),
          ),
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
    // 与 FlClash 一致的交互：左键显示窗口，右键弹出菜单。
    // ignore: deprecated_member_use
    trayManager.popUpContextMenu(bringAppToFront: true);
  }

  void dispose() {
    trayManager.removeListener(this);
    panel.removeListener(_syncMenu);
  }
}
