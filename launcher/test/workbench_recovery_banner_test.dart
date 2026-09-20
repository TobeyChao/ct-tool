import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 总览里的发布事务恢复横幅（任务 4.7 的界面侧证据）。
class _FakeGateway implements KernelGateway {
  final List<String> methods = [];
  bool pending = true;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-banner';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    methods.add(method);
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 4,
          'status': pending ? 'recovery_needed' : 'ready',
          'recovery': {
            'needed': pending,
            'journals': pending ? ['publish-7.json'] : <String>[],
          },
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        return {
          'revision': 4,
          'schemaRevision': 'baseline-banner',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.workspaceRecover:
        pending = false;
        return {'outcome': 'recovered', 'revision': 5, 'detail': '已还原 2 个文件'};
      default:
        throw StateError('未预期的调用：$method');
    }
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('有待恢复事务时总览给出横幅，点恢复后按内核结果消失', (tester) async {
    final gw = _FakeGateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace('D:/game/A');
    addTearDown(repo.dispose);

    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(data: repo, refresh: repo, draft: repo),
      ),
    );
    await tester.pumpAndSettle();
    // 首屏预选 Schema 模块，先切到总览
    await tester.tap(find.byIcon(Icons.dashboard_outlined));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.recoveryBanner')), findsOneWidget);
    expect(find.textContaining('publish-7.json'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.recover')));
    await tester.pumpAndSettle();

    expect(gw.methods, contains(Methods.workspaceRecover));
    expect(
      find.byKey(const ValueKey('wb.recoveryBanner')),
      findsNothing,
      reason: '恢复结果由内核快照决定，界面不自己清横幅',
    );
  });

  testWidgets('没有待恢复事务时不显示横幅', (tester) async {
    final gw = _FakeGateway()..pending = false;
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace('D:/game/A');
    addTearDown(repo.dispose);

    tester.view.physicalSize = const Size(1400, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(data: repo, refresh: repo, draft: repo),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.dashboard_outlined));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.recoveryBanner')), findsNothing);
  });
}
