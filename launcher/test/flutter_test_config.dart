import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'support/tolerant_golden_comparator.dart';

/// 目录级测试配置：截图矩阵只在这里放宽一次判定。
///
/// flutter 工具已经在进入 [testExecutable] 之前按真实测试文件装好
/// [LocalFileComparator]，所以这里直接沿用它的基线目录。
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  final GoldenFileComparator previous = goldenFileComparator;
  if (previous is LocalFileComparator) {
    goldenFileComparator = TolerantGoldenFileComparator.following(previous);
  }
  await testMain();
}
