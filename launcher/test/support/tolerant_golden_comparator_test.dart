import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'tolerant_golden_comparator.dart';

/// 容差判定本身要有据可查：宿主机噪声放行，真实回归拦截。
///
/// 量级取自真实 CI 证据（见 [goldenTolerance] 的注释）：
/// 噪声 0.01%–0.04%，禁用态配色回归 0.17%–0.20%。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory root;
  late TolerantGoldenFileComparator comparator;

  setUp(() {
    root = Directory.systemTemp.createTempSync('ct-golden-tolerance-');
    comparator = TolerantGoldenFileComparator(
      Uri.file('${root.path}/golden_test.dart'),
    );
  });

  tearDown(() => root.deleteSync(recursive: true));

  Future<void> writeGolden(Uint8List bytes) async {
    final File file = File('${root.path}/goldens/sample.png');
    await file.parent.create(recursive: true);
    await file.writeAsBytes(bytes, flush: true);
  }

  Future<void> expectMatches(Uint8List image) async {
    expect(
      await comparator.compare(image, Uri.parse('goldens/sample.png')),
      isTrue,
    );
  }

  Future<void> expectRejected(Uint8List image) async {
    await expectLater(
      comparator.compare(image, Uri.parse('goldens/sample.png')),
      throwsA(isA<FlutterError>()),
    );
  }

  test('与基线逐像素相同：通过', () async {
    final bytes = await _png(1280, 800);
    await writeGolden(bytes);
    await expectMatches(bytes);
  });

  test('宿主机噪声量级（约 0.04%）在容差内：通过', () async {
    await writeGolden(await _png(1280, 800));
    // 20×20 = 400px / 1_024_000px ≈ 0.04%，与 CI 观测到的宿主机差异同量级。
    await expectMatches(await _png(1280, 800, blockSide: 20));
  });

  test('真实回归量级（约 0.17%）超出容差：失败并给出差异图', () async {
    await writeGolden(await _png(1280, 800));
    // 42×42 = 1764px / 1_024_000px ≈ 0.17%，与禁用态按钮配色回归同量级。
    await expectRejected(await _png(1280, 800, blockSide: 42));
  });

  test('尺寸不同不得被容差放行：失败', () async {
    await writeGolden(await _png(1280, 800));
    await expectRejected(await _png(1279, 800));
  });
}

/// 白底 PNG；[blockSide] 非零时在左上角画一个同色正方形，用来制造已知大小的差异。
Future<Uint8List> _png(int width, int height, {double blockSide = 0}) async {
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.drawRect(
    Offset.zero & Size(width.toDouble(), height.toDouble()),
    Paint()..color = const Color(0xFFFFFFFF),
  );
  if (blockSide > 0) {
    canvas.drawRect(
      Rect.fromLTWH(1, 1, blockSide, blockSide),
      Paint()..color = const Color(0xFF2E7D32),
    );
  }
  final image = await recorder.endRecording().toImage(width, height);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  return data!.buffer.asUint8List();
}
