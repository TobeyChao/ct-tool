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
      calls.where((call) => call.method == method).toList();

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

Finder inCard(String key, String text) =>
    find.descendant(of: find.byKey(ValueKey(key)), matching: find.text(text));

void main() {
  late _FakeGateway gateway;
  late ExportRunner runner;
  late WorkbenchScreen screen;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    gateway = _FakeGateway();
    runner = ExportRunner(worker: gateway, workspaceRoot: 'E:/ws/gd');
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

  TextButton buttonOf(WidgetTester tester, String key) =>
      tester.widget<TextButton>(
        find.descendant(
          of: find.byKey(ValueKey(key)),
          matching: find.byType(TextButton),
        ),
      );

  testWidgets('导出页按 Web 收敛：只剩进度、上下文和三个动作', (tester) async {
    await openExport(tester);

    expect(find.byKey(const ValueKey('wb.exportProgress')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.exportContext')), findsOneWidget);
    expect(find.text('强制全量重建'), findsOneWidget);
    expect(find.text('开始导出'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.exportFilters')), findsNothing);
    expect(find.byKey(const ValueKey('wb.exportResult')), findsNothing);
    expect(find.byKey(const ValueKey('wb.exportLog')), findsNothing);
    expect(find.byKey(const ValueKey('wb.deployRun')), findsNothing);
    expect(find.byKey(const ValueKey('wb.validateRun')), findsNothing);

    gateway.replies[Methods.export] = exportPayload();
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pumpAndSettle();

    expect(gateway.of(Methods.export).single.params, {'all': false});
    expect(find.text('导出成功'), findsOneWidget);
    expect(find.text('重新导出'), findsOneWidget);
    expect(inCard('wb.exportProgress', 'parse'), findsOneWidget);
    expect(inCard('wb.exportProgress', 'generate'), findsWidgets);
    expect(inCard('wb.exportProgress', '32ms'), findsOneWidget);
    expect(find.text('成功 · 3 张表 · 0.04s'), findsOneWidget);
  });

  testWidgets('强制全量重建直接以 all=true 发起导出', (tester) async {
    await openExport(tester);
    gateway.replies[Methods.export] = exportPayload();

    await tester.tap(find.byKey(const ValueKey('wb.exportForce')));
    await tester.pumpAndSettle();

    expect(gateway.of(Methods.export).single.params, {'all': true});
    expect(find.text('强制全量重建'), findsWidgets);
  });

  testWidgets('写入口不可用时给出原因并禁用两个导出动作', (tester) async {
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
    expect(buttonOf(tester, 'wb.exportForce').onPressed, isNull);
  });

  testWidgets('运行器异步到货后，导出页从 MOCK 占位切到真实页面', (tester) async {
    ExportRunner? lateRunner;
    late StateSetter rebuild;
    final data = const StaticWorkbenchData(
      workspaceName: 'gd',
      workspacePath: 'E:/ws/gd',
      resources: [
        WorkbenchResource(
          name: 'Hero',
          kind: WorkbenchResourceKind.table,
          path: 'config/schemas/hero.yaml',
        ),
      ],
    );
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: StatefulBuilder(
          builder: (context, setState) {
            rebuild = setState;
            return WorkbenchScreen(data: data, runner: lateRunner);
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.rocket_launch_outlined));
    await tester.pumpAndSettle();
    expect(find.textContaining('当前为界面样板'), findsOneWidget);

    lateRunner = runner;
    rebuild(() {});
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.exportView')), findsOneWidget);
    expect(find.textContaining('当前为界面样板'), findsNothing);
  });

  testWidgets('取消只在运行期出现，首个带 requestId 的事件后可用', (tester) async {
    await openExport(tester);
    gateway.heldFor[Methods.export] = Completer<Object?>();
    gateway.replies[Methods.cancel] = 'cancelling';

    expect(find.byKey(const ValueKey('wb.exportCancel')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.exportCancel')), findsOneWidget);
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
    expect(inCard('wb.exportProgress', 'generate 3/8'), findsOneWidget);
    expect(buttonOf(tester, 'wb.exportCancel').onPressed, isNotNull);

    await tester.tap(find.byKey(const ValueKey('wb.exportCancel')));
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.cancel).single.params, {'targetRequestId': 21});

    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await tester.pumpAndSettle();
    expect(find.text('导出成功'), findsOneWidget, reason: '取消意图不改写成功终态');
  });

  testWidgets('失败与结构化问题都进入执行进度，不再单独占卡', (tester) async {
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

    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pumpAndSettle();
    expect(find.text('type-mismatch：atk 期望 int'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.exportIssue.0')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.exportIssues')), findsNothing);

    gateway.failures[Methods.export] = const ErrorBody(
      code: 'internal',
      message: '生成器失败',
    );
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pumpAndSettle();
    expect(find.text('internal：生成器失败'), findsOneWidget);
    expect(find.text('导出中止'), findsOneWidget);
    expect(inCard('wb.exportProgress', '生成器失败'), findsOneWidget);
  });

  testWidgets('断连后标为终态未知并明确不自动重放', (tester) async {
    await openExport(tester);
    gateway.heldFor[Methods.export] = Completer<Object?>();
    await tester.tap(find.byKey(const ValueKey('wb.exportRun')));
    await tester.pump();

    runner.markDisconnected();
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.exportUnknown')), findsOneWidget);
    expect(find.textContaining('没有自动重放写请求'), findsWidgets);
    expect(find.byKey(const ValueKey('wb.exportPhase')), findsOneWidget);
    expect(find.text('终态未知'), findsWidgets);

    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.export), hasLength(1));
    expect(find.text('0.04s'), findsNothing, reason: '迟到的终态不得生成成功统计');
    expect(find.textContaining('连接已断开，任务终态未知'), findsWidgets);
  });
}
