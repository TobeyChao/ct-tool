import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/state/validate_runner.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_export_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 导出页的校验入口（任务 5.4 前置）：按钮、内核摘要、写任务互斥与问题定位。
class _FakeGateway implements KernelGateway {
  _FakeGateway(this.reply);

  final Map<String, Object?> reply;
  int validateCalls = 0;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-v';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    if (method == Methods.validate) {
      validateCalls += 1;
      return reply;
    }
    return <String, Object?>{};
  }
}

void main() {
  late _FakeGateway gateway;
  late ExportRunner runner;
  late ValidateRunner validate;

  Future<void> pump(
    WidgetTester tester, {
    RunnerPhase phase = RunnerPhase.idle,
  }) async {
    runner.phase = phase;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: WorkbenchExportView(
            runner: runner,
            validate: validate,
            tables: const ['Item'],
            languages: const ['en'],
            onLocateIssue: (_) {},
          ),
        ),
      ),
    );
    await tester.pump();
  }

  setUp(() {
    gateway = _FakeGateway(const {'ok': true, 'issues': <Object?>[]});
    runner = ExportRunner(worker: gateway, workspaceRoot: 'D:/ws');
    validate = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
  });
  tearDown(() {
    runner.dispose();
    validate.dispose();
  });

  testWidgets('校验按钮发内核请求并渲染其摘要', (tester) async {
    await pump(tester);
    expect(find.byKey(const ValueKey('wb.validateResult')), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(const ValueKey('wb.validateResult'))).data,
      '未校验',
    );

    await tester.tap(find.byKey(const ValueKey('wb.validateRun')));
    await tester.pumpAndSettle();

    expect(gateway.validateCalls, 1);
    final label = tester
        .widget<Text>(find.byKey(const ValueKey('wb.validateResult')))
        .data!;
    expect(label, contains('校验通过'));
    expect(label, contains('问题 0 个'));
    expect(label, contains('ms'), reason: '耗时来自真实计时，不是装饰');
  });

  testWidgets('内核报问题时逐条列出并可定位', (tester) async {
    gateway = _FakeGateway({
      'ok': false,
      'issues': [
        {'code': 'type', 'message': 'Bad 不是 int32', 'resource': 'Item'},
      ],
    });
    validate = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
    await pump(tester);
    await tester.tap(find.byKey(const ValueKey('wb.validateRun')));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.validateIssue.0')), findsOneWidget);
    expect(find.textContaining('Bad 不是 int32'), findsOneWidget);
    await tester.tap(find.text('定位'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('校验未通过（全库，问题 1 个'),
      findsOneWidget,
      reason: '未通过就写未通过，不改口径',
    );
  });

  testWidgets('写任务进行中：校验禁用并说明原因', (tester) async {
    // 首帧即运行中：断言入口互斥本身，不启动真实导出任务。
    await pump(tester, phase: RunnerPhase.running);
    expect(
      tester
          .widget<CtButton>(find.byKey(const ValueKey('wb.validateRun')))
          .onPressed,
      isNull,
      reason: '有写任务在跑时不得并发校验',
    );
    expect(
      find.byKey(const ValueKey('wb.validateQueued')),
      findsOneWidget,
      reason: '禁用必须说原因，不能只变灰',
    );
    expect(gateway.validateCalls, 0);
  });
}
