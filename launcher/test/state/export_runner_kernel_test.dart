import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:flutter_test/flutter_test.dart';

/// 导出/部署/取消直连真实 `ct worker`（任务 4.4/4.6 的内核侧证据）。
///
/// 断言只认内核回包：阶段与耗时非空、缓存有命中、桌面导出不产生部署、
/// 未知过滤条件由内核拒绝、终态之后的取消不改写成功。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({Directory ws, WorkerService worker, ExportRunner runner})>
  open() async {
    final ws = await Directory.systemTemp.createTemp('ct-export-runner-');
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
    final worker = WorkerService(
      settings: SettingsStore()
        ..workspacePath = ws.path
        ..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    await worker.start();
    final runner = ExportRunner(worker: worker, workspaceRoot: ws.path);
    worker.events.listen(runner.onEvent);
    return (ws: ws, worker: worker, runner: runner);
  }

  Future<void> close(
    ({Directory ws, WorkerService worker, ExportRunner runner}) ctx,
  ) async {
    await ctx.worker.stop();
    ctx.runner.dispose();
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  test(
    '真内核导出：阶段/耗时/缓存统计齐备，且不会顺带部署',
    () async {
      if (!available) return;
      final ctx = await open();

      expect(await ctx.runner.startExport(), isTrue);
      expect(ctx.runner.phase, RunnerPhase.succeeded);
      final first = ctx.runner.result!;
      expect(first.outcome, TaskOutcome.succeeded);
      expect(first.tables, greaterThanOrEqualTo(1));
      expect(first.durationMs, greaterThan(0));
      expect(first.stages, isNotEmpty, reason: '阶段耗时必须由内核给出');
      expect(first.cache, isNotNull);

      // 以内核任务账本为证：这条连接里没有出现过 deploy 任务
      final ledger = await ctx.worker.query(
        Methods.tasksList,
        workspaceRoot: ctx.ws.path,
      );
      final methods = [
        for (final task
            in (ledger! as Map<String, Object?>)['tasks'] as List? ?? const [])
          (task! as Map<String, Object?>)['method'],
      ];
      expect(methods, contains(Methods.export));
      expect(methods, isNot(contains(Methods.deploy)), reason: '桌面导出不自动部署');

      // 第二次导出应复用缓存（增量），且阶段仍然齐备
      expect(await ctx.runner.startExport(), isTrue);
      final again = ctx.runner.result!;
      expect(again.stages, isNotEmpty);
      expect(
        again.cache!.hits + again.cache!.misses,
        greaterThan(0),
        reason: '缓存统计不能是哑值',
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );

  test(
    '独立部署是显式请求；未配置目标时如实回「未写入」',
    () async {
      if (!available) return;
      final ctx = await open();
      expect(await ctx.runner.startExport(), isTrue);

      expect(await ctx.runner.startDeploy(), isTrue);
      expect(ctx.runner.last!.kind, Methods.deploy);
      expect(ctx.runner.deploy, isNotNull);
      expect(ctx.runner.deploy!.synced, 0, reason: '夹具没有配置部署目录');
      expect(ctx.runner.last!.message, '目标已是最新，未写入');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );

  test(
    '过滤条件由内核裁决：单表导出 tables=1，未知表/语言被内核拒绝',
    () async {
      if (!available) return;
      final ctx = await open();

      ctx.runner.table = 'Item';
      expect(await ctx.runner.startExport(), isTrue);
      expect(ctx.runner.result!.tables, 1);

      ctx.runner.table = 'NoSuchTable';
      expect(await ctx.runner.startExport(), isFalse, reason: '未知表名应由内核拒绝');
      expect(ctx.runner.phase, RunnerPhase.failed);
      expect(ctx.runner.error, contains('不存在'));

      ctx.runner
        ..table = null
        ..lang = 'xx';
      expect(await ctx.runner.startExport(), isFalse);
      expect(ctx.runner.error, contains('语言'));
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );

  test(
    '终态之后的取消不改写成功：客户端不发请求，内核回绝陌生 requestId',
    () async {
      if (!available) return;
      final ctx = await open();
      expect(await ctx.runner.startExport(), isTrue);
      expect(ctx.runner.phase, RunnerPhase.succeeded);

      // 任务已终态：取消必须是空操作，不能把成功改写成取消
      await ctx.runner.cancel();
      expect(ctx.runner.phase, RunnerPhase.succeeded);
      expect(ctx.runner.cancelState, isNull);
      expect(ctx.runner.last!.phase, RunnerPhase.succeeded);

      // 内核侧：本连接没见过的 requestId 得到 unknown_request，而不是伪造的 cancelling
      final reply = await ctx.worker.query(
        Methods.cancel,
        params: const {'targetRequestId': 9999},
        workspaceRoot: ctx.ws.path,
      );
      expect(reply, 'unknown_request');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );
}
