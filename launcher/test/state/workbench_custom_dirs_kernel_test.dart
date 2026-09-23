import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 非默认配置目录下的概览 / 预览 / 历史（任务 5.7）。
///
/// 全部经真实 `ct worker`：界面拿到的路径、计数、预览列和历史记录都必须是内核回包，
/// 不允许像旧 StatsService 那样自己扫 `config/schemas`、`output/json`。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();

  late Directory ws;
  late WorkerService worker;
  late WorkbenchRepository repo;
  late DesktopStateRepository desktop;

  // 故意全部换成非默认目录，并且混中文段名。
  const layout = {
    'schemas': 'meta/schemas',
    'types': 'meta/types',
    'excel': '表格',
    'i18n': '翻译',
    'output': '产物',
    'cache': '缓存',
  };

  setUpAll(() async {
    if (!available) return;
    ws = await Directory.systemTemp.createTemp('ct-dirs-');
    Directory('${ws.path}/config').createSync(recursive: true);
    Directory('${ws.path}/${layout['schemas']}').createSync(recursive: true);
    Directory('${ws.path}/${layout['types']}').createSync(recursive: true);
    File('${ws.path}/config/global.yaml').writeAsStringSync(
      'primary_lang: zh\n'
      'secondary_langs:\n  - en\n'
      'schemas_dir: ${layout['schemas']}\n'
      'types_dir: ${layout['types']}\n'
      'excel_dir: ${layout['excel']}\n'
      'i18n_dir: ${layout['i18n']}\n'
      'output_dir: ${layout['output']}\n'
      'cache_dir: ${layout['cache']}\n',
    );
    File('${ws.path}/${layout['schemas']}/item.yaml').writeAsStringSync(
      'table: Item\n'
      'primary: Id\n'
      'fields:\n'
      '  - name: Id\n    type: int32\n'
      '  - name: Name\n    type: string\n    i18n: true\n',
    );
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
    desktop = DesktopStateRepository(worker: worker);
  });

  tearDownAll(() async {
    if (!available) return;
    await worker.stop();
    repo.dispose();
    desktop.dispose();
    try {
      ws.deleteSync(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  });

  test('概览与清单：路径与计数都来自内核，非默认目录如实反映', () async {
    if (!available) return;
    final item = repo.resources.single;
    expect(item.name, 'Item');
    expect(
      item.path,
      '${layout['schemas']}/item.yaml',
      reason: 'sourcePath 必须由 resources.list 给出，而不是拼 config/schemas',
    );
    expect(
      repo.resources.where((r) => r.kind == WorkbenchResourceKind.table),
      hasLength(1),
      reason: '分类计数由内核清单算出，不扫目录',
    );
    expect(
      repo.resources.where((r) => r.kind != WorkbenchResourceKind.table),
      isEmpty,
    );
    expect(
      repo.schemaRevision,
      greaterThan(0),
      reason: '代次来自 workspace.open 回包',
    );
    expect(repo.schemaBaseline.length, 64, reason: '基线摘要来自 resources.list');
    // 默认目录根本不存在，任何硬编码扫描都会得出 0 或空。
    expect(Directory('${ws.path}/config/schemas').existsSync(), isFalse);
    expect(Directory('${ws.path}/excel').existsSync(), isFalse);
  });

  test('预览：内核在非默认 excel_dir 上建模板并回列', () async {
    if (!available) return;
    await worker.query(
      Methods.templateGenerate,
      params: const {'table': 'Item'},
      workspaceRoot: ws.path,
    );
    expect(
      File('${ws.path}/${layout['excel']}/Item.xlsx').existsSync(),
      isTrue,
      reason: '模板应落在配置的 excel_dir，而不是默认 excel/',
    );
    await repo.loadPreview('Item');
    final preview = repo.previewOf('Item');
    expect(preview, isNotNull);
    expect(preview!.columns.map((c) => c.name), containsAll(['Id', 'Name']));
    expect(repo.resources.single.previewColumns, contains('Name'));
  });

  test('导出与历史：产物进非默认 output_dir，历史/日志由内核方法提供', () async {
    if (!available) return;
    final raw = await worker.query(
      Methods.export,
      params: const {'all': true},
      workspaceRoot: ws.path,
    );
    final result = ExportResult.fromJson(raw! as Map<String, Object?>);
    expect(result.outcome, TaskOutcome.succeeded);
    expect(
      File('${ws.path}/${layout['output']}/json/Item_zh.json').existsSync(),
      isTrue,
      reason: 'JSON 产物应进配置的 output_dir',
    );
    expect(Directory('${ws.path}/output').existsSync(), isFalse);

    await desktop.bind(ws.path);
    expect(desktop.history, isNotEmpty, reason: 'history.list 要记到这次导出');
    expect(desktop.history.first.result, 'success');
    expect(
      desktop.tasks.map((t) => t.method),
      contains(Methods.export),
      reason: '任务账本来自 tasks.list，不是本地猜的',
    );
    await desktop.setLogFilter(module: 'export');
    expect(desktop.logs, isNotEmpty);
  });

  testWidgets('界面显示的就是内核给的非默认路径（无 StatsService 兜底）', (tester) async {
    if (!available) return;
    SharedPreferences.setMockInitialValues({'workspace_path': ws.path});
    final settings = SettingsStore();
    await settings.load();
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: repo,
          refresh: repo,
          draft: repo,
          settings: settings,
          workspaceKey: 'dirs-test',
          bannerLabel: '已连接原生内核',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('meta/schemas/item.yaml'), findsWidgets);
    expect(find.textContaining('config/schemas'), findsNothing);
  });
}
