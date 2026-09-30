import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:ct_launcher/ui/workbench/workbench_schema_editor.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 资源区里的草稿编辑面板（native-flutter-workbench 任务 3.1 的界面侧证据）。
class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<Map<String, Object?>> candidates = [];
  final List<Map<String, Object?>> saves = [];
  bool emptyResources = false;

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
          'resources': emptyResources
              ? <Object?>[]
              : [
                  {
                    'name': 'Item',
                    'kind': 'table',
                    'sourcePath': 'config/schemas/item.yaml',
                  },
                  {
                    'name': 'Reward',
                    'kind': 'record',
                    'sourcePath': 'config/schemas/reward.yaml',
                    'fields': [
                      {'name': 'Amount', 'type': 'int32'},
                    ],
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

  bool menuEnabled(WidgetTester tester, String keyName) => tester
      .widget<PopupMenuButton<String>>(find.byKey(ValueKey(keyName)))
      .enabled;

  Future<void> openResourceMenu(WidgetTester tester, String name) async {
    await tester.tap(find.text(name).first, buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
  }

  testWidgets('资源区保持新建入口，资源右键菜单提供常用操作', (tester) async {
    await pumpEditor(tester);
    expect(find.byKey(const ValueKey('wb.schemaEditor')), findsOneWidget);
    expect(find.text('草稿 0 条'), findsNothing);
    expect(menuEnabled(tester, 'wb.newMenu'), isTrue);

    await openResourceMenu(tester, 'Item');
    for (final key in const [
      'wb.resourceMenu.open',
      'wb.resourceMenu.addField',
      'wb.resourceMenu.rename',
      'wb.resourceMenu.copyId',
      'wb.resourceMenu.copyPath',
      'wb.resourceMenu.delete',
    ]) {
      expect(find.byKey(ValueKey(key)), findsOneWidget);
    }
  });

  testWidgets('无选中资源时新建入口仍可用', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(body: WorkbenchSchemaEditor(repo: repo)),
      ),
    );
    await tester.pump();
    expect(menuEnabled(tester, 'wb.newMenu'), isTrue);
    expect(find.byKey(const ValueKey('wb.resourceMenu')), findsNothing);
  });

  for (final (button, kind, name) in [
    ('wb.emptyNewTable', 'table', 'Hero'),
    ('wb.emptyNewRecord', 'record', 'Stats'),
    ('wb.emptyNewEnum', 'enum', 'Quality'),
  ]) {
    testWidgets('空工作区的 $kind 按钮复用真实草稿创建流程', (tester) async {
      gateway.emptyResources = true;
      await repo.switchWorkspace('D:/game/gd');
      await pumpEditor(tester);
      expect(repo.resources, isEmpty);
      await tester.tap(find.byKey(ValueKey(button)));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('wb.nameField')), findsOneWidget);
      await tester.enterText(find.byKey(const ValueKey('wb.nameField')), name);
      await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
      await tester.pumpAndSettle();
      expect(repo.commands.single.kind, 'add_resource');
      expect(repo.resources.single.name, name);
      expect(repo.resources.single.dirty, isTrue);
      expect(find.text('草稿 1 条'), findsOneWidget);
      expect(find.byKey(ValueKey(button)), findsNothing);
    });
  }

  testWidgets('未绑定工作区时新建不会加入草稿', (tester) async {
    repo.clearWorkspace();
    await pumpEditor(tester);
    await tester.tap(find.byKey(const ValueKey('wb.emptyNewTable')));
    await tester.pump();
    expect(find.text('请先在设置中绑定配表工作区'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.nameField')), findsNothing);
    expect(repo.commands, isEmpty);
  });

  testWidgets('资源列表空态的新建菜单也可加入草稿', (tester) async {
    gateway.emptyResources = true;
    await repo.switchWorkspace('D:/game/gd');
    await pumpEditor(tester);
    await tester.tap(find.byKey(const ValueKey('wb.emptyNewMenu')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('新建表').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('wb.nameField')), 'Hero');
    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();
    expect(repo.resources.single.name, 'Hero');
    expect(repo.commands.single.kind, 'add_resource');
  });

  testWidgets('新建 Table 走对话框入草稿，清单立刻出现草稿资源', (tester) async {
    await pumpEditor(tester);
    await tester.tap(find.byKey(const ValueKey('wb.newMenu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.newTable')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.nameField')), findsOneWidget);
    await tester.enterText(find.byKey(const ValueKey('wb.nameField')), 'Hero');
    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();

    expect(find.text('草稿 1 条'), findsOneWidget);
    expect(find.textContaining('Hero'), findsWidgets);
    expect(repo.resources.last.dirty, isTrue);
    expect(
      tester
          .widget<WorkbenchSchemaEditor>(
            find.byKey(const ValueKey('wb.schemaEditor')),
          )
          .selected,
      'Hero',
    );
    expect(repo.commands.single.kind, 'add_resource');
  });

  testWidgets('加字段用工作区具名类型与 vector 选择器，不再手填类型', (tester) async {
    await pumpEditor(tester);
    await openResourceMenu(tester, 'Item');
    await tester.tap(find.byKey(const ValueKey('wb.resourceMenu.addField')));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byKey(const ValueKey('wb.nameField')),
      'Rewards',
    );
    await tester.tap(find.byKey(const ValueKey('wb.addFieldType.base')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('wb.addFieldType.search')),
      'Reward',
    );
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const ValueKey('wb.addFieldType.option.Reward')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.addFieldType.vector')));
    await tester.pumpAndSettle();
    expect(find.text('vector<Reward>'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();
    final field = repo.commands.last.payload['field'] as Map<String, Object?>;
    expect(repo.commands.last.kind, 'add_field');
    expect(field['type'], 'vector<Reward>');
  });

  testWidgets('算候选把守卫参数送内核并回显净差异', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pumpAndSettle();
    expect(gateway.candidates, hasLength(1), reason: '编辑后自动算候选');
    await tester.tap(find.byKey(const ValueKey('wb.candidate')));
    await tester.pumpAndSettle();

    expect(find.textContaining('净差异 新增1'), findsOneWidget);
    expect(gateway.candidates, hasLength(2), reason: '工具栏按钮仍可显式重算');
    final sent = gateway.candidates.last;
    expect(sent['schemaRevision'], 'baseline-sha');
    expect(sent['cursor'], '1');
    expect(
      sent['draftGeneration'],
      greaterThan(gateway.candidates.first['draftGeneration']! as int),
      reason: '显式刷新使用新的候选代次，编辑和加载也会使代次递增',
    );
    expect(repo.candidate!.draftGeneration, sent['draftGeneration']);
  });

  testWidgets('撤销/重做/丢弃都反映到清单与按钮可用性', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pump();
    expect(find.textContaining('Hero'), findsWidgets);

    await tester.tap(find.byKey(const ValueKey('wb.undo')));
    await tester.pump();
    expect(find.text('草稿 0 条'), findsOneWidget, reason: '仍有可重做历史');
    expect(find.textContaining('Hero'), findsNothing);
    expect(find.byKey(const ValueKey('wb.redo')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.redo')));
    await tester.pump();
    expect(find.text('草稿 1 条'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.discard')));
    await tester.pumpAndSettle();
    expect(repo.hasDraft, isTrue, reason: '侧栏放弃草稿也必须先确认');
    await tester.tap(find.text('取消').last);
    await tester.pumpAndSettle();
    expect(repo.hasDraft, isTrue);
    await tester.tap(find.byKey(const ValueKey('wb.discard')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.draftDiscard.confirm')));
    await tester.pumpAndSettle();
    expect(find.text('草稿 0 条'), findsNothing);
    expect(repo.hasDraft, isFalse);
  });

  testWidgets('改名后仍选中新资源', (tester) async {
    await pumpEditor(tester);
    // 默认选中清单里第一个资源（Item）
    await openResourceMenu(tester, 'Item');
    await tester.tap(find.byKey(const ValueKey('wb.resourceMenu.rename')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const ValueKey('wb.nameField')), 'Gear');
    await tester.tap(find.byKey(const ValueKey('wb.dialogConfirm')));
    await tester.pumpAndSettle();
    expect(repo.resourceNamed('Gear'), isNotNull);
    expect(find.textContaining('Gear'), findsWidgets);
    expect(
      tester
          .widget<WorkbenchSchemaEditor>(
            find.byKey(const ValueKey('wb.schemaEditor')),
          )
          .selected,
      'Gear',
    );
  });

  testWidgets('删除选中资源先确认，取消时不入草稿', (tester) async {
    await pumpEditor(tester);
    await openResourceMenu(tester, 'Item');
    await tester.tap(find.byKey(const ValueKey('wb.resourceMenu.delete')));
    await tester.pumpAndSettle();
    expect(repo.resourceNamed('Item'), isNotNull);
    await tester.tap(find.text('取消').last);
    await tester.pumpAndSettle();
    expect(repo.draftCount, 0);
    await openResourceMenu(tester, 'Item');
    await tester.tap(find.byKey(const ValueKey('wb.resourceMenu.delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.deleteResourceConfirm')));
    await tester.pumpAndSettle();
    expect(repo.resourceNamed('Item'), isNull);
    expect(repo.resourceNamed('Reward'), isNotNull);
    expect(
      tester
          .widget<WorkbenchSchemaEditor>(
            find.byKey(const ValueKey('wb.schemaEditor')),
          )
          .selected,
      'Reward',
    );
    expect(repo.commands.last.payload['name'], 'table:Item');
  });

  testWidgets('真实草稿下保存走双守卫请求，成功后清空草稿', (tester) async {
    await pumpEditor(tester);
    repo.createTable('Hero');
    await tester.pumpAndSettle();

    TextButton saveButton() =>
        tester.widget<TextButton>(find.byKey(const ValueKey('wb.draftSave')));
    expect(gateway.candidates, hasLength(1), reason: '编辑后自动算候选');
    expect(saveButton().onPressed, isNotNull, reason: '候选就绪后无需再找「算候选」');
    await tester.tap(find.byKey(const ValueKey('wb.draftSave')));
    await tester.pumpAndSettle();

    final sent = gateway.saves.single;
    expect(sent['schemaRevision'], 'baseline-sha');
    expect(sent['candidateHash'], 'hash-edit');
    expect(sent['commands'], hasLength(1));
    expect(sent['cursor'], '1');
    expect(find.text('草稿 0 条'), findsNothing);
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
