import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 桌面偏好（native-flutter-workbench 任务 2.4）。
///
/// 只保留原生内核用得上的四项：工作区、可选的开发期运行时路径、开机自启、托盘常驻。
/// 旧版的 `tool_dir`（Python 工具目录）与 `port`（面板监听端口）已废弃：
/// [load] 会把它们从存储中清除，并用 [migratedFromLegacy] 让界面提示一次性说明。
class SettingsStore extends ChangeNotifier {
  static const kWorkspacePath = 'workspace_path';
  static const kRuntimePath = 'runtime_path';
  static const kAutoStart = 'auto_start';
  static const kTrayResident = 'tray_resident';
  static const kLegacyDraftSeen = 'legacy_draft_notice_seen';

  /// 已废弃的旧键（仅用于迁移清理，不再读取其值参与任何启动参数）。
  static const legacyKeys = <String>[
    'tool_dir',
    'port',
    'host',
    'python_path',
    // 旧面板时代的固定尺寸窗口设置：原生工作台是可调窗口，绝不继承（任务 2.5）。
    'window_width',
    'window_height',
    'window_x',
    'window_y',
    'window_resizable',
    'window_maximized',
  ];

  String workspacePath = '';

  /// 开发期显式指定的原生内核可执行文件；留空表示使用应用包内置运行时。
  String runtimePath = '';
  bool autoStart = false;
  bool trayResident = false;

  /// 本次 [load] 是否清掉了旧配置（用于设置页一次性提示）。
  bool migratedFromLegacy = false;

  /// 旧浏览器（IndexedDB）草稿不会自动迁移：只提示一次，由用户在旧端自行保存。
  bool legacyDraftNoticeSeen = false;

  /// 自动推断出的开发期运行时路径（设置页的「恢复为自动推断」用）。
  String inferredRuntimePath = '';

  bool _loaded = false;

  Future<void> load() async {
    if (_loaded) return;
    final prefs = await SharedPreferences.getInstance();
    // 新安装必须由用户明确选择工作区，不能自动绑定仓库里的真实 gd。
    workspacePath = prefs.getString(kWorkspacePath) ?? '';
    inferredRuntimePath = _inferNativeRuntime();
    // main 的薄桌面壳已保存原生路径；仅迁移这个键，不读取旧 Python tool_dir。
    const previousRuntimeKey = 'native_runtime_path';
    final savedRuntime = prefs.getString(kRuntimePath);
    final previousRuntime = prefs.getString(previousRuntimeKey);
    runtimePath = savedRuntime ?? previousRuntime ?? inferredRuntimePath;
    if (savedRuntime == null && previousRuntime != null) {
      await prefs.setString(kRuntimePath, previousRuntime);
    }
    await prefs.remove(previousRuntimeKey);
    autoStart = prefs.getBool(kAutoStart) ?? false;
    trayResident = prefs.getBool(kTrayResident) ?? false;
    migratedFromLegacy = await _dropLegacy(prefs);
    legacyDraftNoticeSeen = prefs.getBool(kLegacyDraftSeen) ?? false;
    _loaded = true;
    notifyListeners();
  }

  /// 删除废弃键；返回是否真的清掉过东西。
  static Future<bool> _dropLegacy(SharedPreferences prefs) async {
    var removed = false;
    for (final key in legacyKeys) {
      if (prefs.containsKey(key)) {
        removed = true;
        await prefs.remove(key);
      }
    }
    return removed;
  }

  /// 供测试与界面确认：旧键确实不再存在。
  static Future<bool> legacyKeysCleared() async {
    final prefs = await SharedPreferences.getInstance();
    return legacyKeys.every((key) => !prefs.containsKey(key));
  }

  /// 开发期原生运行时：`native/target/{release,debug}/ct[.exe]`。
  static String _inferNativeRuntime() {
    final exeName = Platform.isWindows ? 'ct.exe' : 'ct';
    var dir = File(Platform.resolvedExecutable).parent;
    for (var i = 0; i < 12; i++) {
      if (File('${dir.path}/pubspec.yaml').existsSync() &&
          Directory('${dir.path}/lib').existsSync()) {
        final native = '${dir.parent.path}/native/target';
        for (final profile in ['release', 'debug']) {
          final candidate = '$native/$profile/$exeName';
          if (File(candidate).existsSync()) return candidate;
        }
        return '';
      }
      dir = dir.parent;
    }
    return '';
  }

  /// 旧浏览器草稿的迁移提示只说一次，之后不再打扰。
  Future<void> acknowledgeLegacyDraftNotice() async {
    legacyDraftNoticeSeen = true;
    notifyListeners();
    await _save(kLegacyDraftSeen, true);
  }

  Future<void> setWorkspacePath(String value) async {
    workspacePath = value;
    await _save(kWorkspacePath, value);
  }

  Future<void> setRuntimePath(String value) async {
    runtimePath = value;
    await _save(kRuntimePath, value);
  }

  /// 清空显式路径，回到自动推断（打包分发时就是空值，走内置运行时）。
  Future<void> useInferredRuntimePath() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kRuntimePath);
    runtimePath = inferredRuntimePath;
    notifyListeners();
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
      case final bool v:
        await prefs.setBool(key, v);
    }
    notifyListeners();
  }
}
