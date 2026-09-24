import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 3.7：类型/ref 跳转与返回栈、Enum 成员追加/重排/删除、Quick Open 的
/// 键盘操作与最近打开持久化。
class _FakeGateway implements KernelGateway {
  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-nav';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 9,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 2,
          'records': 0,
          'enums': 1,
        };
      case Methods.resourcesList:
        return {
          'revision': 9,
          'schemaRevision': 'baseline-nav',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
              'primary': 'Id',
              'fields': [
                {'name': 'Id', 'type': 'int32'},
                {'name': 'Rarity', 'type': 'Quality'},
                {'name': 'Amount', 'type': 'int32'},
                {'name': 'Price', 'type': 'int32'},
              ],
            },
            {
              'name': 'Drop',
              'kind': 'table',
              'sourcePath': 'config/schemas/drop.yaml',
              'primary': 'Id',
              'fields': [
                {'name': 'Id', 'type': 'int32'},
                {'name': 'Source', 'type': 'int32', 'ref': 'Item.Id'},
              ],
            },
            {
              'name': 'Quality',
              'kind': 'enum',
              'sourcePath': 'config/schemas/quality.yaml',
              'values': [
                {'name': 'Low'},
                {'name': 'High'},
              ],
            },
          ],
        };
      case Methods.schemaCandidate:
        return {
          'candidateHash': 'hash-nav',
          'draftGeneration': params['draftGeneration'],
          'netDiff': {
            'added': <Object?>[],
            'removed': <Object?>[],
            'changed': <Object?>[],
          },
          'problems': <Object?>[],
        };
      default:
        return {'columns': <Object?>[], 'rows': <Object?>[]};
    }
  }
}

