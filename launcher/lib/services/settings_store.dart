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

  /// 默认工作区推断：**只有发行包才推断**，自动化跑一律返回空。
  ///
  /// 规则：从可执行文件上溯找到 launcher 包（有 pubspec.yaml 且有 lib/），取其同级 `gd/`。
  /// 但 `flutter build / drive / test integration_test` 用的产物就住在该包的 `build/` 之下，
  /// 上溯必然命中——那等于让 CI 与集成跑默认打开**真实 gd/**（本轮排查里真出过一次）。
  /// 所以：可执行文件位于包内 build/ 之下，或环境带 FLUTTER_TEST/CT_INTEGRATION_TEST，
  /// 一律不推断，界面显示「未绑定工作区」，必须由调用方显式传 root。
  /// 依据与守卫见 native/docs/baseline/handoff-macos-linux.md。
  @visibleForTesting
  static String inferWorkspacePath({
    required String executablePath,
    Map<String, String> environment = const {},
    bool Function(String path)? fileExists,
    bool Function(String path)? dirExists,
  }) {
    final hasFile = fileExists ?? _defaultFileExists;
    final hasDir = dirExists ?? _defaultDirExists;
    if (environment.containsKey('FLUTTER_TEST') ||
        environment.containsKey('CT_INTEGRATION_TEST')) {
      return '';
    }
    var dir = File(executablePath).parent;
    for (var i = 0; i < 12; i++) {
      if (hasFile('${dir.path}/pubspec.yaml') && hasDir('${dir.path}/lib')) {
        if (_isUnderBuild(executablePath, dir.path)) return '';
        final workspace = normalizePath('${dir.parent.path}/gd');
        return hasDir(workspace) ? workspace : '';
      }
      dir = dir.parent;
    }
    return '';
  }

  /// 路径归一：正斜杠、折叠 `.` 与 `..`、小写。用于判断「是否在包内 build/ 之下」。
  @visibleForTesting
  static String normalizePath(String path) {
    final parts = <String>[];
    for (final segment in path.split(RegExp(r'[/\\]+'))) {
      if (segment.isEmpty || segment == '.') continue;
      if (segment == '..' && parts.isNotEmpty && parts.last != '..') {
        parts.removeLast();
        continue;
      }
      parts.add(segment);
    }
    return parts.join('/').toLowerCase();
  }

  static bool _isUnderBuild(String executablePath, String packageDir) {
    final exe = normalizePath(executablePath);
    final build = normalizePath('$packageDir/build');
    return exe.startsWith('$build/');
  }

  static bool _defaultFileExists(String path) => File(path).existsSync();

  static bool _defaultDirExists(String path) => Directory(path).existsSync();

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
