import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/validate_runner.dart';
import 'package:flutter_test/flutter_test.dart';

/// 桌面「校验」入口的内核证据（任务 5.4 前置）：真实 `ct worker` + 临时工作区。
///
/// 断言的是口径：好数据说通过、坏数据必须不通过（错误或问题都算），
/// 且运行器不替内核下结论。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  late Directory ws;
  late WorkerService worker;

  setUp(() async {
    if (!available) return;
    ws = await Directory.systemTemp.createTemp('ct-validate-');
    final source = Directory('../native/fixtures/export_pipeline/workspace');
    await for (final entity in source.list(recursive: true)) {
      final relative = entity.path.substring(source.path.length + 1);
      final target = '${ws.path}/$relative';
      if (entity is Directory) {
        await Directory(target).create(recursive: true);
      } else if (entity is File) {
        await Directory(File(target).parent.path).create(recursive: true);
        await entity.copy(target);
      }
    }
    final transport = await StdioWorkerTransport.start(
      executable: File(binary).absolute.path,
      workingDirectory: ws.path,
    );
    worker = WorkerService(
      settings: SettingsStore()
        ..workspacePath = ws.path
        ..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    await worker.start();
  });

  tearDown(() async {
    if (!available) return;
    await worker.stop();
    try {
      ws.deleteSync(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  });

  test('好夹具：内核说通过，运行器原样转达', () async {
    final runner = ValidateRunner(worker: worker, workspaceRoot: ws.path);
    final result = await runner.run();
    expect(result, isNotNull, reason: runner.error ?? '');
    expect(
      result!.ok,
      isTrue,
      reason: 'issues: ${result.issues.map((i) => i.message).toList()}',
    );
    expect(result.issues, isEmpty);
    expect(runner.summaryLabel, contains('校验通过'));
    expect(runner.elapsedMs, isNotNull, reason: '耗时来自真实计时，不是装饰');
  }, skip: available ? false : skipReason);

  test('单表范围随请求走内核', () async {
    final runner = ValidateRunner(worker: worker, workspaceRoot: ws.path);
    runner.scopeTable = 'Item';
    final result = await runner.run();
    expect(result?.ok, isTrue, reason: runner.error ?? '');
    expect(runner.summaryLabel, contains('表 Item'));
  }, skip: available ? false : skipReason);

  test('坏 schema：必须不通过，且不粉饰', () async {
    final yaml = File('${ws.path}/config/schemas/item.yaml');
    final original = yaml.readAsStringSync();
    // 引一个不存在的具名类型：内核按问题或错误回，两种都不算通过。
    yaml.writeAsStringSync(
      '$original\n  - name: Broken\n    type: NoSuchTypeHere\n',
    );
    final runner = ValidateRunner(worker: worker, workspaceRoot: ws.path);
    final result = await runner.run();
    expect(result?.ok ?? false, isFalse, reason: '坏 schema 下内核不得说通过');
    expect(
      (result?.issues.isNotEmpty ?? false) || (runner.error ?? '').isNotEmpty,
      isTrue,
      reason: '要么带问题，要么带错误——不能静默',
    );
    expect(runner.summaryLabel, isNot(contains('校验通过')));
    yaml.writeAsStringSync(original);
  }, skip: available ? false : skipReason);

  test('校验方法与协议常量同源', () {
    expect(Methods.validate, 'validate');
  });
}
