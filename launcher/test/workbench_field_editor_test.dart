import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_field_editor.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
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

  DropdownButton<String> dropdownOf(WidgetTester tester, String key) =>
      tester.widget<DropdownButton<String>>(find.byKey(ValueKey(key)));

  Future<void> chooseDropdown(
    WidgetTester tester,
    String key,
    String option,
  ) async {
    await tester.tap(find.byKey(ValueKey(key)));
    await tester.pumpAndSettle();
    await tester.tap(find.text(option).last);
    await tester.pumpAndSettle();
  }

  Switch switchOf(WidgetTester tester, String key) =>
      tester.widget<Switch>(find.byKey(ValueKey(key)));

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
      switchOf(tester, 'wb.indexCodename').value,
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
          .widget<Switch>(find.byKey(const ValueKey('wb.indexCodename')))
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
    expect(switchOf(tester, 'wb.indexCodename').value, isFalse);

    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(repo.draftCount, 2);
    expect(repo.commands.last.kind, 'set_indexes');
    expect(repo.resourceNamed('Item')!.indexes, ['codename']);
    expect(switchOf(tester, 'wb.indexCodename').value, isTrue);
  });

  testWidgets('选中字段后可改类型与属性，改动只进草稿', (tester) async {
    await openWorkbench(tester, field: 'Name');
    expect(dropdownOf(tester, 'wb.fieldType.base').value, 'string');
    expect(
      switchOf(tester, 'wb.fieldI18n').value,
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

    await chooseDropdown(tester, 'wb.fieldType.base', 'int64');
    await tester.tap(find.byKey(const ValueKey('wb.setFieldType')));
    await tester.pumpAndSettle();
    expect(repo.draftCount, 2);
    expect(repo.commands.last.kind, 'set_type');
    expect(repo.commands.last.payload['type_text'], 'int64');
  });

  testWidgets('具名类型通过下拉选择，vector 开关拼成合法类型表达式', (tester) async {
    await openWorkbench(tester, field: 'Name');
    final values = dropdownOf(
      tester,
      'wb.fieldType.base',
    ).items!.map((item) => item.value).whereType<String>();
    expect(values, contains('Rarity'), reason: '枚举名必须来自内核资源清单');

    await chooseDropdown(tester, 'wb.fieldType.base', 'Rarity');
    final vector = find.byKey(const ValueKey('wb.fieldType.vector'));
    final before = tester.getSize(vector);
    await tester.tap(vector);
    await tester.pumpAndSettle();
    final after = tester.getSize(vector);
    expect(after.width, before.width, reason: '选中态不得改变文字度量或按钮宽度');
    expect(find.byKey(const ValueKey('wb.fieldType.preview')), findsOneWidget);
    expect(find.text('实际写入：vector<Rarity>'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.setFieldType')));
    await tester.pumpAndSettle();
    expect(repo.commands.last.kind, 'set_type');
    expect(repo.commands.last.payload['type_text'], 'vector<Rarity>');
  });

  testWidgets('ref 只能从工作区表主键下拉选择', (tester) async {
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
    await chooseDropdown(tester, 'wb.fieldRef.picker', 'Quest.Id');
    await tester.tap(find.byKey(const ValueKey('wb.setFieldRef')));
    await tester.pumpAndSettle();

    expect(repo.commands.last.kind, 'set_property');
    expect(repo.commands.last.payload['property'], 'ref');
    expect(repo.commands.last.payload['value'], 'Quest.Id');
  });

  testWidgets('主键字段不给删除与调序入口', (tester) async {
    await openWorkbench(tester, field: 'Id');
    await tester.scrollUntilVisible(
      find.textContaining('主键不可删除'),
      220,
      scrollable: find
          .descendant(
            of: find.byKey(const ValueKey('wb.fieldEditor')),
            matching: find.byType(Scrollable),
          )
          .first,
    );
    expect(buttonOf(tester, 'wb.fieldDelete').onPressed, isNull);
    expect(buttonOf(tester, 'wb.fieldDown').onPressed, isNull);
    expect(find.textContaining('主键不可删除'), findsOneWidget);
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
    await tester.tap(find.byKey(const ValueKey('wb.fieldServerOnly')));
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
