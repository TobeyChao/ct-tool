import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _Call {
  _Call(this.method, this.params);
  final String method;
  final Map<String, Object?> params;
}

class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<_Call> calls = [];
  final Map<String, Object?> replies = {};
  final Map<String, ErrorBody> failures = {};
  final Map<String, Completer<Object?>> heldFor = {};

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-export';

  List<_Call> of(String method) =>
      calls.where((c) => c.method == method).toList();

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(_Call(method, params));
    final failure = failures[method];
    if (failure != null) throw WorkerRequestException(failure);
    final gate = heldFor[method];
    if (gate != null) return gate.future;
    return replies[method];
  }
}

Map<String, Object?> exportPayload({List<Object?> issues = const []}) => {
  'outcome': 'succeeded',
  'tables': 3,
  'durationMs': 42,
  'stages': [
    {'name': 'parse', 'elapsedMs': 10},
    {'name': 'generate', 'elapsedMs': 32},
  ],
  'cache': {'hits': 5, 'misses': 2},
  'issues': issues,
};

/// 限定在某张卡片（按 Key）里找文本：运行日志里会出现同一行，全局查找会有歧义。
Finder inCard(String key, String text) =>
    find.descendant(of: find.byKey(ValueKey(key)), matching: find.text(text));

void main() {
  late _FakeGateway gateway;
  late ExportRunner runner;
  late List<String> opened;
  late WorkbenchScreen screen;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    gateway = _FakeGateway();
    runner = ExportRunner(worker: gateway, workspaceRoot: 'E:/ws/gd');
    opened = [];
    screen = WorkbenchScreen(
      data: const StaticWorkbenchData(
        workspaceName: 'gd',
        workspacePath: 'E:/ws/gd',
        schemaRevision: 7,
        resources: [
          WorkbenchResource(
            name: 'Hero',
            kind: WorkbenchResourceKind.table,
            path: 'config/schemas/hero.yaml',
          ),
          WorkbenchResource(
            name: 'Item',
            kind: WorkbenchResourceKind.table,
            path: 'config/schemas/item.yaml',
          ),
        ],
      ),
      runner: runner,
      exportLanguages: const ['en', 'ja'],
      onResourceSelected: opened.add,
    );
  });

  tearDown(() {
    runner.dispose();
  });

  Future<void> openExport(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(theme: buildCtTheme(), home: screen));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.rocket_launch_outlined));
    await tester.pumpAndSettle();
  }

  Future<void> runButton(WidgetTester tester) async {
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pumpAndSettle();
  }

  TextButton buttonOf(WidgetTester tester, String key) =>
      tester.widget<TextButton>(
        find.descendant(
          of: find.byKey(ValueKey(key)),
          matching: find.byType(TextButton),
        ),
      );

  testWidgets('导出模块可操作：过滤条件、结果卡与阶段耗时全部来自内核回包', (tester) async {
    await openExport(tester);
    expect(find.byKey(const ValueKey('wb.exportFilters')), findsOneWidget);
    expect(find.text('强制重建（绕过缓存）'), findsOneWidget);

    // 选表：下拉最后一项是浮层里的菜单项
    await tester.tap(find.byKey(const ValueKey('wb.exportTable')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Item').last);
    await tester.pumpAndSettle();

    // 选语言
    await tester.tap(find.byKey(const ValueKey('wb.exportLang')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('ja').last);
    await tester.pumpAndSettle();

    gateway.replies[Methods.export] = exportPayload();
    await runButton(tester);

    expect(gateway.of(Methods.export), hasLength(1));
    expect(gateway.of(Methods.export).single.params, {
      'table': 'Item',
      'lang': 'ja',
      'all': false,
    }, reason: '过滤条件必须一比一送内核');
    expect(find.text('导出结果'), findsOneWidget);
    expect(find.text('42ms'), findsOneWidget);
    expect(find.text('5 / 2'), findsOneWidget);
    expect(find.text('parse'), findsOneWidget);
    expect(find.text('generate'), findsOneWidget);
    expect(inCard('wb.exportPhase', '成功'), findsOneWidget);
  });

  testWidgets('桌面导出不自动部署；独立部署是另一个按钮', (tester) async {
    await openExport(tester);
    gateway.replies[Methods.export] = exportPayload();
    gateway.replies[Methods.deploy] = {'synced': 12, 'unchanged': false};

    await runButton(tester);
    expect(gateway.of(Methods.deploy), isEmpty, reason: '导出不得顺带部署');

    await tester.tap(find.byKey(const ValueKey('wb.deployRun')));
    await tester.pumpAndSettle();
    final deploy = gateway.of(Methods.deploy);
    expect(deploy, hasLength(1));
    expect(deploy.single.params, {'forBuild': false});
    expect(inCard('wb.exportResult', '已同步 12 个文件'), findsOneWidget);
    expect(gateway.of(Methods.export), hasLength(1), reason: '部署不应重跑导出');
  });

  testWidgets('写入口不可用时给出原因并禁用按钮', (tester) async {
    screen = WorkbenchScreen(
      data: const StaticWorkbenchData(
        workspaceName: 'gd',
        workspacePath: 'E:/ws/gd',
        resources: [
          WorkbenchResource(
            name: 'Hero',
            kind: WorkbenchResourceKind.table,
            path: 'config/schemas/hero.yaml',
          ),
        ],
      ),
      runner: runner,
      writeBlockReason: '内核未就绪（协议不兼容）',
    );
    await openExport(tester);
    expect(find.text('内核未就绪（协议不兼容）'), findsOneWidget);
    expect(buttonOf(tester, 'wb.exportRun').onPressed, isNull);
    expect(buttonOf(tester, 'wb.deployRun').onPressed, isNull);
  });

  testWidgets('取消要等首个带 requestId 的事件，点击只转达意图', (tester) async {
    await openExport(tester);
    gateway.heldFor[Methods.export] = Completer<Object?>();
    gateway.replies[Methods.cancel] = 'cancelling';

    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pump();
    expect(buttonOf(tester, 'wb.exportCancel').onPressed, isNull);

    runner.onEvent(
      ProgressEvent(
        requestId: 21,
        workspaceId: 'ws-export',
        seq: 1,
        stage: 'generate',
        done: 3,
        total: 8,
      ),
    );
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.exportProgress')), findsOneWidget);
    expect(inCard('wb.exportProgress', 'generate 3/8'), findsOneWidget);
    expect(buttonOf(tester, 'wb.exportCancel').onPressed, isNotNull);

    await tester.tap(find.byKey(const ValueKey('wb.exportCancel')));
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.cancel).single.params, {'targetRequestId': 21});
    expect(find.textContaining('取消请求已转达内核'), findsOneWidget);

    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await tester.pumpAndSettle();
    expect(find.text('导出结果'), findsOneWidget, reason: '取消意图不改写成功终态');
  });

  testWidgets('结构化问题可定位：把内核给的 Issue 原样回传', (tester) async {
    await openExport(tester);
    gateway.replies[Methods.export] = exportPayload(
      issues: const [
        {
          'code': 'type-mismatch',
          'message': 'atk 期望 int',
          'resource': 'Hero',
          'fieldPath': 'atk',
          'excelRow': 7,
        },
      ],
    );
    await runButton(tester);

    expect(find.text('type-mismatch：atk 期望 int'), findsOneWidget);
    expect(find.textContaining('第 7 行'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wb.exportLocate.0')));
    await tester.pumpAndSettle();
    expect(opened, contains('Hero'), reason: '定位必须让壳层选中内核给的资源');
    // 定位后切到 Schema 模块，主编辑区选中该资源
    expect(find.byKey(const ValueKey('wb.exportView')), findsNothing);
  });

  testWidgets('失败终态显示错误码与问题明细，不显示成功', (tester) async {
    await openExport(tester);
    gateway.failures[Methods.export] = const ErrorBody(
      code: 'busy',
      message: '工作区被写任务占用',
    );
    await runButton(tester);
    expect(find.text('内核忙等：工作区被写任务占用'), findsOneWidget);
    expect(find.text('导出结果'), findsNothing);
    expect(find.text('空闲'), findsWidgets);
  });

  testWidgets('断连后标为终态未知并明确不自动重放', (tester) async {
    await openExport(tester);
    gateway.heldFor[Methods.export] = Completer<Object?>();
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pump();

    runner.markDisconnected();
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.exportUnknown')), findsOneWidget);
    expect(find.textContaining('未自动重放'), findsWidgets);
    expect(inCard('wb.exportPhase', '终态未知'), findsOneWidget);

    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.export), hasLength(1));
    expect(find.text('42ms'), findsNothing, reason: '迟到的终态不得生成成功统计');
    expect(inCard('wb.exportResult', '终态未知'), findsOneWidget);
    expect(find.textContaining('连接已断开，任务终态未知'), findsOneWidget);
  });
}
