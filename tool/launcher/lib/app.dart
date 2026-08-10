import 'dart:io';
import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'services/panel_service.dart';
import 'services/settings_store.dart';
import 'services/tray_service.dart';
import 'theme.dart';
import 'ui/launcher_screen.dart';
import 'ui/widgets/common.dart';

class LauncherApp extends StatefulWidget {
  const LauncherApp({super.key, required this.settings});

  final SettingsStore settings;

  @override
  State<LauncherApp> createState() => _LauncherAppState();
}

class _LauncherAppState extends State<LauncherApp> with WindowListener {
  late final PanelService _panel;
  late final TrayService _tray;
  late final AppLifecycleListener _lifecycleListener;

  @override
  void initState() {
    super.initState();
    _panel = PanelService(settings: widget.settings);
    _tray = TrayService(
      panel: _panel,
      onQuit: () async {
        await _panel.stop();
        await windowManager.destroy();
        exit(0);
      },
      onShowWindow: () async {
        await windowManager.setSkipTaskbar(false);
        await windowManager.show();
        await windowManager.focus();
      },
      onOpenPanel: () async {
        await openPanelInBrowser(_panel.baseUrl);
      },
    );
    // 拦截 Cmd+Q / Dock 退出：先停 Flask 子进程再真正退出，避免孤儿进程。
    _lifecycleListener = AppLifecycleListener(
      onExitRequested: () async {
        await _panel.stop();
        return AppExitResponse.exit;
      },
    );
    // 窗口关闭事件由 app 层统一决策（对齐 FlClash 的 WindowManager 模式）
    windowManager.addListener(this);
    _tray.init();
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    _lifecycleListener.dispose();
    _tray.dispose();
    _panel.dispose();
    super.dispose();
  }

  @override
  void onWindowClose() async {
    if (widget.settings.trayResident) {
      // 托盘常驻：先隐藏窗口，再从 Dock/任务栏消失（对齐 FlClash 顺序）
      await windowManager.hide();
      try {
        await windowManager.setSkipTaskbar(true);
      } catch (_) {
        // 个别平台不支持跳过任务栏时忽略
      }
      return;
    }
    // 退出：3 秒兜底强制退出，避免任何残留（对齐 FlClash handleExit）
    Future.delayed(const Duration(seconds: 3), () => exit(0));
    try {
      await _panel.stop().timeout(const Duration(seconds: 8), onTimeout: () {});
      await windowManager.destroy();
    } finally {
      exit(0);
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ct Launcher',
      theme: buildCtTheme(),
      debugShowCheckedModeBanner: false,
      home: LauncherScreen(settings: widget.settings, panel: _panel),
    );
  }
}
