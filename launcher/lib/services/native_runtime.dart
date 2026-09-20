import 'dart:io';

import 'package:flutter/foundation.dart';

/// 桌面壳使用的原生内核运行时来源。
enum RuntimeSource {
  /// 随应用分发的运行时包（`ct-native-<ver>-<triple>`）。
  bundled,

  /// 用户在设置里显式指定的开发路径。
  explicit,
}

/// 一次解析结果：路径 + 来源 + 排查线索。
final class NativeRuntime {
  const NativeRuntime({
    required this.path,
    required this.source,
    this.reasons = const [],
  });

  final String path;
  final RuntimeSource source;

  /// 即使可用也保留的排查线索（例如被跳过的候选路径）。
  final List<String> reasons;

  bool get isBundled => source == RuntimeSource.bundled;
}

/// 原生运行时发现（native-flutter-workbench 任务 2.2）。
///
/// 只有两条来源：应用包内置 → 用户显式配置的开发路径。
/// **不存在 Python/venv 回退**：两者都不可用时返回 null，由调用方给出可操作错误。
abstract final class NativeRuntimeLocator {
  /// 内置运行时的平台布局（纯路径拼接，是否存在由 [discover] 判定）：
  /// macOS `<app>.app/Contents/MacOS/<bin>` → `Contents/Resources/runtime/ct`
  /// Windows `<dir>\ct_launcher.exe` → `<dir>\runtime\ct.exe`
  @visibleForTesting
  static String bundledCandidate({
    required String executablePath,
    required bool isMacOS,
    required bool isWindows,
  }) {
    final dir = File(executablePath).parent;
    if (isMacOS) {
      // MacOS 的 Contents/MacOS 上一级是 Contents，运行时放 Resources/runtime。
      return _join([dir.parent.path, 'Resources', 'runtime', 'ct'], false);
    }
    return _join([dir.path, 'runtime', isWindows ? 'ct.exe' : 'ct'], isWindows);
  }

  static String _join(List<String> parts, bool windows) =>
      parts.join(windows ? r'\' : '/');

  /// 解析可用运行时；两个存在性判定都可注入，便于覆盖缺文件/选错对象分支。
  static Future<NativeRuntime?> discover({
    required String executablePath,
    required String? explicitPath,
    bool Function(String path) fileExists = _defaultFileExists,
    bool Function(String path) dirExists = _defaultDirExists,
    bool? isMacOS,
    bool? isWindows,
    List<String>? diagnostics,
  }) async {
    final mac = isMacOS ?? Platform.isMacOS;
    final win = isWindows ?? Platform.isWindows;
    final notes = <String>[...?diagnostics];

    final bundled = bundledCandidate(
      executablePath: executablePath,
      isMacOS: mac,
      isWindows: win,
    );
    if (fileExists(bundled)) {
      return NativeRuntime(
        path: bundled,
        source: RuntimeSource.bundled,
        reasons: notes,
      );
    }
    notes.add('内置运行时不存在：$bundled');

    final explicit = explicitPath?.trim();
    if (explicit == null || explicit.isEmpty) {
      notes.add('未配置开发用运行时路径');
      return null;
    }
    if (dirExists(explicit)) {
      notes.add('配置的路径是目录而不是可执行文件：$explicit');
      return null;
    }
    if (!fileExists(explicit)) {
      notes.add('配置的运行时路径不存在或不可执行：$explicit');
      return null;
    }
    return NativeRuntime(
      // 折叠 .. 与相对片段：Windows 创建进程不接受这类路径写法。
      path: _normalize(explicit),
      source: RuntimeSource.explicit,
      reasons: [...notes, '使用显式配置的开发运行时：$explicit'],
    );
  }

  static bool _defaultFileExists(String path) => File(path).existsSync();

  static bool _defaultDirExists(String path) => Directory(path).existsSync();

  static String _normalize(String path) =>
      Uri.file(File(path).absolute.path).normalizePath().toFilePath();
}
