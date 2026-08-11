import 'dart:io';

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'app.dart';
import 'services/settings_store.dart';
import 'services/single_instance_lock.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  // 单实例：已有实例在运行时直接退出（对齐 FlClash）。
  if (!await SingleInstanceLock().acquire()) {
    exit(0);
  }

  final settings = SettingsStore();
  await settings.load();

  final windowOptions = WindowOptions(
    // 按内容适配：左侧导航 176 + 内容区 ~540，高度容纳概览/设置页并给日志留足空间
    size: Size(720, 460),
    minimumSize: Size(720, 460),
    center: true,
    title: 'ct Launcher',
    // 对齐 FlClash：macOS 隐藏标题栏条（保留系统红绿灯），内容顶到顶部；
    // Windows 暂用系统标题栏，后续再对齐自绘方案。
    titleBarStyle: Platform.isMacOS ? TitleBarStyle.hidden : TitleBarStyle.normal,
  );
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.setResizable(false);
    // 对齐 FlClash：启动阶段就拦截关闭事件，关闭行为由 app 层决策。
    await windowManager.setPreventClose(true);
    await windowManager.show();
    await windowManager.focus();
  });

  runApp(LauncherApp(settings: settings));
}
