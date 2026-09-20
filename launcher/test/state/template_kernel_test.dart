import 'dart:io';

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/template_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 模板预检/生成直连真实 `ct worker`（任务 3.6 的内核侧证据）。
///
/// 关键点：保存 YAML 不会创建 Excel；只有显式生成才建工作簿；
/// 缺迁移依据时预检阻塞、生成请求根本发不出去，原工作簿一字节不动。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({Directory ws, WorkerService worker})> boot() async {
    final ws = await Directory.systemTemp.createTemp('ct-template-');
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
    return (ws: ws, worker: worker);
  }

  Future<void> shutdown(({Directory ws, WorkerService worker}) ctx) async {
    await ctx.worker.stop();
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  test(
    '保存 YAML 不建 Excel；显式预检+生成才创建工作簿，且不碰别人的工作簿',
    () async {
      if (!available) return;
      final ctx = await boot();
      final repo = WorkbenchRepository(worker: ctx.worker);
      await repo.switchWorkspace(ctx.ws.path);
      final itemBefore = File(
        '${ctx.ws.path}/excel/Item.xlsx',
      ).readAsBytesSync();

      // 用草稿命令新建一张表并保存（YAML-only）。
      repo.createTable('Quest');
      final candidate = await repo.requestCandidate();
      expect(candidate, isNotNull, reason: repo.draftError);
      expect(
        candidate!.problems.where((p) => p.resource != 'schemaRevision'),
        isEmpty,
        reason: '${candidate.problems.map((p) => p.message).toList()}',
      );
      expect(await repo.saveDraft(), isNotNull, reason: repo.saveError);
      expect(
        File('${ctx.ws.path}/config/schemas/quest.yaml').existsSync(),
        isTrue,
        reason: '保存应落 YAML',
      );
      final questExcel = File('${ctx.ws.path}/excel/Quest.xlsx');
      expect(questExcel.existsSync(), isFalse, reason: '保存不许顺手创建 Excel');

      final service = TemplateService(
        worker: ctx.worker,
        workspaceRoot: ctx.ws.path,
      );
      final plan = await service.runPlan('Quest');
      expect(plan, isNotNull, reason: service.error);
      expect(plan!.canGenerate, isTrue, reason: '${plan.problems}');
      expect(
        plan.actions.any((a) => a.contains('空模板')),
        isTrue,
        reason: '工作簿不存在时应给出建空模板的动作：${plan.actions}',
      );

      final done = await service.runGenerate();
      expect(done, isNotNull, reason: service.error);
      expect(questExcel.existsSync(), isTrue, reason: '显式生成之后才有工作簿');
      expect(
        File('${ctx.ws.path}/excel/Item.xlsx').readAsBytesSync(),
        itemBefore,
        reason: '生成 Quest 模板不得改写 Item 的工作簿',
      );
      expect(service.plan, isNotNull, reason: '生成后必须重新预检状态');

      service.dispose();
      repo.dispose();
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );

  test(
    '缺迁移依据时预检阻塞、生成请求发不出去，原工作簿保持不变',
    () async {
      if (!available) return;
      final ctx = await boot();
      final excel = File('${ctx.ws.path}/excel/Item.xlsx');
      final before = excel.readAsBytesSync();
      // 抹掉布局 manifest：内核没有安全迁移依据。
      File('${ctx.ws.path}/excel/layout_manifests/item.json').deleteSync();

      final service = TemplateService(
        worker: ctx.worker,
        workspaceRoot: ctx.ws.path,
      );
      final plan = await service.runPlan('Item');
      expect(plan, isNotNull, reason: service.error);
      expect(
        plan!.canGenerate,
        isFalse,
        reason: '没有 manifest 却允许生成就是撒谎：${plan.actions}',
      );
      expect(
        plan.problems.map((p) => p.message).join(' / '),
        contains('manifest'),
      );
      expect(service.canGenerate, isFalse);
      expect(await service.runGenerate(), isNull, reason: '阻塞时不许发写请求');
      expect(excel.readAsBytesSync(), before, reason: 'Excel 一字节不动');
      service.dispose();
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '模板只作用于 Table：对 Enum 预检由内核直接拒绝',
    () async {
      if (!available) return;
      final ctx = await boot();
      final service = TemplateService(
        worker: ctx.worker,
        workspaceRoot: ctx.ws.path,
      );
      expect(await service.runPlan('Rarity'), isNull);
      expect(service.error, contains('不存在'), reason: service.error);
      expect(service.canGenerate, isFalse);
      service.dispose();
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
