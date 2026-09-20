import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:ct_launcher/services/native_runtime.dart';

void main() {
  group('内置原生运行时布局（任务 2.2）', () {
    test('macOS 指向 Contents/Resources/runtime/ct', () {
      expect(
        NativeRuntimeLocator.bundledCandidate(
          executablePath: '/Apps/ct.app/Contents/MacOS/ct_launcher',
          isMacOS: true,
          isWindows: false,
        ),
        '/Apps/ct.app/Contents/Resources/runtime/ct',
      );
    });

    test('Windows 指向可执行文件同级 runtime\\ct.exe', () {
      expect(
        NativeRuntimeLocator.bundledCandidate(
          executablePath: r'C:\Apps\ct_launcher.exe',
          isMacOS: false,
          isWindows: true,
        ),
        r'C:\Apps\runtime\ct.exe',
      );
    });

    test('Linux 指向同级 runtime/ct', () {
      expect(
        NativeRuntimeLocator.bundledCandidate(
          executablePath: '/opt/ct/ct_launcher',
          isMacOS: false,
          isWindows: false,
        ),
        '/opt/ct/runtime/ct',
      );
    });
  });

  group('运行时发现', () {
    test('内置缺失且未配置开发路径 → 不可用', () async {
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '',
        fileExists: (_) => false,
        dirExists: (_) => false,
        isMacOS: false,
        isWindows: false,
      );
      expect(result, isNull);
    });

    test('内置存在 → 用内置，忽略开发路径', () async {
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '/dev/other-ct',
        fileExists: (path) => path == '/opt/ct/runtime/ct',
        dirExists: (_) => false,
        isMacOS: false,
        isWindows: false,
      );
      expect(result, isNotNull);
      expect(result!.source, RuntimeSource.bundled);
      expect(result.path, '/opt/ct/runtime/ct');
      expect(result.isBundled, isTrue);
    });

    test('开发路径可用 → 显式来源并留下排查线索', () async {
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '/work/native/target/release/ct',
        fileExists: (path) => path == '/work/native/target/release/ct',
        dirExists: (_) => false,
        isMacOS: false,
        isWindows: false,
      );
      expect(result!.source, RuntimeSource.explicit);
      expect(result.reasons.any((r) => r.contains('内置运行时不存在')), isTrue);
      expect(result.reasons.last, contains('使用显式配置的开发运行时'));
    });

    test('开发路径填成目录 → 拒绝并说明（错误对象可诊断）', () async {
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '/work/native/target/release',
        fileExists: (path) => !path.endsWith('runtime/ct'),
        dirExists: (path) => path == '/work/native/target/release',
        isMacOS: false,
        isWindows: false,
      );
      expect(result, isNull);
    });

    test('开发路径文件缺失 → 拒绝并说明', () async {
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '/work/ct-missing',
        fileExists: (_) => false,
        dirExists: (_) => false,
        isMacOS: false,
        isWindows: false,
      );
      expect(result, isNull);
    });

    test('定位器自身从不提出 Python/venv 路径', () async {
      for (final layout in [
        (isMacOS: true, isWindows: false),
        (isMacOS: false, isWindows: true),
        (isMacOS: false, isWindows: false),
      ]) {
        final candidate = NativeRuntimeLocator.bundledCandidate(
          executablePath: '/opt/ct/ct_launcher',
          isMacOS: layout.isMacOS,
          isWindows: layout.isWindows,
        );
        expect(candidate.toLowerCase(), isNot(contains('python')));
        expect(candidate.toLowerCase(), isNot(contains('.venv')));
      }

      // 用户即使把开发路径填成 venv，结果也只能是他给的那条或内置那条：定位器不会去找解释器。
      final result = await NativeRuntimeLocator.discover(
        executablePath: '/opt/ct/ct_launcher',
        explicitPath: '/work/ct/.venv/bin/ct',
        fileExists: (path) => path == '/work/ct/.venv/bin/ct',
        dirExists: (_) => false,
        isMacOS: false,
        isWindows: false,
      );
      expect(result!.source, RuntimeSource.explicit);
      // 显式路径会被归一（折叠 .. / 补绝对前缀），这里只关心它仍是用户给的那条。
      expect(
        result.path.replaceAll('\\', '/'),
        endsWith('/work/ct/.venv/bin/ct'),
      );
      expect(
        result.reasons.any((r) => r.toLowerCase().contains('python')),
        isFalse,
        reason: '定位器自身不应引入 Python 概念',
      );
    });
  });

  test('仓库开发布局能发现已构建的原生二进制', () async {
    final candidate =
        Platform.environment['CT_WORKER_BIN'] ??
        '../native/target/debug/ct.exe';
    if (!File(candidate).existsSync()) {
      return; // 未构建时由真实 worker 测试统一说明，不在此判失败
    }
    final result = await NativeRuntimeLocator.discover(
      executablePath: Platform.resolvedExecutable,
      explicitPath: candidate,
    );
    expect(result, isNotNull);
    expect(File(result!.path).existsSync(), isTrue);
  });
}
