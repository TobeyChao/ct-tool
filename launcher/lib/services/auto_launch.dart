import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:launch_at_startup/launch_at_startup.dart';

/// 开机自启（对齐 FlClash：launch_at_startup 插件 + macOS 系统登录项）。
class AutoLaunch {
  AutoLaunch._internal() {
    launchAtStartup.setup(
      appName: 'ct_launcher',
      appPath: Platform.resolvedExecutable,
    );
  }

  static final AutoLaunch instance = AutoLaunch._internal();

  Future<bool> get isEnabled async => launchAtStartup.isEnabled();

  /// debug 模式不启用自启（避免开发时污染登录项，对齐 FlClash）。
  Future<void> updateStatus(bool enabled) async {
    if (kDebugMode) return;
    if (await isEnabled == enabled) return;
    if (enabled) {
      await launchAtStartup.enable();
    } else {
      await launchAtStartup.disable();
    }
  }
}
