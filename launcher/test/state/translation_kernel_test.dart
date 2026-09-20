import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 翻译页直连真实 `ct worker`（任务 4.1–4.3 的内核侧证据）。
///
/// 覆盖：译文与状态由内核给出、筛选在内核执行、单条保存只改该语言文件、
/// sync 重建 source、compact 先预检后执行且牵连不到别的条目。
/// 全程只写临时目录，绝不碰真实 gd/。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({Directory ws, WorkerService worker, TranslationRepository repo})>
  open() async {
    final ws = await Directory.systemTemp.createTemp('ct-i18n-');
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
    final repo = TranslationRepository(worker: worker);
    await repo.bind(ws.path);
    await repo.selectTable('Item');
    return (ws: ws, worker: worker, repo: repo);
  }

  Future<void> close(
    ({Directory ws, WorkerService worker, TranslationRepository repo}) ctx,
  ) async {
    await ctx.worker.stop();
    ctx.repo.dispose();
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  String describe(TranslationRepository repo) =>
      'entries=${repo.entries.map((e) => '${e.key}:${e.status.wire}').toList()} '
      'langs=${repo.langs.map((l) => l.lang).toList()} error=${repo.error}';

  Map<String, Object?> readLang(Directory ws) =>
      jsonDecode(File('${ws.path}/i18n/en/Item.json').readAsStringSync())!
          as Map<String, Object?>;

  void writeLang(Directory ws, Map<String, Object?> data) => File(
    '${ws.path}/i18n/en/Item.json',
  ).writeAsStringSync(const JsonEncoder.withIndent('  ').convert(data));

  test(
    '译文条目与状态由内核给出，状态筛选在内核执行',
    () async {
      if (!available) return;
      final ctx = await open();

      expect(ctx.repo.langNames, contains('en'), reason: describe(ctx.repo));
      expect(
        ctx.repo.entries.map((e) => e.key),
        containsAll(<String>['1001.Name', '1002.Name']),
        reason: describe(ctx.repo),
      );
      // 夹具没有 i18n/source：内核把这些译文判成 orphan，界面不自己改判。
      expect(
        ctx.repo.entries.every((e) => e.status == I18nStatus.orphan),
        isTrue,
        reason: describe(ctx.repo),
      );

      await ctx.repo.sync();
      await ctx.repo.refresh();
      expect(
        ctx.repo.entries.any((e) => e.status == I18nStatus.translated),
        isTrue,
        reason: '同步后应出现真实状态：${describe(ctx.repo)}',
      );

      await ctx.repo.selectFilter(TranslationFilter.translated);
      expect(ctx.repo.entries, isNotEmpty, reason: describe(ctx.repo));
      expect(
        ctx.repo.entries.every((e) => e.status == I18nStatus.translated),
        isTrue,
        reason: '筛选必须由内核执行：${describe(ctx.repo)}',
      );

      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '单条保存只改该语言文件，状态由内核重判',
    () async {
      if (!available) return;
      final ctx = await open();
      final yamlBefore = File(
        '${ctx.ws.path}/config/schemas/item.yaml',
      ).readAsBytesSync();
      final excelBefore = File(
        '${ctx.ws.path}/excel/Item.xlsx',
      ).readAsBytesSync();

      expect(
        await ctx.repo.saveRow(
          key: '1002.Name',
          text: 'Iron Shield',
          confirmed: true,
        ),
        isTrue,
        reason: describe(ctx.repo),
      );
      final saved = readLang(ctx.ws)['1002.Name']! as Map<String, Object?>;
      expect(saved['text'], 'Iron Shield');
      expect(saved['confirmed'], isTrue);
      expect(saved['status'], isNot('missing'), reason: '内核重判后的状态应写进文件：$saved');

      final row = ctx.repo.entries.firstWhere((e) => e.key == '1002.Name');
      expect(row.status, isNot(I18nStatus.missing));
      expect(
        File('${ctx.ws.path}/config/schemas/item.yaml').readAsBytesSync(),
        yamlBefore,
        reason: '保存译文不得碰 schema',
      );
      expect(
        File('${ctx.ws.path}/excel/Item.xlsx').readAsBytesSync(),
        excelBefore,
        reason: '保存译文不得碰 Excel',
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    'sync 重建 source 集合，之后进度总览有真实计数',
    () async {
      if (!available) return;
      final ctx = await open();
      expect(
        File('${ctx.ws.path}/i18n/source/Item.json').existsSync(),
        isFalse,
        reason: '夹具不带 source 文件',
      );

      final result = await ctx.repo.sync();
      expect(result, isNotNull, reason: ctx.repo.error);
      expect(
        File('${ctx.ws.path}/i18n/source/Item.json').existsSync(),
        isTrue,
        reason: 'sync 必须由内核重建 source',
      );
      expect(ctx.repo.notice, contains('已同步'));

      await ctx.repo.refresh();
      final en = ctx.repo.langs.firstWhere((l) => l.lang == 'en');
      expect(
        en.translated + en.missing + en.stale + en.orphan,
        greaterThan(0),
        reason: '同步后进度总览必须有真实计数：${describe(ctx.repo)}',
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    'compact 预检只报告不写盘，显式执行才删孤立且不牵连其它条目',
    () async {
      if (!available) return;
      final ctx = await open();
      // source 缺失时内核不做清理（安全默认）：先 sync 建立 source 再制造孤立。
      await ctx.repo.sync();
      final data = readLang(ctx.ws);
      data['9999.Name'] = {
        'confirmed': false,
        'source': '幽灵',
        'status': 'missing',
        'text': 'Ghost',
      };
      writeLang(ctx.ws, data);

      final plan = await ctx.repo.compactPreview();
      expect(plan, isNotNull, reason: ctx.repo.error);
      expect(plan!.dryRun, isTrue);
      expect(plan.entries, contains('9999.Name'), reason: '预检应给出将被删的键');
      expect(
        readLang(ctx.ws).containsKey('9999.Name'),
        isTrue,
        reason: '预检绝不写盘',
      );

      final applied = await ctx.repo.compactApply();
      expect(applied, isNotNull, reason: ctx.repo.error);
      expect(applied!.removed, greaterThanOrEqualTo(1));
      expect(applied.dryRun, isFalse);
      final after = readLang(ctx.ws);
      expect(after.containsKey('9999.Name'), isFalse);
      expect(after.containsKey('1001.Name'), isTrue, reason: '清理不得牵连其它条目');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '未知语言由内核拒绝，界面不谎报保存成功',
    () async {
      if (!available) return;
      final ctx = await open();
      await ctx.repo.sync();
      await ctx.repo.selectLang('xx');
      expect(ctx.repo.entries, isNotEmpty, reason: describe(ctx.repo));

      final ok = await ctx.repo.saveRow(
        key: ctx.repo.entries.first.key,
        text: 'x',
        confirmed: false,
      );
      expect(ok, isFalse, reason: '未知语言不得算保存成功');
      expect(ctx.repo.error, contains('语言'), reason: describe(ctx.repo));
      expect(readLang(ctx.ws)['1001.Name'], isNotNull, reason: '被拒的保存不得改语言文件');
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    'source 缺失时内核不肯清理：预检返回空且不删任何东西',
    () async {
      if (!available) return;
      final ctx = await open();
      final plan = await ctx.repo.compactPreview();
      expect(plan, isNotNull, reason: ctx.repo.error);
      expect(
        plan!.entries,
        isEmpty,
        reason: '没有 source 时不能把所有译文当孤立删掉：${describe(ctx.repo)}',
      );
      expect(readLang(ctx.ws).containsKey('1001.Name'), isTrue);
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
