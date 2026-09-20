import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 桌面全链路串测（native-flutter-workbench 任务 5.4）：
/// 创建 → 保存 → 模板预检/生成 → 校验 → 导出（全量+增量）→ 翻译（sync/查询/保存）→ 独立部署，
/// 全部经真实 `ct worker` 的 NDJSON 协议在临时工作区里跑，逐步验证产物与账本。
///
/// 诚实边界：Excel 数据行由 openpyxl 夹具提供，"人手工往新列填数"这一步不能从协议层完成；
/// 本用例改为验证 schema 迁移**保住了既有 2 行数据**并把新增 i18n 列纳入 sync/翻译范围，
/// 界面截图证据见 `test/e2e_workbench_chain_screens_test.dart`（同一条链，10 张 PNG + 文本留档）；
/// 真机鼠标与输入法操作留在任务 5.1/5.5。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  late Directory ws;
  late Directory unity;
  late WorkerService worker;
  late WorkbenchRepository repo;
  late TranslationRepository translations;

  Future<void> copyFixture() async {
    ws = await Directory.systemTemp.createTemp('ct-e2e-');
    unity = await Directory.systemTemp.createTemp('ct-e2e-unity-');
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
    // 打开部署目标：独立部署必须真的把产物送到 Unity 工程目录
    final cfg = File('${ws.path}/config/global.yaml');
    final deployYaml = <String>[
      '',
      'deploy:',
      '  enabled: true',
      '  unity_project: ${unity.path.replaceAll(Platform.pathSeparator, '/')}',
      '  targets:',
      '    - {source: output/binary, dest: Assets/Content/Config}',
      '    - {source: output/generated/csharp, dest: Assets/Scripts/Config/Gen}',
      '',
    ].join('\n');
    final before = cfg.readAsStringSync();
    cfg.writeAsStringSync('$before$deployYaml');
  }

  setUpAll(() async {
    if (!available) return;
    await copyFixture();
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
    repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(ws.path);
    await repo.reloadPreview('Item');
    translations = TranslationRepository(worker: worker);
    await translations.bind(ws.path);
  });

  tearDownAll(() async {
    if (!available) return;
    await worker.stop();
    repo.dispose();
    translations.dispose();
    for (final dir in [ws, unity]) {
      try {
        dir.deleteSync(recursive: true);
      } on FileSystemException {
        // 交给系统临时目录回收
      }
    }
  });

  final payloadDump = <Object?>[];

  String read(String relative) =>
      File('${ws.path}/$relative').readAsStringSync();

  test('0. 缺原生二进制时整条串测显式跳过', () async {
    if (!available) markTestSkipped(skipReason);
  });

  test('1. 创建：草稿命令进清单，候选无阻塞问题', () async {
    if (!available) return;
    final item = repo.resourceNamed('Item')!;
    expect(item.fields.map((f) => f.name), contains('Name'));
    expect(item.indexes, ['codename'], reason: '索引状态来自内核清单');

    repo
      ..addField('table:Item', 'Note', 'string', i18n: true)
      ..createTable('Quest');
    final found = await repo.requestCandidate();
    expect(found, isNotNull, reason: repo.draftError);
    expect(
      found!.problems,
      isEmpty,
      reason: '${found.problems.map((p) => p.message).toList()}',
    );
    expect(found.netDiff.changed.map((r) => r.name), contains('Item'));
    expect(found.netDiff.added.map((r) => r.name), contains('Quest'));
    expect(repo.canSave, isTrue);
  });

  test('2. 保存：只改 YAML，Excel 与产物都不动', () async {
    if (!available) return;
    final excelBefore = File('${ws.path}/excel/Item.xlsx').readAsBytesSync();
    final i18nBefore = read('i18n/en/Item.json');
    final baselineBefore = repo.schemaBaseline;

    final saved = await repo.saveDraft();
    expect(saved, isNotNull, reason: repo.saveError);
    expect(saved!.schemaRevision, isNotEmpty);
    expect(repo.schemaBaseline, isNot(baselineBefore), reason: '基线随提交推进');
    expect(repo.draftCount, 0);

    final yaml = read('config/schemas/item.yaml');
    expect(yaml, contains('Note'));
    expect(File('${ws.path}/config/schemas/quest.yaml').existsSync(), isTrue);
    expect(
      File('${ws.path}/excel/Item.xlsx').readAsBytesSync(),
      excelBefore,
      reason: '保存不得改 Excel',
    );
    expect(read('i18n/en/Item.json'), i18nBefore, reason: '保存不得改翻译');
    expect(
      Directory('${ws.path}/output').existsSync(),
      isFalse,
      reason: '保存不产生产物',
    );
  });

  test('3. 模板：预检放行后生成，迁移保住既有数据行；新表建空模板', () async {
    if (!available) return;
    final plan = await worker.query(
      Methods.templatePlan,
      params: const {'table': 'Item'},
      workspaceRoot: ws.path,
    );
    final item = TemplatePlanResult.fromJson(plan! as Map<String, Object?>);
    expect(
      item.canGenerate,
      isTrue,
      reason:
          '有 manifest 的表应可安全迁移：${item.problems.map((p) => p.message).toList()}',
    );
    expect(item.actions.join(' '), contains('迁移'));

    await worker.query(
      Methods.templateGenerate,
      params: const {'table': 'Item'},
      workspaceRoot: ws.path,
    );
    await repo.reloadPreview('Item');
    final preview = repo.previewOf('Item')!;
    expect(preview.rows, hasLength(2), reason: '模板迁移必须保住既有 2 行数据');
    expect(preview.columns.map((c) => c.name), contains('Note'));

    final questPlan = TemplatePlanResult.fromJson(
      (await worker.query(
            Methods.templatePlan,
            params: const {'table': 'Quest'},
            workspaceRoot: ws.path,
          ))!
          as Map<String, Object?>,
    );
    expect(questPlan.canGenerate, isTrue);
    expect(questPlan.actions.join(' '), contains('空模板'));
    await worker.query(
      Methods.templateGenerate,
      params: const {'table': 'Quest'},
      workspaceRoot: ws.path,
    );
    expect(File('${ws.path}/excel/Quest.xlsx').existsSync(), isTrue);
    // 回归钉：模板生成只动 Excel 与 manifest，不碰任何表的 schema YAML。
    expect(
      File('${ws.path}/config/schemas/quest.yaml').existsSync(),
      isTrue,
      reason: '生成新表模板后 schema 必须在',
    );
    expect(
      Directory('${ws.path}/config/schemas').listSync(),
      hasLength(2),
      reason: 'schema 目录成员不该被模板生成增删',
    );
  });

  test('4. 校验闸门：整表结构通过，无问题', () async {
    if (!available) return;
    final payload = await worker.query(
      Methods.validate,
      workspaceRoot: ws.path,
    );
    final result = ValidateResult.fromJson(payload! as Map<String, Object?>);
    expect(
      result.issues,
      isEmpty,
      reason: '${result.issues.map((i) => i.message).toList()}',
    );
    expect(result.ok, isTrue);
    // 校验闸门同样是只读的：跑完 schema 成员不变。
    expect(Directory('${ws.path}/config/schemas').listSync(), hasLength(2));
  });

  test('5. 导出：全量出产物并记账，再跑一次走增量复用', () async {
    if (!available) return;
    expect(
      Directory('${ws.path}/config/schemas').listSync(),
      hasLength(2),
      reason: '导出前 schema 成员仍完整（回归钉：曾经一次性的消失）',
    );

    final firstRaw = await worker.query(
      Methods.export,
      params: const {'all': true},
      workspaceRoot: ws.path,
    );
    payloadDump.add(firstRaw);
    final first = ExportResult.fromJson(
      (await worker.query(
            Methods.export,
            params: const {'all': true},
            workspaceRoot: ws.path,
          ))!
          as Map<String, Object?>,
    );
    expect(first.outcome, TaskOutcome.succeeded);
    expect(
      first.tables,
      greaterThanOrEqualTo(2),
      reason: jsonEncode(payloadDump.first),
    );
    expect(first.durationMs, greaterThan(0));
    expect(first.stages, isNotEmpty);
    expect(
      File('${ws.path}/output/json/Item_zh.json').existsSync(),
      isTrue,
      reason: '新增列之后 JSON 产物仍按语言落地',
    );
    expect(File('${ws.path}/output/json/Quest_zh.json').existsSync(), isTrue);
    expect(
      File('${ws.path}/output/generated/csharp/QuestAccessor.cs').existsSync(),
      isTrue,
    );
    expect(read('output/json/Item_zh.json'), contains('Note'));

    final again = ExportResult.fromJson(
      (await worker.query(
            Methods.export,
            params: const {'all': false},
            workspaceRoot: ws.path,
          ))!
          as Map<String, Object?>,
    );
    expect(again.outcome, TaskOutcome.succeeded);
    expect(
      (again.cache!.hits + again.cache!.misses),
      greaterThan(0),
      reason: '增量导出必须报出生成缓存统计',
    );
    expect(again.cache!.hits, greaterThan(0), reason: '未变化的表应复用缓存');
  });

  test('6. 翻译：sync 纳入新增列，查询与单条保存回写状态', () async {
    if (!available) return;
    await translations.selectTable('Item');
    final synced = await translations.sync();
    expect(synced, isNotNull, reason: translations.error);
    expect(File('${ws.path}/i18n/source/Item.json').existsSync(), isTrue);

    await translations.refresh();
    expect(
      translations.entries.map((e) => e.key),
      contains('1001.Note'),
      reason: '新增 i18n 列必须由 sync 进入翻译范围',
    );
    await translations.selectFilter(TranslationFilter.missing);
    expect(translations.entries, isNotEmpty);
    expect(
      translations.entries.every((e) => e.status == I18nStatus.missing),
      isTrue,
      reason: '筛选由内核执行',
    );

    final target = translations.entries.first;
    expect(
      await translations.saveRow(
        key: target.key,
        text: 'e2e-note',
        confirmed: true,
      ),
      isTrue,
      reason: translations.error,
    );
    final stored =
        jsonDecode(read('i18n/en/Item.json'))! as Map<String, Object?>;
    final entry = stored[target.key]! as Map<String, Object?>;
    expect(entry['text'], 'e2e-note');
    expect(entry['confirmed'], isTrue);
    expect(entry['status'], isNot('missing'));
  });

  test('7. 独立部署：产物落到 Unity 目标目录，再部署一次报未变更', () async {
    if (!available) return;
    final first = DeployResult.fromJson(
      (await worker.query(
            Methods.deploy,
            params: const {'forBuild': false},
            workspaceRoot: ws.path,
          ))!
          as Map<String, Object?>,
    );
    expect(first.unchanged, isFalse, reason: '首次部署应有同步文件');
    expect(
      Directory(
        '${unity.path}/Assets/Content/Config',
      ).listSync(recursive: true).whereType<File>(),
      isNotEmpty,
      reason: 'binary 产物应出现在 Unity 目录',
    );
    expect(
      File(
        '${unity.path}/Assets/Scripts/Config/Gen/QuestAccessor.cs',
      ).existsSync(),
      isTrue,
      reason: 'C# Accessor 也应被部署',
    );

    final second = DeployResult.fromJson(
      (await worker.query(
            Methods.deploy,
            params: const {'forBuild': false},
            workspaceRoot: ws.path,
          ))!
          as Map<String, Object?>,
    );
    expect(second.unchanged, isTrue, reason: '内容未变时不重复写入');
  });

  test('8. 生命周期：历史/任务/日志三张表都记到了这次链路', () async {
    if (!available) return;
    // 直接走桌面状态仓库：与工作台用的是同一条读取路径。
    final desktop = DesktopStateRepository(worker: worker);
    await desktop.bind(ws.path);
    expect(desktop.history, isNotEmpty, reason: '桌面导出应写最近五条历史');
    expect(desktop.history.first.result, 'success');
    expect(desktop.history.first.tables, greaterThanOrEqualTo(2));
    final methods = desktop.tasks.map((t) => t.method).toSet();
    expect(
      methods,
      containsAll(<String>[Methods.export, Methods.deploy]),
      reason: '任务账本要含本次的导出与独立部署',
    );
    await desktop.setLogFilter(module: 'export');
    expect(desktop.logs, isNotEmpty, reason: '导出阶段日志应可按模块筛选');
    expect(
      desktop.logs.every((l) => l.module == 'export'),
      isTrue,
      reason: '筛选必须由内核执行',
    );
    desktop.dispose();
  });
  test('9. 收尾：不留发布残留，工作区账本一致', () async {
    if (!available) return;
    final leftovers = Directory(ws.path)
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.contains('.ct-stage-') || f.path.endsWith('.tmp'))
        .toList();
    expect(leftovers, isEmpty, reason: '发布完成后不该有暂存残留');
    expect(repo.draftCount, 0);
    expect(repo.hasDraftConflict, isFalse);
    expect(repo.draftPersisted, isTrue);
  });
}
