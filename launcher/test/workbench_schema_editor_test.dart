import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 资源区里的草稿编辑面板（native-flutter-workbench 任务 3.1 的界面侧证据）。
class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<Map<String, Object?>> candidates = [];
  final List<Map<String, Object?>> saves = [];

  @override
  WorkerStatus status = WorkerStatus.ready;

  @override
  String? failureReason;

  @override
  String? lastWorkspaceId = 'ws-edit';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 3,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        return {
          'revision': 3,
          'schemaRevision': 'baseline-sha',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.schemaSave:
        saves.add(params);
        return {
          'schemaRevision': 'new-baseline-000000000000000000000000000000',
        };
      case Methods.schemaCandidate:
        candidates.add(params);
        return {
          'candidateHash': 'hash-edit',
          'draftGeneration': params['draftGeneration'],
          'netDiff': {
            'added': [
              {'kind': 'table', 'name': 'Hero'},
            ],
            'removed': <Object?>[],
            'changed': <Object?>[],
          },
          'problems': <Object?>[],
        };
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _FakeGateway gateway;
  late WorkbenchRepository repo;
  late SettingsStore settings;

  Future<void> pumpEditor(WidgetTester tester) async {
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
          workspaceKey: 'editor-test',
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

  testWidgets('资源区挂着编辑面板，未选中资源时改名/删除禁用', (tester) async {
    await pumpEditor(tester);
    expect(find.byKey(const ValueKey('wb.schemaEditor')), findsOneWidget);
    expect(find.text('草稿 0 条'), findsOneWidget);
    expect(
      tester
          .widget<ActionChip>(find.byKey(const ValueKey('wb.newTable')))
          .onPressed,
      isNotNull,
    );
  });

  testWidgets('新建 Table 走对话框入草稿，清单立刻出现草稿资源', (tester) async {
    await pumpEditor(tester);
    await tester.tap(find.byKey(const ValueKey('wb.newTable')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.nameField')), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('wb.nameField')), 'Hero');
    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();

    expect(find.text('草稿 1 条'), findsOneWidget);
    expect(find.textContaining('Hero'), findsWidgets);
    expect(repo.resources.last.dirty, isTrue);
    expect(repo.commands.single.kind, 'add_resource');
  });

  testWidgets('算候选把守卫参数送内核并回显净差异', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('wb.candidate')));
    await tester.pumpAndSettle();

    expect(find.textContaining('净差异 新增1'), findsOneWidget);
    final sent = gateway.candidates.single;
    expect(sent['schemaRevision'], 'baseline-sha');
    expect(sent['cursor'], '1');
    expect(sent['draftGeneration'], 1);
  });

  testWidgets('撤销/重做/丢弃都反映到清单与按钮可用性', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pump();
    expect(find.textContaining('Hero'), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('wb.undo')));
    await tester.pump();
    expect(find.text('草稿 0 条'), findsOneWidget);
    expect(find.textContaining('Hero'), findsNothing);
    expect(find.byKey(const ValueKey('wb.redo')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.redo')));
    await tester.pump();
    expect(find.text('草稿 1 条'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.discard')));
    await tester.pump();
    expect(find.text('草稿 0 条'), findsOneWidget);
    expect(repo.hasDraft, isFalse);
  });

  testWidgets('改名作用于选中资源，删除走内核 id', (tester) async {
    await pumpEditor(tester);
    // 默认选中清单里第一个资源（Item）
    await tester.tap(find.byKey(const ValueKey('wb.renameResource')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('wb.nameField')), 'Gear');
    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();
    expect(repo.resources.single.name, 'Gear');
    expect(find.textContaining('Gear'), findsWidgets);

    await repo.requestCandidate();
    repo.deleteResource('table:Gear');
    await tester.pump();
    expect(repo.resources, isEmpty);
    expect(
      repo.commands.last.payload['name'],
      'table:Gear',
      reason: '删除命令必须带内核 id 形态',
    );
  });

  testWidgets('真实草稿下保存走双守卫请求，成功后清空草稿', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pump();

    TextButton saveButton() =>
        tester.widget<TextButton>(find.byKey(const ValueKey('wb.draftSave')));
    expect(saveButton().onPressed, isNull, reason: '还没算候选时不得允许保存');

    await repo.requestCandidate();
    await tester.pump();
    expect(saveButton().onPressed, isNotNull);
    await tester.tap(find.byKey(const ValueKey('wb.draftSave')));
    await tester.pumpAndSettle();

    final sent = gateway.saves.single;
    expect(sent['schemaRevision'], 'baseline-sha');
    expect(sent['candidateHash'], 'hash-edit');
    expect(sent['commands'], hasLength(1));
    expect(sent['cursor'], '1');
    expect(find.text('草稿 0 条'), findsOneWidget);
    expect(repo.draftCount, 0);
  });

  testWidgets('差异按钮弹出内核净差异与问题计数', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pump();
    // 差异入口已收进全局草稿条（工具条不再放第二份）
    await tester.tap(find.byKey(const ValueKey('wb.draftSummaryTap')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('净差异'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.candidateHash')), findsOneWidget);
    expect(find.textContaining('candidateHash hash-edit'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.diff.added')), findsOneWidget);
    expect(find.text('新增 1'), findsOneWidget);
    expect(find.text('阻塞问题 0'), findsOneWidget);
  });
}
