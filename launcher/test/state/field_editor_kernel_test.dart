import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 字段类型/属性/索引编辑直连真实 `ct worker`（任务 3.2 的内核裁决证据）。
///
/// 客户端不做第二套校验：非法组合必须被内核候选拦住并且**存不下去**，
/// 合法组合则只改 YAML，不碰 Excel、翻译与导出产物。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({Directory ws, WorkerService worker, WorkbenchRepository repo})>
  open() async {
    final ws = await Directory.systemTemp.createTemp('ct-field-editor-');
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
    final repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(ws.path);
    await repo.loadPreview('Item');
    return (ws: ws, worker: worker, repo: repo);
  }

  Future<void> close(
    ({Directory ws, WorkerService worker, WorkbenchRepository repo}) ctx,
  ) async {
    await ctx.worker.stop();
    ctx.repo.dispose();
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  String readYaml(Directory ws) =>
      File('${ws.path}/config/schemas/item.yaml').readAsStringSync();

  test(
    '内核状态回显：字段属性与已声明索引都来自预览与清单',
    () async {
      if (!available) return;
      final ctx = await open();
      final item = ctx.repo.resourceNamed('Item')!;
      expect(item.fields.map((f) => f.name), contains('Name'));
      expect(
        item.fields.firstWhere((f) => f.name == 'Name').localized,
        isTrue,
        reason: '夹具里 Name 标了 i18n',
      );
      expect(item.fields.first.role, 'primary');
      expect(item.indexes, ['codename'], reason: 'resources.list 必须带出索引');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '非法组合被内核候选拦住且保存被拒，草稿原样保留',
    () async {
      if (!available) return;
      final ctx = await open();
      final before = readYaml(ctx.ws);

      // Name 已经是 i18n：再标 server_only 就是内核禁止的组合
      ctx.repo.setFieldProperty('table:Item', 'Name', 'server_only', true);
      await ctx.repo.requestCandidate();
      // 内核要么返回带阻塞问题的候选，要么直接拒绝候选请求：两种都必须留下明细。
      final problems = ctx.repo.candidateProblems;
      expect(problems, isNotEmpty, reason: ctx.repo.draftError ?? '候选返回了空问题清单');
      expect(
        problems.map((p) => p.message).join(' / '),
        contains('server_only'),
      );
      expect(ctx.repo.problemsFor('table:Item', fieldName: 'Name'), isNotEmpty);
      expect(ctx.repo.canSave, isFalse, reason: '非法组合不许进入保存');

      expect(await ctx.repo.saveDraft(), isNull, reason: '有问题不许落盘');
      expect(readYaml(ctx.ws), before, reason: '被拒的保存不得改 YAML');
      expect(ctx.repo.draftCount, 1, reason: '草稿必须留着让用户改');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '展开组数只适用于 vector：类型不符由内核拒绝',
    () async {
      if (!available) return;
      final ctx = await open();
      ctx.repo.setFieldProperty('table:Item', 'Price', 'excel_columns', 3);
      final candidate = await ctx.repo.requestCandidate();
      expect(candidate!.problems, isNotEmpty);
      expect(
        candidate.problems.map((p) => p.message).join(' / '),
        contains('vector'),
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '只移除 codename 索引也计入净差异并可保存',
    () async {
      if (!available) return;
      final ctx = await open();
      ctx.repo.setTableIndexes('table:Item', const []);

      final candidate = await ctx.repo.requestCandidate();
      expect(candidate, isNotNull, reason: ctx.repo.draftError ?? 'no error');
      expect(
        candidate!.netDiff.changed.map((r) => r.name),
        contains('Item'),
        reason: '索引也是候选结构的一部分，不能报零差异',
      );
      expect(ctx.repo.canSave, isTrue);

      final saved = await ctx.repo.saveDraft();
      expect(saved, isNotNull, reason: ctx.repo.saveError);
      expect(readYaml(ctx.ws), isNot(contains('codename')));
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '合法编辑保存只改 YAML：注释、类型与移除索引都落盘',
    () async {
      if (!available) return;
      final ctx = await open();
      final excelBefore = File(
        '${ctx.ws.path}/excel/Item.xlsx',
      ).readAsBytesSync().length;

      ctx.repo
        ..setFieldType('table:Item', 'Price', 'int64')
        ..setFieldProperty('table:Item', 'Price', 'comment', '单价')
        ..setTableIndexes('table:Item', const []);
      final candidate = await ctx.repo.requestCandidate();
      expect(candidate, isNotNull, reason: ctx.repo.draftError ?? 'no error');
      expect(
        candidate!.problems.where((p) => p.resource != 'schemaRevision'),
        isEmpty,
        reason: '${candidate.problems.map((p) => p.message).toList()}',
      );
      expect(candidate.netDiff.changed.map((r) => r.name), contains('Item'));

      final saved = await ctx.repo.saveDraft();
      expect(saved, isNotNull, reason: ctx.repo.saveError);
      final yaml = readYaml(ctx.ws);
      expect(yaml, contains('int64'));
      expect(yaml, contains('单价'));
      expect(yaml, isNot(contains('codename')), reason: '索引声明已移除');
      expect(
        File('${ctx.ws.path}/excel/Item.xlsx').readAsBytesSync().length,
        excelBefore,
        reason: '保存不许碰 Excel',
      );
      expect(
        ctx.repo.resourceNamed('Item')!.indexes,
        isEmpty,
        reason: '重读后的状态必须来自内核',
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );

  test(
    '枚举成员改名 ordinal 错位由内核直接拒绝',
    () async {
      if (!available) return;
      final ctx = await open();
      ctx.repo.renameEnumItem('enum:Rarity', 'NotThere', 'Oops', 7);
      var threw = false;
      try {
        await ctx.worker.query(
          Methods.schemaCandidate,
          params: {
            'schemaRevision': ctx.repo.schemaBaseline,
            'commands': [
              {
                'kind': 'rename_enum_item',
                'payload': {
                  'name': 'enum:Rarity',
                  'oldName': 'NotThere',
                  'newName': 'Oops',
                  'originalOrdinal': 7,
                },
              },
            ],
            'cursor': '1',
            'draftGeneration': 1,
          },
          workspaceRoot: ctx.ws.path,
        );
      } on WorkerRequestException catch (e) {
        threw = true;
        expect(e.message, contains('ordinal'));
      }
      expect(threw, isTrue, reason: 'ordinal 不一致必须由内核拒绝');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
