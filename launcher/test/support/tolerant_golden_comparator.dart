import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

/// 截图基线的比对容差（矩阵说明见 `test/workbench_golden_test.dart`）。
///
/// 即使 Flutter 修订完全相同（本地与 CI 都是 `4cf2416426`），宿主机的系统字体
/// 抗锯齿仍会让极少量像素不同：实测差异 0.01%–0.04%，即
/// [ComparisonResult.diffPercent] 0.0001–0.0004。
/// 真实界面回归的量级要高一个数量级：禁用态按钮配色漂移实测 0.17%–0.20%。
/// 容差取 0.1% 正是卡在两者之间：宿主机噪声不会误报，配色与布局变化仍会被拦下。
const double goldenTolerance = 0.001;

/// 容忍宿主机渲染噪声的比对器：超出容差时仍按默认方式产出差异图并失败。
class TolerantGoldenFileComparator extends LocalFileComparator {
  TolerantGoldenFileComparator(
    super.testFile, {
    this.tolerance = goldenTolerance,
  }) : assert(
         tolerance >= 0 && tolerance <= 1,
         '容差必须是 0..1 的比例（0 逐像素相同，1 完全不同）',
       );

  /// 沿用 [base] 的基线目录：只放宽判定，不改动基线的解析位置。
  ///
  /// flutter 工具在 `testExecutable` 之前就已按真实测试文件装好
  /// [LocalFileComparator]，这里从它取出目录，避免自己拼相对路径。
  factory TolerantGoldenFileComparator.following(
    LocalFileComparator base, {
    double tolerance = goldenTolerance,
  }) => TolerantGoldenFileComparator(
    base.basedir.resolve('golden_test.dart'),
    tolerance: tolerance,
  );

  /// 允许的像素差异比例（0 表示逐像素相同）。
  final double tolerance;

  @override
  Future<bool> compare(Uint8List imageBytes, Uri golden) async {
    final ComparisonResult result = await GoldenFileComparator.compareLists(
      imageBytes,
      await getGoldenBytes(golden),
    );
    final bool passed = result.passed || result.diffPercent <= tolerance;
    if (passed) {
      if (!result.passed) {
        // 容差内的漂移要留痕，否则基线会在无人察觉时越来越旧。
        debugPrint(
          '[golden] $golden 与基线相差 '
          '${(result.diffPercent * 100).toStringAsFixed(3)}%（在容差内）',
        );
      }
      result.dispose();
      return true;
    }

    final String error = await generateFailureOutput(result, golden, basedir);
    result.dispose();
    throw FlutterError(error);
  }
}
