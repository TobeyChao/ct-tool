import 'dart:io';

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'app.dart';
import 'services/settings_store.dart';
import 'services/single_instance_lock.dart';
import 'services/window_options.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  // 单实例：已有实例在运行时直接退出（对齐 FlClash）。
  if (!await SingleInstanceLock().acquire()) {
    // 已有实例在跑：直接退出，**不会**再启动第二个 worker 进程。
    stderr.writeln('检测到已有 ct 工作台实例在运行，本次启动退出。');
    exit(0);
  }

  final settings = SettingsStore();
  await settings.load();

  // 可调原生工作台：默认 1280×800、最小 1024×700（任务 2.5，参数见 window_options.dart）
  final windowOptions = desktopWindowOptions();
  await windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.setResizable(true);
    // 对齐 FlClash：启动阶段就拦截关闭事件，关闭行为由 app 层决策。
    await windowManager.setPreventClose(true);
    await windowManager.show();
    await windowManager.focus();
  });

  runApp(LauncherApp(settings: settings));
}
