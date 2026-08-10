import 'dart:io';

class LauncherStats {
  const LauncherStats({
    required this.tableCount,
    required this.languages,
    required this.lastExportAt,
  });

  final int tableCount;
  final List<String> languages;
  final DateTime? lastExportAt;
}

/// 从工作区直接读取概览统计（不依赖面板进程）。
class StatsService {
  static Future<LauncherStats> load(String workspacePath) async {
    var tableCount = 0;
    final schemasDir = Directory('$workspacePath/config/schemas');
    if (schemasDir.existsSync()) {
      tableCount = schemasDir
          .listSync()
          .where((f) => f.path.endsWith('.yaml'))
          .length;
    }

    var languages = <String>[];
    final i18nDir = Directory('$workspacePath/i18n');
    if (i18nDir.existsSync()) {
      languages = i18nDir
          .listSync()
          .whereType<Directory>()
          .map((d) => d.uri.pathSegments.isEmpty ? '' : d.uri.pathSegments.last)
          .where((n) => n.isNotEmpty && n != 'source')
          .toList()
        ..sort();
    }

    DateTime? lastExportAt;
    final jsonDir = Directory('$workspacePath/output/json');
    if (jsonDir.existsSync()) {
      for (final e in jsonDir.listSync()) {
        final m = e.statSync().modified;
        if (lastExportAt == null || m.isAfter(lastExportAt)) lastExportAt = m;
      }
    }

    return LauncherStats(
      tableCount: tableCount,
      languages: languages,
      lastExportAt: lastExportAt,
    );
  }
}
