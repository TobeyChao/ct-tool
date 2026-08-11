import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 启动器配置：工作区 / 工具目录 / 端口 / 自启 / 托盘常驻。
class SettingsStore extends ChangeNotifier {
  static const kWorkspacePath = 'workspace_path';
  static const kToolDir = 'tool_dir';
  static const kPort = 'port';
  static const kAutoStart = 'auto_start';
  static const kTrayResident = 'tray_resident';

  String workspacePath = '';
  String toolDir = '';
  int port = 8000;
  bool autoStart = false;
  bool trayResident = false;
  bool _loaded = false;

  String get pythonPath {
    final base = toolDir.isEmpty ? '' : '$toolDir/.venv';
    return Platform.isWindows ? '$base\\Scripts\\python.exe' : '$base/bin/python';
  }

  /// ct 控制台入口（pyproject [project.scripts] 安装的 wrapper）。
  String get ctCliPath {
    final base = toolDir.isEmpty ? '' : '$toolDir/.venv';
    return Platform.isWindows ? '$base\\Scripts\\ct.exe' : '$base/bin/ct';
  }

  String get baseUrl => 'http://127.0.0.1:$port';

  Future<void> load() async {
    if (_loaded) return;
    final prefs = await SharedPreferences.getInstance();
    final defaults = _inferDefaults();
    final defaultTool = defaults.$1;
    final defaultWs = defaults.$2;
    workspacePath = prefs.getString(kWorkspacePath) ?? defaultWs;
    toolDir = prefs.getString(kToolDir) ?? defaultTool;
    port = prefs.getInt(kPort) ?? 8000;
    autoStart = prefs.getBool(kAutoStart) ?? false;
    trayResident = prefs.getBool(kTrayResident) ?? false;
    _loaded = true;
    notifyListeners();
  }

  /// 开发期默认值推断：从可执行文件向上找 Flutter 项目根（tool/launcher），
  /// 得到工具目录 tool/ 与工作区仓库根/gd。打包分发后找不到项目结构，
  /// 返回空值，由用户在设置中配置。
  static (String, String) _inferDefaults() {
    var dir = File(Platform.resolvedExecutable).parent;
    for (var i = 0; i < 12; i++) {
      if (File('${dir.path}/pubspec.yaml').existsSync() &&
          Directory('${dir.path}/lib').existsSync()) {
        // 仓库布局：launcher/ 与 tool/、gd/ 平级于仓库根
        final repoRoot = dir.parent.path;
        final tool = '$repoRoot/tool';
        final ws = '$repoRoot/gd';
        // 校验工具目录存在（含 venv 或 ct 包），不存在则留给用户配置
        if (!Directory('$tool/.venv').existsSync() &&
            !Directory('$tool/ct').existsSync()) {
          return ('', '');
        }
        return (tool, ws);
      }
      dir = dir.parent;
    }
    return ('', '');
  }

  Future<void> setWorkspacePath(String value) async {
    workspacePath = value;
    await _save(kWorkspacePath, value);
  }

  Future<void> setToolDir(String value) async {
    toolDir = value;
    await _save(kToolDir, value);
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
