import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 任务 5.7 的机器守护：桌面壳不得再自己扫工作区目录。
///
/// 旧 `StatsService` 直接扫 `config/schemas`、`i18n/`、`output/json`，
/// 一旦工作区用非默认配置目录（`schemas_dir`/`i18n_dir`/`output_dir`…）就会给出错的概览。
/// 现在概览/预览/历史一律来自内核方法回包，这里钉住不回退。
void main() {
  const forbidden = <String>[
    'StatsService',
    r"Directory('\$workspacePath",
    'config/schemas',
    'output/json',
    r"'\$workspacePath/i18n",
    r"'\$workspacePath/excel",
  ];

  test('lib/ 里没有工作区目录硬编码扫描', () {
    final offenders = <String>[];
    for (final file in Directory(
      'lib',
    ).listSync(recursive: true).whereType<File>()) {
      if (!file.path.endsWith('.dart')) continue;
      // 界面样板（dev 组件画廊）里的假路径字符串不算：它不读文件系统。
      if (file.path.replaceAll(r'\', '/').contains('lib/ui/dev/')) continue;
      final text = file.readAsStringSync();
      for (final needle in forbidden) {
        if (text.contains(needle)) {
          offenders.add('${file.path} 含 "$needle"');
        }
      }
    }
    expect(
      offenders,
      isEmpty,
      reason: '概览/预览/历史必须由内核提供：\n${offenders.join('\n')}',
    );
  });

  test('StatsService 文件已移除', () {
    expect(File('lib/services/stats_service.dart').existsSync(), isFalse);
  });
}