Future<void> _ctrl(
  WidgetTester tester,
  LogicalKeyboardKey key, {
  LogicalKeyboardKey? modifier,
}) async {
  final mod = modifier ?? LogicalKeyboardKey.controlLeft;
  await tester.sendKeyDownEvent(mod);
  await tester.sendKeyDownEvent(key);
  await tester.sendKeyUpEvent(key);
  await tester.sendKeyUpEvent(mod);
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late WorkbenchRepository repo;
  late SettingsStore settings;

  Future<void> pumpNav(WidgetTester tester) async {
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
          workspaceKey: 'nav-test',
          bannerLabel: '已连接原生内核',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  Future<void> focusBody(WidgetTester tester) async {
    await tester.tap(find.text('Item').first);
    await tester.pumpAndSettle();
  }

  setUp(() async {
    SharedPreferences.setMockInitialValues({'workspace_path': 'D:/game/gd'});
    settings = SettingsStore();
    await settings.load();
    repo = WorkbenchRepository(worker: _FakeGateway());
    await repo.switchWorkspace('D:/game/gd');
  });

  tearDown(() => repo.dispose());

  testWidgets('类型链接跳到 Enum 资源，返回栈跳回原表', (tester) async {
    await pumpNav(tester);
    // 默认选中第一个资源 Item；Rarity 的类型是 Quality，应可点跳。
    expect(find.byKey(const ValueKey('wb.enumAddItem')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('wb.refLink.Quality')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.enumAddItem')),
      findsOneWidget,
      reason: '跳转后主区应停在枚举 Quality',
    );
    expect(find.byKey(const ValueKey('wb.navBack')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.navBack')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.enumAddItem')), findsNothing);
    expect(find.byKey(const ValueKey('wb.navBack')), findsNothing);
  });

  testWidgets('ref 链接去掉主键段后跳到目标表', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.text('Drop').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.refLink.Item.Id')));
    await tester.pumpAndSettle();
    expect(find.textContaining('config/schemas/item.yaml'), findsWidgets);
    expect(find.byKey(const ValueKey('wb.navBack')), findsOneWidget);
  });

  testWidgets('资源与字段操作可从可聚焦按钮打开', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.byKey(const ValueKey('wb.resourceActions')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.resourceMenu.rename')),
      findsOneWidget,
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Rarity').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.fieldActions')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.fieldMenu.changeType')),
      findsOneWidget,
    );
  });

  testWidgets('字段右键下移只交换相邻字段', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.text('Rarity').first, buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.fieldMenu.moveDown')));
    await tester.pumpAndSettle();
    expect(repo.commands.last.kind, 'move_field');
    expect(repo.commands.last.payload['to'], 2);
    expect(
      repo.resourceNamed('Item')!.fields.map((field) => field.name).toList(),
      ['Id', 'Amount', 'Rarity', 'Price'],
    );
  });

  testWidgets('属性区下移只交换相邻字段且末项不可下移', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.text('Rarity').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.fieldDown')));
    await tester.pumpAndSettle();
    expect(repo.commands.last.payload['to'], 2);
    expect(repo.resourceNamed('Item')!.fields.map((f) => f.name), [
      'Id',
      'Amount',
      'Rarity',
      'Price',
    ]);
    await tester.tap(find.text('Price').first);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<CtButton>(find.byKey(const ValueKey('wb.fieldDown')))
          .onPressed,
      isNull,
    );
  });

  testWidgets('枚举成员在属性区下移时只交换相邻成员', (tester) async {
    repo.setEnumValues('enum:Quality', ['Low', 'High', 'Epic']);
    await pumpNav(tester);
    await tester.tap(find.text('Quality').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Low').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.enumItemDown')));
    await tester.pumpAndSettle();
    expect([
      for (final item in repo.commands.last.payload['values'] as List)
        (item as Map)['name'],
    ], ['High', 'Low', 'Epic']);
  });

  testWidgets('枚举成员追加走 set_enum_values 整表改写', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.text('Quality').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.enumOrdinalRisk')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.enumAddItem')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('wb.enumItemField')),
      'Epic',
    );
    await tester.tap(find.byKey(const ValueKey('wb.enumItemConfirm')));
    await tester.pumpAndSettle();

    final payload = repo.commands.last.payload;
    expect(repo.commands.last.kind, 'set_enum_values');
    expect(payload['name'], 'enum:Quality', reason: 'owner 必须是内核资源 id');
    expect(
      [for (final v in payload['values'] as List) (v as Map)['name']],
      ['Low', 'High', 'Epic'],
    );
  });

  testWidgets('枚举重排/删除不能用 move_field：整表改写并留 ordinal 风险', (tester) async {
    await pumpNav(tester);
    await tester.tap(find.text('Quality').first);
    await tester.pumpAndSettle();
    // 选中第二个成员，点「上移」→ 顺序变成 High, Low。
    await tester.tap(find.text('High').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.group.danger')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.enumItemUp')));
    await tester.pumpAndSettle();
    var values = [
      for (final v in repo.commands.last.payload['values'] as List)
        (v as Map)['name'],
    ];
    expect(values, ['High', 'Low']);
    expect(
      repo.commands.last.kind,
      'set_enum_values',
      reason: 'Enum 没有字段列表，move_field 会被内核拒绝',
    );

    await tester.tap(find.byKey(const ValueKey('wb.group.danger')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.enumItemDelete')));
    await tester.pumpAndSettle();
    values = [
      for (final v in repo.commands.last.payload['values'] as List)
        (v as Map)['name'],
    ];
    expect(values, ['High']);
  });

  testWidgets('Quick Open：Esc 关闭，最近打开按工作区持久化', (tester) async {
    await pumpNav(tester);
    await focusBody(tester);
    await _ctrl(tester, LogicalKeyboardKey.keyP);
    expect(find.byKey(const ValueKey('wb.quickOpen.field')), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.quickOpen.field')), findsNothing);

    // 从 Quick Open 选 Quality，最近清单要记住它。
    await _ctrl(tester, LogicalKeyboardKey.keyP);
    await tester.enterText(
      find.byKey(const ValueKey('wb.quickOpen.field')),
      'qua',
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.quickOpen.row.Quality.0')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.enumAddItem')), findsOneWidget);

    final prefs = await SharedPreferences.getInstance();
    expect(
      prefs.getStringList('wb.nav-test.recents'),
      contains('Quality'),
      reason: '最近打开按工作区键存进偏好，重启后仍在',
    );

    // 重开：空查询把最近打开排在第一位。
    await _ctrl(tester, LogicalKeyboardKey.keyP);
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.quickOpen.row.Quality.0')),
      findsOneWidget,
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
  });
}
