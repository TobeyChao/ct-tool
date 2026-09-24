import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/workbench_field_editor.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 属性区里的字段编辑器（任务 3.2 界面侧）：状态一律来自内核，改动只落草稿。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.problems = const []});

  final List<Issue> problems;
  final List<Map<String, Object?>> candidates = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-field';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    if (method == Methods.schemaCandidate) candidates.add(params);
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 4,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 0,
      },
      Methods.resourcesList => {
        'revision': 4,
        'schemaRevision': 'baseline-field',
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
            'indexes': ['codename'],
            'primary': 'Id',
            'fields': [
              {'name': 'Id', 'type': 'int32'},
              {'name': 'Name', 'type': 'string', 'i18n': true},
            ],
          },
          {
            'name': 'Quest',
            'kind': 'table',
            'sourcePath': 'config/schemas/quest.yaml',
            'primary': 'Id',
            'fields': [
              {'name': 'Id', 'type': 'int32'},
            ],
          },
          {
            'name': 'Rarity',
            'kind': 'enum',
            'sourcePath': 'config/schemas/rarity.yaml',
            'values': [
              {'name': 'Common'},
              {'name': 'Rare'},
            ],
          },
        ],
      },
      Methods.tablePreview => {
        'revision': 4,
        'columns': const [
          {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
          {
            'name': 'Name',
            'typeExpr': 'string',
            'role': 'i18n',
            'i18n': true,
            'comment': '显示名',
          },
        ],
        'rows': const <Object?>[],
      },
      Methods.schemaCandidate => {
        'candidateHash': 'hash-field',
        'draftGeneration': params['draftGeneration'],
        'netDiff': {
          'added': <Object?>[],
          'removed': <Object?>[],
          'changed': const [
            {'kind': 'table', 'name': 'Item'},
          ],
        },
        'problems': problems.map((e) => e.toJson()).toList(),
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

/// 命中可点的行（同名文本也出现在属性区，必须走 InkWell 定位）。
Finder rowOf(String text) =>
    find.ancestor(of: find.text(text), matching: find.byType(InkWell));

void main() {
  late _FakeGateway gateway;
  late WorkbenchRepository repo;

  Future<void> openWorkbench(WidgetTester tester, {String? field}) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(data: repo, refresh: repo, draft: repo),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(rowOf('Item'));
    await tester.pumpAndSettle();
    if (field != null) {
      await tester.tap(rowOf(field));
      await tester.pumpAndSettle();
    }
  }

  setUp(() async {
    gateway = _FakeGateway();
    repo = WorkbenchRepository(worker: gateway);
    // resources.list 自带的 fields 是字段行的唯一来源。
    await repo.switchWorkspace('D:/game/A');
  });

  tearDown(() => repo.dispose());

  Future<void> chooseType(
    WidgetTester tester,
    String prefix,
    String query,
    String option,
  ) async {
    await tester.tap(find.byKey(ValueKey('$prefix.base')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(ValueKey('$prefix.search')), query);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(ValueKey('$prefix.option.$option')));
    await tester.pumpAndSettle();
  }

  CtCheckbox checkboxOf(WidgetTester tester, String key) =>
      tester.widget<CtCheckbox>(find.byKey(ValueKey(key)));

  TextButton buttonOf(WidgetTester tester, String key) =>
      tester.widget<TextButton>(
        find.descendant(
          of: find.byKey(ValueKey(key)),
          matching: find.byType(TextButton),
        ),
      );

  testWidgets('未选中字段时显示资源与索引状态（来自内核清单）', (tester) async {
    await openWorkbench(tester);
    expect(find.byKey(const ValueKey('wb.fieldEditor')), findsOneWidget);
    expect(find.text('table:Item'), findsOneWidget, reason: '资源 ID 要可见');
    expect(
      checkboxOf(tester, 'wb.indexCodename').value,
      isTrue,
      reason: '内核报了索引',
    );
    expect(find.text('主键'), findsOneWidget);
  });

  testWidgets('禁用开关会显示不可修改原因', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: WorkbenchFieldEditor(
            resource: const WorkbenchResource(
              name: 'Item',
              kind: WorkbenchResourceKind.table,
              path: 'config/schemas/item.yaml',
              indexes: ['codename'],
            ),
            ownerId: 'table:Item',
            disabled: true,
            disabledHint: '保存进行中，暂不可修改',
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      tester
          .widget<CtCheckbox>(find.byKey(const ValueKey('wb.indexCodename')))
          .onChanged,
      isNull,
    );
    expect(
      find.byKey(const ValueKey('wb.indexCodename.disabledHint')),
      findsOneWidget,
    );
    expect(find.textContaining('当前不可修改：保存进行中'), findsOneWidget);
  });

  testWidgets('codename 索引开关可打开也可关闭', (tester) async {
    await openWorkbench(tester);
    final toggle = find.byKey(const ValueKey('wb.indexCodename'));

    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(repo.draftCount, 1);
    expect(repo.commands.last.kind, 'set_indexes');
    expect(repo.resourceNamed('Item')!.indexes, isEmpty);
    expect(checkboxOf(tester, 'wb.indexCodename').value, isFalse);

    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(repo.draftCount, 2);
    expect(repo.commands.last.kind, 'set_indexes');
    expect(repo.resourceNamed('Item')!.indexes, ['codename']);
    expect(checkboxOf(tester, 'wb.indexCodename').value, isTrue);
  });

  testWidgets('选中字段后可改类型与属性，改动只进草稿', (tester) async {
    await openWorkbench(tester, field: 'Name');
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('wb.fieldType.value')))
          .data,
      'string',
    );
    expect(
      checkboxOf(tester, 'wb.fieldI18n').value,
      isTrue,
      reason: 'i18n 开关回显内核状态',
    );

    await tester.tap(find.byKey(const ValueKey('wb.fieldI18n')));
    await tester.pumpAndSettle();
    expect(repo.draftCount, 1);
    expect(repo.commands.single.kind, 'set_property');
    expect(repo.commands.single.payload['owner'], 'table:Item');
    expect(repo.commands.single.payload['property'], 'i18n');
    final note = tester.widget<Text>(
      find.byKey(const ValueKey('wb.inspectorNote')),
    );
    expect(note.data, contains('草稿 1 条'), reason: '属性区自己也要报草稿条数');

    await chooseType(tester, 'wb.fieldType', 'int64', 'int64');
    expect(repo.draftCount, 2);
    expect(repo.commands.last.kind, 'set_type');
    expect(repo.commands.last.payload['type_text'], 'int64');
  });

  testWidgets('具名类型通过下拉选择，vector 开关拼成合法类型表达式', (tester) async {
    await openWorkbench(tester, field: 'Name');
    await tester.tap(find.byKey(const ValueKey('wb.fieldType.base')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('wb.fieldType.search')),
      'Rarity',
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.fieldType.option.Rarity')),
      findsOneWidget,
      reason: '枚举名必须来自内核资源清单',
    );
    await tester.tap(find.byKey(const ValueKey('wb.fieldType.option.Rarity')));
    await tester.pumpAndSettle();

    final vector = find.byKey(const ValueKey('wb.fieldType.vector'));
    final before = tester.getSize(vector);
    await tester.tap(vector);
    await tester.pumpAndSettle();
    final after = tester.getSize(vector);
    expect(after.width, before.width, reason: '选中态不得改变文字度量或按钮宽度');
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('wb.fieldType.value')))
          .data,
      'vector<Rarity>',
    );
    expect(repo.commands.last.kind, 'set_type');
    expect(repo.commands.last.payload['type_text'], 'vector<Rarity>');
  });

  testWidgets('ref 从可搜索的工作区表主键弹窗选择', (tester) async {
    await openWorkbench(tester, field: 'Name');
    final picker = find.byKey(const ValueKey('wb.fieldRef.picker'));
    await tester.scrollUntilVisible(
      picker,
      220,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('wb.fieldEditor')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.tap(picker);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('wb.fieldRef.search')),
      'Quest',
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.fieldRef.option.Quest.Id')));
    await tester.pumpAndSettle();

    expect(repo.commands.last.kind, 'set_property');
    expect(repo.commands.last.payload['property'], 'ref');
    expect(repo.commands.last.payload['value'], 'Quest.Id');
  });

  testWidgets('注释支持多行：有变更才出现还原与保存，还原不发命令', (tester) async {
    await openWorkbench(tester, field: 'Name');
    final comment = find.byKey(const ValueKey('wb.fieldComment'));
    await tester.scrollUntilVisible(
      comment,
      180,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('wb.fieldEditor')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    final controller = tester.widget<TextField>(comment).controller!;
    final original = controller.text;

    // 与草稿值一致时不留动作，注释输入框是多行的。
    expect(find.byKey(const ValueKey('wb.setFieldComment')), findsNothing);
    expect(find.byKey(const ValueKey('wb.revertFieldComment')), findsNothing);
    expect(tester.widget<TextField>(comment).maxLines, 4);
    final oneLine = tester.getSize(comment).height;

    await tester.enterText(comment, '$original\n第二行注释');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.revertFieldComment')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.setFieldComment')), findsOneWidget);
    expect(
      tester.getSize(comment).height,
      greaterThan(oneLine),
      reason: '换行要撑高输入框',
    );

    await tester.tap(find.byKey(const ValueKey('wb.revertFieldComment')));
    await tester.pumpAndSettle();
    expect(controller.text, original);
    expect(repo.draftCount, 0, reason: '还原只回文本，不发命令');
    expect(find.byKey(const ValueKey('wb.setFieldComment')), findsNothing);

    await tester.enterText(comment, '新注释\n第二行');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.setFieldComment')));
    await tester.pumpAndSettle();
    expect(repo.commands.last.kind, 'set_property');
    expect(repo.commands.last.payload['property'], 'comment');
    expect(repo.commands.last.payload['value'], '新注释\n第二行');

    // 行内编辑的键盘惯例：Esc 还原到草稿值，Ctrl+Enter 保存。
    await tester.enterText(comment, '键盘改的注释');
    await tester.pumpAndSettle();
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(controller.text, '新注释\n第二行');
    expect(find.byKey(const ValueKey('wb.setFieldComment')), findsNothing);

    await tester.enterText(comment, '键盘保存的注释');
    await tester.pumpAndSettle();
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyDownEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();
    expect(repo.commands.last.payload['value'], '键盘保存的注释');
  });

  testWidgets('Excel 展开默认展开：复选框控制输入，组数只收 1~64', (tester) async {
    final calls = <MapEntry<String, Object?>>[];

    WorkbenchField field(int? columns, [String name = 'Rewards']) =>
        WorkbenchField(
          name: name,
          type: 'vector<string>',
          excelColumns: columns,
        );

    Future<void> pumpEditor(
      int? columns, {
      bool disabled = false,
      String name = 'Rewards',
    }) async {
      tester.view.physicalSize = const Size(360, 900);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildCtTheme(),
          home: Scaffold(
            body: WorkbenchFieldEditor(
              resource: WorkbenchResource(
                name: 'Item',
                kind: WorkbenchResourceKind.table,
                path: 'config/schemas/item.yaml',
                fields: [field(columns, name)],
              ),
              ownerId: 'table:Item',
              field: field(columns, name),
              fieldOrdinal: 0,
              disabled: disabled,
              onSetProperty: (property, value) =>
                  calls.add(MapEntry(property, value)),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    final count = find.byKey(const ValueKey('wb.fieldColumns'));
    final toggle = find.byKey(const ValueKey('wb.fieldExpand'));

    // 有 excel_columns：区块直接摊开（没有折叠壳），复选框已勾选，组数回显草稿值。
    await pumpEditor(3);
    expect(find.text('Excel 展开'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.group.excelColumns')), findsNothing);
    expect(tester.widget<CtCheckbox>(toggle).value, isTrue);
    expect(tester.widget<TextField>(count).controller!.text, '3');
    expect(calls, isEmpty, reason: '没有改动不发命令');

    // 只能数字：字母被格式化器挡掉。
    await tester.enterText(count, '12a');
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(count).controller!.text, '12');

    // 越界：给出提示并禁用保存；0、65、999 与空值都不合法。
    for (final bad in const ['0', '65', '999', '']) {
      await tester.enterText(count, bad);
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('wb.fieldColumns.error')),
        findsOneWidget,
        reason: '$bad 不在 1~64 内',
      );
      expect(
        tester
            .widget<IconButton>(
              find.byKey(const ValueKey('wb.setFieldColumns')),
            )
            .onPressed,
        isNull,
      );
    }

    // 合法值：保存发 set_property(excel_columns)，还原只回文本。
    await tester.enterText(count, '8');
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.fieldColumns.error')), findsNothing);
    await tester.tap(find.byKey(const ValueKey('wb.revertFieldColumns')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(count).controller!.text, '3');
    expect(calls, isEmpty);

    await tester.enterText(count, '8');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.setFieldColumns')));
    await tester.pumpAndSettle();
    expect(calls.last.key, 'excel_columns');
    expect(calls.last.value, 8);

    // 取消勾选 = 清掉 excel_columns；未勾选时没有组数输入。
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(calls.last.key, 'excel_columns');
    expect(calls.last.value, isNull);

    calls.clear();
    await pumpEditor(null);
    expect(tester.widget<CtCheckbox>(toggle).value, isFalse);
    expect(count, findsNothing, reason: '开关关掉就没有输入内容');
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(calls.last.key, 'excel_columns');
    expect(calls.last.value, 8, reason: '同一字段沿用上次填过的数');

    calls.clear();
    await pumpEditor(null, name: 'Tags');
    expect(count, findsNothing);
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(calls.last.key, 'excel_columns');
    expect(calls.last.value, 1, reason: '没有历史值就给最小值');

    await pumpEditor(null, name: 'Tags', disabled: true);
    expect(
      find.byKey(const ValueKey('wb.fieldExpand.disabledHint')),
      findsOneWidget,
      reason: '禁用态沿用同一套原因行',
    );
  });

  testWidgets('枚举成员改名沿用同一套行内编辑（有改动才出现动作）', (tester) async {
    final renamed = <(String, int)>[];
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: WorkbenchFieldEditor(
            resource: const WorkbenchResource(
              name: 'Rarity',
              kind: WorkbenchResourceKind.enumType,
              path: 'config/types/rarity.yaml',
              fields: [
                WorkbenchField(name: 'Common', type: 'enum'),
                WorkbenchField(name: 'Rare', type: 'enum'),
              ],
            ),
            ownerId: 'enum:Rarity',
            field: const WorkbenchField(name: 'Rare', type: 'enum'),
            fieldOrdinal: 1,
            onRenameEnumItem: (name, ordinal) => renamed.add((name, ordinal)),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final name = find.byKey(const ValueKey('wb.enumItemName'));
    expect(name, findsOneWidget);
    expect(find.byKey(const ValueKey('wb.enumItemRename')), findsNothing);

    await tester.enterText(name, 'Legendary');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.enumItemRename')));
    await tester.pumpAndSettle();
    expect(renamed, [('Legendary', 1)]);

    await tester.enterText(name, '   ');
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.enumItemName.error')),
      findsOneWidget,
      reason: '空名不给保存，并说明原因',
    );
    expect(
      tester
          .widget<IconButton>(find.byKey(const ValueKey('wb.enumItemRename')))
          .onPressed,
      isNull,
    );
  });

  testWidgets('主键字段不给删除与调序入口', (tester) async {
    await openWorkbench(tester, field: 'Id');
    final danger = find.byKey(const ValueKey('wb.group.danger'));
    await tester.scrollUntilVisible(
      danger,
      220,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('wb.fieldEditor')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    // 危险操作现在是普通卡片（不再折叠），滚到即可见。
    expect(buttonOf(tester, 'wb.fieldDelete').onPressed, isNull);
    expect(buttonOf(tester, 'wb.fieldDown').onPressed, isNull);
    expect(find.textContaining('主键不可删除'), findsOneWidget);
  });

  testWidgets('字段行右键菜单可直接切换属性并显示完整动作', (tester) async {
    await openWorkbench(tester);
    await tester.tap(find.text('Name').first, buttons: kSecondaryMouseButton);
    await tester.pumpAndSettle();

    for (final key in const [
      'wb.fieldMenu.edit',
      'wb.fieldMenu.changeType',
      'wb.fieldMenu.copyName',
      'wb.fieldMenu.copyType',
      'wb.fieldMenu.toggleI18n',
      'wb.fieldMenu.toggleServerOnly',
      'wb.fieldMenu.moveUp',
      'wb.fieldMenu.moveDown',
      'wb.fieldMenu.delete',
    ]) {
      expect(find.byKey(ValueKey(key)), findsOneWidget);
    }

    await tester.tap(find.byKey(const ValueKey('wb.fieldMenu.toggleI18n')));
    await tester.pumpAndSettle();
    expect(repo.commands.last.kind, 'set_property');
    expect(repo.commands.last.payload['property'], 'i18n');
    expect(repo.commands.last.payload['value'], isFalse);
  });

  testWidgets('非法组合由内核候选报出来，界面原样列出问题', (tester) async {
    gateway = _FakeGateway(
      problems: const [
        Issue(
          code: 'schema-issue',
          message: '字段 Name 不能同时标记 i18n 和 server_only',
          resource: 'table:Item/Name',
        ),
      ],
    );
    repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/A');
    await openWorkbench(tester, field: 'Name');
    final serverOnly = find.byKey(const ValueKey('wb.fieldServerOnly'));
    await tester.scrollUntilVisible(
      serverOnly,
      180,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('wb.fieldEditor')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    await tester.tap(serverOnly);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('wb.candidate')));
    await tester.pumpAndSettle();
    // 分组后问题块可能被挤出视口：ListView 懒加载，先滚到底再断言
    await tester.drag(
      find.byKey(const ValueKey('wb.fieldEditor')),
      const Offset(0, -260),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.fieldProblems')), findsOneWidget);
    final block = find.byKey(const ValueKey('wb.fieldProblems'));
    expect(
      find.descendant(
        of: block,
        matching: find.textContaining('不能同时标记 i18n 和 server_only'),
      ),
      findsOneWidget,
      reason: '问题文本原样来自内核',
    );
    expect(
      find.descendant(
        of: block,
        matching: find.textContaining('（table:Item/Name）'),
      ),
      findsOneWidget,
    );
  });
}
