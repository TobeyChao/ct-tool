import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/single_instance_lock.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'missing default directory plugin may bypass without claiming a lock',
    () async {
      final lock = SingleInstanceLock();
      expect(await lock.acquire(), isTrue);
      expect(lock.held, isFalse);
      await lock.release();
    },
  );

  test(
    'default root must acquire a real lock and lookup failures refuse startup',
    () async {
      final root = await Directory.systemTemp.createTemp('ct-lock-default-');
      const channel = MethodChannel('plugins.flutter.io/path_provider');
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      final lock = SingleInstanceLock();
      try {
        messenger.setMockMethodCallHandler(channel, (_) async => root.path);
        expect(await lock.acquire(), isTrue);
        expect(lock.held, isTrue);
        await lock.release();

        messenger.setMockMethodCallHandler(
          channel,
          (_) async => throw PlatformException(code: 'access-denied'),
        );
        expect(await lock.acquire(), isFalse);
        expect(lock.held, isFalse);

        // Missing platform directory is different from a missing plugin.
        messenger.setMockMethodCallHandler(channel, (_) async => null);
        expect(await lock.acquire(), isFalse);
        expect(lock.held, isFalse);

        final blockedRoot = await Directory('${root.path}/blocked').create();
        await Directory('${blockedRoot.path}/ct_launcher.lock').create();
        messenger.setMockMethodCallHandler(
          channel,
          (_) async => blockedRoot.path,
        );
        expect(await lock.acquire(), isFalse);
        expect(lock.held, isFalse);
      } finally {
        messenger.setMockMethodCallHandler(channel, null);
        await lock.release();
        await root.delete(recursive: true);
      }
    },
  );

  test('filesystem acquisition failures refuse startup', () async {
    final root = await Directory.systemTemp.createTemp('ct-lock-failure-');
    final lock = SingleInstanceLock(
      dirOverride: Directory('${root.path}/file'),
    );
    try {
      await File('${root.path}/file').writeAsString('not a directory');
      expect(await lock.acquire(), isFalse);
      expect(lock.held, isFalse);
      await lock.release();

      // A valid root with an unusable lock-file path must also refuse startup.
      await Directory('${root.path}/ct_launcher.lock').create();
      final blockedFile = SingleInstanceLock(dirOverride: root);
      expect(await blockedFile.acquire(), isFalse);
      expect(blockedFile.held, isFalse);
      await blockedFile.release();
    } finally {
      await lock.release();
      await root.delete(recursive: true);
    }
  });

  test(
    'repeated acquire preserves the held lock and release permits reacquisition',
    () async {
      final root = await Directory.systemTemp.createTemp('ct-lock-held-');
      final lock = SingleInstanceLock(dirOverride: root);
      try {
        expect(await lock.acquire(), isTrue);
        expect(await lock.acquire(), isTrue);
        expect(lock.held, isTrue);
        await lock.release();
        expect(lock.held, isFalse);
        expect(await lock.acquire(), isTrue);
        expect(lock.held, isTrue);
      } finally {
        await lock.release();
        await root.delete(recursive: true);
      }
    },
  );

  test(
    'a real process holding the OS lock rejects a duplicate contender',
    () async {
      final root = await Directory.systemTemp.createTemp('ct-lock-process-');
      final script = File('${root.path}/holder.dart');
      final lockPath = '${root.path}/ct_launcher.lock';
      final contender = SingleInstanceLock(dirOverride: root);
      Process? holder;
      Future<int>? exit;
      try {
        await script.writeAsString('''
import 'dart:io';

Future<void> main(List<String> args) async {
  final file = await File(args.single).open(mode: FileMode.append);
  await file.lock(FileLock.exclusive);
  stdout.writeln('held');
  await stdout.flush();
  await stdin.drain<void>();
  await file.unlock();
  await file.close();
}
''');
        // flutter_tester lives under cache/artifacts/engine; use its sibling SDK.
        final dart = Platform.resolvedExecutable.replaceFirst(
          RegExp(r'/artifacts/engine/.*$'),
          '/dart-sdk/bin/dart',
        );
        expect(File(dart).existsSync(), isTrue, reason: 'Dart SDK: $dart');
        holder = await Process.start(dart, [script.path, lockPath]);
        exit = holder.exitCode;
        final diagnostics = holder.stderr.transform(utf8.decoder).join();
        final lines = StreamIterator<String>(
          holder.stdout.transform(utf8.decoder).transform(const LineSplitter()),
        );
        try {
          expect(
            await lines.moveNext().timeout(const Duration(seconds: 10)),
            isTrue,
          );
          expect(lines.current, 'held');

          // This documents the actual macOS failure, rather than mocking errno 35.
          final probe = await File(lockPath).open(mode: FileMode.append);
          try {
            await expectLater(
              probe.lock(FileLock.exclusive),
              throwsA(
                isA<FileSystemException>().having(
                  (error) => error.osError?.errorCode,
                  'contention errno',
                  Platform.isMacOS ? 35 : isNotNull,
                ),
              ),
            );
          } finally {
            await probe.close();
          }

          expect(
            await contender.acquire().timeout(const Duration(seconds: 2)),
            isFalse,
          );
          expect(contender.held, isFalse);
          expect(await contender.acquire(), isFalse);
          expect(contender.held, isFalse);

          await holder.stdin.close();
          expect(await exit.timeout(const Duration(seconds: 10)), 0);
          expect(await diagnostics, isEmpty);
          expect(await contender.acquire(), isTrue);
          expect(contender.held, isTrue);
        } finally {
          await lines.cancel();
        }
      } finally {
        await contender.release();
        if (holder != null) {
          await holder.stdin.close();
          await exit?.timeout(const Duration(seconds: 10));
        }
        await root.delete(recursive: true);
      }
    },
    timeout: const Timeout(Duration(seconds: 30)),
  );
}
