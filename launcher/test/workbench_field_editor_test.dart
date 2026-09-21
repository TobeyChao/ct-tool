import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
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
    // 与真实壳层同序：先开工作区，再按需拉预览（字段行与属性由它提供）。
    await repo.switchWorkspace('D:/game/A');
    await repo.loadPreview('Item');
  });

  tearDown(() => repo.dispose());

  TextField fieldOf(WidgetTester tester, String key) =>
      tester.widget<TextField>(find.byKey(ValueKey(key)));

  Checkbox checkOf(WidgetTester tester, String key) =>
      tester.widget<Checkbox>(find.byKey(ValueKey(key)));

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
    expect(checkOf(tester, 'wb.indexCodename').value, isTrue, reason: '内核报了索引');
    expect(find.text('主键'), findsOneWidget);
  });

  testWidgets('选中字段后可改类型与属性，改动只进草稿', (tester) async {
    await openWorkbench(tester, field: 'Name');
    expect(fieldOf(tester, 'wb.fieldType').controller!.text, 'string');
    expect(
      checkOf(tester, 'wb.fieldI18n').value,
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

    await tester.enterText(find.byKey(const ValueKey('wb.fieldType')), 'int64');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.setFieldType')));
    await tester.pumpAndSettle();
    expect(repo.draftCount, 2);
    expect(repo.commands.last.kind, 'set_type');
    expect(repo.commands.last.payload['type_text'], 'int64');
  });

  testWidgets('主键字段不给删除与调序入口', (tester) async {
    await openWorkbench(tester, field: 'Id');
    expect(buttonOf(tester, 'wb.fieldDelete').onPressed, isNull);
    expect(buttonOf(tester, 'wb.fieldDown').onPressed, isNull);
    await tester.drag(
      find.byKey(const ValueKey('wb.fieldEditor')),
      const Offset(0, -240),
    );
    await tester.pumpAndSettle();
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
    await repo.loadPreview('Item');
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
