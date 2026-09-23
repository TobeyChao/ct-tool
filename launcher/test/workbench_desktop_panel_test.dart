import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_desktop_panel.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 桌面状态面板（任务 4.5/4.8 的界面侧）：有界日志列表与筛选、任务问题与关闭、
/// 历史最近 5 条与旧状态码归一，以及工作台底部任务区的接入。
class _FakeGateway implements KernelGateway {
  final List<String> calls = [];
  int dismissals = 0;
  int issuesCalls = 0;
  bool dismissed = false;

  @override
  WorkerStatus status = WorkerStatus.ready;

  @override
  String? failureReason;

  @override
  String? lastWorkspaceId = 'ws-panel';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(method);
    final page = (params['page'] as Map<String, Object?>?) ?? const {};
    switch (method) {
      case Methods.logsList:
        final first = page['cursor'] == null;
        final filtered = params.containsKey('module');
        return {
          'entries': [
            for (var i = 0; i < (first ? 120 : 30); i++)
              {
                'ts': '2026-09-18T10:00:00Z',
                'module': filtered ? 'export' : (i.isEven ? 'export' : 'i18n'),
                'level': 'info',
                'message': '日志行 $i',
                'requestId': 3,
              },
          ],
          'revision': 5,
          if (first && !filtered) 'nextCursor': 'cursor-2',
        };
      case Methods.historyList:
        return {
          'entries': [
            {
              'time': '2026-09-18T10:00:00Z',
              'scope': 'all',
              'result': 'success',
              'tables': 2,
              'elapsed': 1.25,
              'forced': false,
              'error': '',
            },
            {
              'time': '2026-09-17T08:00:00Z',
              'scope': 'table:Item',
              'result': 'ok',
              'tables': 1,
              'elapsed': 0.5,
              'forced': true,
              'error': '',
            },
          ],
        };
      case Methods.tasksList:
        return {
          'tasks': [
            {
              'id': 'task-9',
              'requestId': 3,
              'method': 'export',
              'status': 'error',
              'message': '校验失败',
              'startedAt': 1760000000.0,
              'dismissed': dismissed,
            },
          ],
        };
      case Methods.tasksIssues:
        issuesCalls++;
        return {
          'issues': [
            {
              'code': 'bad-enum',
              'message': 'Quality 不在 Enum Rarity 的声明值中',
              'resource': 'table:Item',
              'fieldPath': 'Quality',
              'excelRow': 4,
            },
          ],
          'revision': 5,
        };
      case Methods.tasksDismiss:
        dismissals++;
        dismissed = true;
        return {'outcome': 'dismissed'};
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late _FakeGateway gateway;
  late DesktopStateRepository state;

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    gateway = _FakeGateway();
    state = DesktopStateRepository(worker: gateway);
    await state.bind('D:/game/gd');
  });

  Future<void> pumpPanel(WidgetTester tester, Widget child) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(body: SizedBox(height: 520, child: child)),
      ),
    );
    await tester.pump();
  }

  testWidgets('日志页有界分页：可滚动并继续加载，筛选由内核执行', (tester) async {
    await pumpPanel(tester, WorkbenchLogView(state: state));
    expect(find.byKey(const ValueKey('wb.logList')), findsOneWidget);
    expect(state.logs.length, 120);
    expect(state.logsHasMore, isTrue);
    // 有界列表：加载更多的入口在列表末尾，滚到底才可见。
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('wb.loadMoreLogs')),
      400,
      scrollable: find.descendant(
        of: find.byKey(const ValueKey('wb.logList')),
        matching: find.byType(Scrollable),
      ),
    );
    expect(find.byKey(const ValueKey('wb.loadMoreLogs')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.loadMoreLogs')));
    await tester.pumpAndSettle();
    expect(state.logs.length, 150);
    expect(state.logsHasMore, isFalse);

    await tester.tap(find.byKey(const ValueKey('wb.logModule.export')));
    await tester.pumpAndSettle();
    expect(state.logs.every((log) => log.module == 'export'), isTrue);
    expect(
      gateway.calls.where((c) => c == Methods.logsList).length,
      greaterThanOrEqualTo(3),
    );
  });

  testWidgets('历史页显示最近记录并归一旧状态码', (tester) async {
    await pumpPanel(tester, WorkbenchHistoryView(state: state));
    expect(find.textContaining('all · 2 张表'), findsOneWidget);
    expect(find.textContaining('成功'), findsWidgets);
    expect(
      find.textContaining('未知（ok）'),
      findsOneWidget,
      reason: '旧状态码不得被当成内核当前状态，也不能报错',
    );
    expect(find.textContaining('table:Item · 1 张表'), findsOneWidget);
    expect(find.textContaining('强制重建'), findsOneWidget);
  });

  testWidgets('工作台侧栏接入日志与历史模块', (tester) async {
    final workbench = WorkbenchRepository(worker: gateway);
    final settings = SettingsStore();
    await settings.load();
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: workbench,
          refresh: Listenable.merge([workbench, state]),
          desktop: state,
          settings: settings,
          workspaceKey: 'panel-test',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('wb.navTap.日志')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.logModule')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.logList')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.navTap.历史')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.historyModule')), findsOneWidget);
    expect(find.textContaining('未知（ok）'), findsOneWidget);
    workbench.dispose();
  });
}
