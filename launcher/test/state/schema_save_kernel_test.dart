import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 双守卫保存（native-flutter-workbench 任务 3.4）与候选呈现（3.3）——直连真实 `ct worker`。
///
/// 关注三件事：保存只写 YAML；任何拒绝路径都不动文件、保留草稿；
/// 以及「新增后删除归零」「候选刷新不改变基线」这两条净差异约束。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({WorkbenchRepository repo, WorkerService worker, Directory ws})> open(
    String? copyFrom,
  ) async {
    final ws = await Directory.systemTemp.createTemp('ct-save-');
    if (copyFrom == null) {
      Directory('${ws.path}/config/schemas').createSync(recursive: true);
      File(
        '${ws.path}/config/global.yaml',
      ).writeAsStringSync('primary_lang: zh\n');
    } else {
      final source = Directory(copyFrom);
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
    return (repo: repo, worker: worker, ws: ws);
  }

  Future<void> shutdown(
    ({WorkbenchRepository repo, WorkerService worker, Directory ws}) ctx,
  ) async {
    await ctx.worker.stop();
    ctx.repo.dispose();
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  Map<String, String> digestConfig(Directory ws) {
    final out = <String, String>{};
    for (final entity in Directory(
      '${ws.path}/config',
    ).listSync(recursive: true)) {
      if (entity is! File) continue;
      final key = entity.path
          .substring(ws.path.length + 1)
          .replaceAll('\\', '/');
      out[key] = cryptoSha256(entity.readAsBytesSync());
    }
    return out;
  }

  test(
    '保存成功：只写 YAML，草稿清空、清单改由内核提供、基线推进',
    () async {
      if (!available) return;
      final ctx = await open(null);
      ctx.repo.createTable('Hero');
      ctx.repo.createRecord('Loot');
      ctx.repo.createEnum('Rarity');
      final candidate = await ctx.repo.requestCandidate();
      expect(candidate, isNotNull, reason: ctx.repo.draftError ?? '');
      expect(ctx.repo.canSave, isTrue);

      final result = await ctx.repo.saveDraft();
      expect(result, isNotNull, reason: ctx.repo.saveError ?? '');
      expect(result!.schemaRevision.length, 64);
      expect(ctx.repo.saveError, isNull);
      expect(ctx.repo.draftCount, 0, reason: '保存成功后草稿应已提交');
      expect(
        ctx.repo.resources.map((r) => r.name).toList(),
        containsAll(['Hero', 'Loot', 'Rarity']),
      );
      expect(
        ctx.repo.resources.every((r) => !r.dirty),
        isTrue,
        reason: '清单已来自磁盘，不应再标草稿',
      );

      // YAML-only：不得创建/改写 Excel、翻译、产物或缓存
      for (final dir in ['excel', 'i18n', 'output', 'cache']) {
        expect(
          Directory('${ctx.ws.path}/$dir').existsSync(),
          isFalse,
          reason: '保存只允许写 schema YAML，$dir 不该被创建',
        );
      }
      // `.ct` 是工具私有目录（工作区锁等），但保存事务必须自行收尾、不留 journal
      expect(
        File('${ctx.ws.path}/.ct/export-publication.json').existsSync(),
        isFalse,
        reason: '保存不得留下未完成的发布材料',
      );
      expect(
        File('${ctx.ws.path}/config/schemas/hero.yaml').existsSync(),
        isTrue,
      );
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '外部改动使旧基线被拒：不动文件、草稿保留、基线刷新',
    () async {
      if (!available) return;
      final ctx = await open(null);
      ctx.repo.createTable('Hero');
      await ctx.repo.requestCandidate();
      final before = digestConfig(ctx.ws);

      // 外部改一个 schema 成员（模拟并行编辑），保存必须拒绝
      File('${ctx.ws.path}/config/schemas/outsider.yaml').writeAsStringSync(
        'table: Outsider\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n',
      );
      final result = await ctx.repo.saveDraft();

      expect(result, isNull);
      expect(ctx.repo.saveError, isNotNull, reason: '旧基线保存必须被拒');
      expect(ctx.repo.draftCount, 1, reason: '拒绝时草稿必须保留');
      expect(
        File('${ctx.ws.path}/config/schemas/outsider.yaml').existsSync(),
        isTrue,
        reason: '不得覆盖外部修改',
      );
      expect(
        File('${ctx.ws.path}/config/schemas/hero.yaml').existsSync(),
        isFalse,
        reason: '被拒的保存不得留下任何 YAML 写入',
      );
      for (final entry in before.entries) {
        final file = File('${ctx.ws.path}/${entry.key}');
        expect(
          cryptoSha256(file.readAsBytesSync()),
          entry.value,
          reason: '${entry.key} 不应被改写',
        );
      }
      // 基线已刷新：重算候选后即可保存
      expect(ctx.repo.candidate, isNull, reason: '旧候选应作废');
      expect(ctx.repo.schemaBaseline.length, 64);
      final recalc = await ctx.repo.requestCandidate();
      expect(recalc, isNotNull, reason: ctx.repo.draftError ?? '');
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '候选哈希不符：内核拒绝且不写文件（客户端不自行判断）',
    () async {
      if (!available) return;
      final ctx = await open(null);
      final files = digestConfig(ctx.ws);
      Object? caught;
      try {
        await ctx.worker.request(
          Methods.schemaSave,
          params: const {
            'schemaRevision': 'baseline-not-used',
            'candidateHash':
                'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
            'commands': <Object?>[],
            'cursor': '0',
          },
          workspaceRoot: ctx.ws.path,
        );
      } on WorkerRequestException catch (e) {
        caught = e;
      }
      expect(caught, isA<WorkerRequestException>());
      expect(
        (caught! as WorkerRequestException).issues,
        isNotEmpty,
        reason: '拒绝必须带结构化明细，界面不必解析日志',
      );
      expect(digestConfig(ctx.ws), files, reason: '拒绝路径不得留下文件改动');
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '净差异：新增后再删除应归零；候选刷新不改变基线',
    () async {
      if (!available) return;
      final ctx = await open(null);
      ctx.repo.createTable('Temp');
      ctx.repo.deleteResource('table:Temp');
      final candidate = await ctx.repo.requestCandidate();
      expect(candidate, isNotNull, reason: ctx.repo.draftError ?? '');
      final diff = candidate!.netDiff;
      expect(
        diff.added.length + diff.removed.length + diff.changed.length,
        0,
        reason: '一加一删净差异应为零：$diff',
      );

      ctx.repo.createTable('Keeper');
      final baseline = ctx.repo.schemaBaseline;
      final first = await ctx.repo.requestCandidate();
      expect(first, isNotNull);
      final second = await ctx.repo.requestCandidate();
      expect(second!.candidateHash, first!.candidateHash);
      expect(ctx.repo.schemaBaseline, baseline, reason: '候选刷新不得推进基线');
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '写任务占用工作区时保存被拒且保留草稿',
    () async {
      if (!available) return;
      final fixture = Directory('../native/fixtures/export_pipeline/workspace');
      final ctx = await open(fixture.path);
      ctx.repo.createTable('WhileBusy');
      await ctx.repo.requestCandidate();
      expect(ctx.repo.canSave, isTrue);

      // 先占住写任务（导出是写任务，会持有工作区锁）
      final running = ctx.worker.request(
        Methods.export,
        workspaceRoot: ctx.ws.path,
      );
      final result = await ctx.repo.saveDraft();
      await running;

      expect(result, isNull, reason: '工作区忙时保存不应落盘');
      expect(ctx.repo.saveError, isNotNull);
      expect(ctx.repo.draftCount, 1, reason: '无论拒绝原因是什么，草稿都必须保留');
      expect(
        File('${ctx.ws.path}/config/schemas/whilebusy.yaml').existsSync(),
        isFalse,
      );
      await shutdown(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}

/// 内容指纹（FNV-1a + 长度）：测试只用于判断文件有没有被改动。
String cryptoSha256(List<int> bytes) {
  var hash = 0x811c9dc5;
  for (final byte in bytes) {
    hash = ((hash ^ byte) * 0x01000193) & 0xFFFFFFFF;
  }
  return '${hash.toRadixString(16).padLeft(8, '0')}-${bytes.length}';
}
