import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 启动器配置：工作区 / 工具目录 / 端口 / 自启 / 托盘常驻。
class SettingsStore extends ChangeNotifier {
  static const kWorkspacePath = 'workspace_path';
  static const kNativeRuntimePath = 'native_runtime_path';
  static const kPort = 'port';
  static const kAutoStart = 'auto_start';
  static const kTrayResident = 'tray_resident';

  String workspacePath = '';
  String nativeRuntimePath = '';
  int port = 8000;
  bool autoStart = false;
  bool trayResident = false;
  bool _loaded = false;

  String get baseUrl => 'http://127.0.0.1:$port';

  Future<void> load() async {
    if (_loaded) return;
    final prefs = await SharedPreferences.getInstance();
    workspacePath = prefs.getString(kWorkspacePath) ?? '';
    // 旧 tool_dir 指向 Python 源码，不将它作为原生可执行文件迁移。
    nativeRuntimePath = prefs.getString(kNativeRuntimePath) ?? _inferRuntime();
    port = prefs.getInt(kPort) ?? 8000;
    autoStart = prefs.getBool(kAutoStart) ?? false;
    trayResident = prefs.getBool(kTrayResident) ?? false;
    _loaded = true;
    notifyListeners();
  }

  /// 仅推断开发运行时，工作区由用户明确选择。
  static String _inferRuntime() {
    var dir = File(Platform.resolvedExecutable).parent;
    for (var i = 0; i < 12; i++) {
      if (File('${dir.path}/pubspec.yaml').existsSync() &&
          Directory('${dir.path}/lib').existsSync()) {
        final name = Platform.isWindows ? 'ct.exe' : 'ct';
        for (final profile in ['debug', 'release']) {
          final path = '${dir.parent.path}/native/target/$profile/$name';
          if (File(path).existsSync()) return path;
        }
      }
      dir = dir.parent;
    }
    return '';
  }

  Future<void> setWorkspacePath(String value) async {
    workspacePath = value;
    await _save(kWorkspacePath, value);
  }

  Future<void> setNativeRuntimePath(String value) async {
    nativeRuntimePath = value;
    await _save(kNativeRuntimePath, value);
  }

  Future<void> setPort(int value) async {
    port = value;
    await _save(kPort, value);
  }

  Future<void> setAutoStart(bool value) async {
    autoStart = value;
    await _save(kAutoStart, value);
  }

  Future<void> setTrayResident(bool value) async {
    trayResident = value;
    await _save(kTrayResident, value);
  }

  Future<void> _save(String key, Object value) async {
    final prefs = await SharedPreferences.getInstance();
    switch (value) {
      case final String v:
        await prefs.setString(key, v);
      case final int v:
        await prefs.setInt(key, v);
      case final bool v:
        await prefs.setBool(key, v);
    }
    notifyListeners();
  }
}
