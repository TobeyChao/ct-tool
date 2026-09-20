import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 预览分页的界面侧证据（任务 5.2）：页脚状态、按钮可用性与续页后的行数。
class _FakeGateway implements KernelGateway {
  final List<Map<String, Object?>> previews = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-pg';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 4,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        return {
          'revision': 4,
          'schemaRevision': 'baseline-pg',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.tablePreview:
        previews.add(Map<String, Object?>.from(params));
        final hasCursor = (params['page']! as Map)['cursor'] != null;
        return {
          'revision': 4,
          'columns': [
            {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
          ],
          'rows': [
            for (var i = 0; i < (hasCursor ? 20 : 50); i++) ['r$i'],
          ],
          'nextCursor': hasCursor ? null : 'c1',
        };
      default:
        return <String, Object?>{};
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _FakeGateway gateway;
  late WorkbenchRepository repo;
  late SettingsStore settings;

  Future<void> pumpScreen(WidgetTester tester) async {
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
          onResourceSelected: (name) => repo.loadPreview(name),
          workspaceKey: 'paging-test',
          bannerLabel: '已连接原生内核',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  setUp(() async {
    SharedPreferences.setMockInitialValues({'workspace_path': 'D:/game/gd'});
    settings = SettingsStore();
    await settings.load();
    gateway = _FakeGateway();
    repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
  });

  tearDown(() => repo.dispose());

  testWidgets('预览页脚：还有更多时可点，续页后变末页并禁用', (tester) async {
    await pumpScreen(tester);
    await repo.loadPreview('Item');
    await tester.pump();
    await tester.tap(find.text('数据预览'));
    await tester.pump();

    Text footer() =>
        tester.widget<Text>(find.byKey(const ValueKey('wb.previewCount')));
    expect(footer().data, contains('50'));
    expect(footer().data, contains('还有更多'));

    final more = find.byKey(const ValueKey('wb.previewMore'));
    expect(tester.widget<IconButton>(more).onPressed, isNotNull);
    await tester.tap(more);
    await tester.pumpAndSettle();

    expect(repo.previewOf('Item')!.rows, hasLength(70));
    expect(footer().data, contains('70'));
    expect(footer().data, contains('已到末页'));
    expect(
      tester.widget<IconButton>(more).onPressed,
      isNull,
      reason: '末页必须禁用，不能让人反复敲内核',
    );
    expect(gateway.previews, hasLength(2));
  });

  testWidgets('未连接内核（样板数据）时页脚如实说明', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(data: repo, refresh: repo, settings: settings),
      ),
    );
    await tester.pump();
    await repo.loadPreview('Item');
    await tester.pump();
    await tester.tap(find.text('数据预览'));
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.previewMore')), findsOneWidget);
  });
}
