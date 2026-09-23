import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 翻译模块界面（任务 4.1–4.3）：筛选/分页都送内核，失焦即单条保存，
/// 清理必须先看预检再显式确认。
class _Call {
  _Call(this.method, this.params);
  final String method;
  final Map<String, Object?> params;
}

class _FakeGateway implements KernelGateway {
  final List<_Call> calls = [];
  bool hasMore = true;
  bool failSave = false;
  String? longSource;

  List<_Call> of(String method) =>
      calls.where((c) => c.method == method).toList();

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-i18n-ui';

  Map<String, Object?> _entry(
    String key,
    String source,
    String text,
    bool confirmed,
    String status,
  ) => {
    'key': key,
    'source': source,
    'text': text,
    'confirmed': confirmed,
    'status': status,
  };

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(_Call(method, params));
    switch (method) {
      case Methods.i18nStatus:
        return {
          'langs': [
            {
              'lang': 'en',
              'translated': 1,
              'missing': 1,
              'stale': 0,
              'orphan': 0,
            },
          ],
        };
      case Methods.i18nQuery:
        final page = params['page']! as Map<String, Object?>;
        final first = page['cursor'] == null;
        return {
          'revision': 11,
          'entries': first
              ? [
                  _entry('1001.Name', '铁剑', 'Iron Sword', true, 'translated'),
                  _entry('1002.Name', longSource ?? '铁盾', '', false, 'missing'),
                ]
              : [_entry('1003.Name', '长弓', 'Long Bow', false, 'stale')],
          if (first && hasMore) 'nextCursor': 'cursor-2',
        };
      case Methods.i18nSave:
        if (failSave) {
          throw WorkerRequestException(
            const ErrorBody(code: 'busy', message: '稍后重试'),
          );
        }
        return {
          'status': (params['text']! as String).isEmpty
              ? 'missing'
              : 'translated',
        };
      case Methods.i18nSync:
        return {'tables': 1, 'inserted': 0};
      case Methods.i18nCompact:
        final dry = params['dryRun']! as bool;
        return {
          'dryRun': dry,
          'entries': dry ? const ['9999.Name'] : const <String>[],
          'removed': dry ? 0 : 1,
        };
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

void main() {
  late _FakeGateway gateway;
  late TranslationRepository translations;

  Future<void> openI18n(
    WidgetTester tester, {
    Size size = const Size(1500, 1100),
    double pixelRatio = 1.0,
  }) async {
    await translations.bind('D:/game/A');
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = pixelRatio;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: const StaticWorkbenchData(
            workspaceName: 'gd',
            workspacePath: 'D:/game/A',
            resources: [
              WorkbenchResource(
                name: 'Item',
                kind: WorkbenchResourceKind.table,
                path: 'config/schemas/item.yaml',
              ),
            ],
          ),
          translations: translations,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.translate));
    await tester.pumpAndSettle();
  }

  setUp(() {
    gateway = _FakeGateway();
    translations = TranslationRepository(worker: gateway);
  });

  tearDown(() => translations.dispose());

  testWidgets('筛选栏与译文表由内核数据驱动，分页按 nextCursor 决定', (tester) async {
    await openI18n(tester);
    expect(find.byKey(const ValueKey('wb.i18nView')), findsOneWidget);
    expect(find.text('1001.Name'), findsOneWidget);
    expect(find.text('铁剑'), findsOneWidget);
    expect(find.text('已翻译'), findsWidgets);
    expect(find.textContaining('已取 2 条'), findsOneWidget);

    final count = gateway.of(Methods.i18nQuery).last;
    expect(count.params['table'], 'Item');
    expect(count.params['lang'], 'en');
    expect(count.params.containsKey('status'), isFalse);

    await tester.tap(find.byKey(const ValueKey('wb.i18nMore')));
    await tester.pumpAndSettle();
    final more = gateway.of(Methods.i18nQuery).last;
    final page = more.params['page']! as Map<String, Object?>;
    expect(page['cursor'], 'cursor-2');
    expect(find.textContaining('已取 3 条'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.i18nMore')), findsOneWidget);
    final button = tester.widget<TextButton>(
      find.descendant(
        of: find.byKey(const ValueKey('wb.i18nMore')),
        matching: find.byType(TextButton),
      ),
    );
    expect(button.onPressed, isNull, reason: '内核没给 nextCursor 就到底了');
  });

  testWidgets('状态筛选送内核，列显隐即时生效并在切表后保留', (tester) async {
    await openI18n(tester);

    await tester.tap(find.byKey(const ValueKey('wb.i18nStatus')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('缺失').last);
    await tester.pumpAndSettle();
    expect(
      gateway.of(Methods.i18nQuery).last.params['status'],
      'missing',
      reason: '筛选条件必须交给内核执行',
    );

    await tester.tap(find.byKey(const ValueKey('wb.i18nColumnsMenu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.i18nColumn.source')));
    await tester.pumpAndSettle();
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('wb.i18nRows')),
        matching: find.text('原文'),
      ),
      findsNothing,
      reason: '表头也该跟着列显隐走',
    );
    expect(find.text('铁剑'), findsNothing, reason: '原文列已隐藏');

    await tester.tap(find.byKey(const ValueKey('wb.i18nTable')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Item').last);
    await tester.pumpAndSettle();
    expect(
      translations.filter,
      TranslationFilter.missing,
      reason: '切表要保留筛选（4.1 验收）',
    );
    expect(translations.shown('source'), isFalse, reason: '列显隐也要保留');
  });

  testWidgets('译文失焦即保存，只发一条 i18n.save', (tester) async {
    await openI18n(tester);
    gateway.calls.clear();

    await tester.enterText(
      find.byKey(const ValueKey('wb.i18nCell.1002.Name')),
      'Iron Shield',
    );
    await tester.pumpAndSettle();
    // 模拟失焦：真实用户是点到别处，测试里直接交还焦点。
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();

    final saves = gateway.of(Methods.i18nSave);
    expect(saves, hasLength(1), reason: '失焦只提交当前行');
    expect(saves.single.params, {
      'table': 'Item',
      'lang': 'en',
      'key': '1002.Name',
      'text': 'Iron Shield',
      'confirmed': false,
    });
    expect(gateway.of(Methods.i18nQuery), isEmpty, reason: '保存不该顺手重查整页');
    expect(find.textContaining('1002.Name → translated'), findsOneWidget);
  });

  testWidgets('清理孤立必须先预检，确认后才执行写操作', (tester) async {
    await openI18n(tester);
    gateway.calls.clear();

    await tester.tap(find.byKey(const ValueKey('wb.i18nActionsMenu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.i18nCompactPreview')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nCompactPlan')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('wb.i18nCompactPlan')),
        matching: find.textContaining('将清理 0 条孤立'),
      ),
      findsOneWidget,
    );
    expect(
      gateway.of(Methods.i18nCompact).single.params['dryRun'],
      isTrue,
      reason: '预检不能带 dryRun=false',
    );

    await tester.tap(find.byKey(const ValueKey('wb.i18nCompactApply')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nCompactConfirm')), findsOneWidget);
    expect(find.text('9999.Name'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.i18nCompactGo')));
    await tester.pumpAndSettle();
    final applies = gateway.of(Methods.i18nCompact);
    expect(applies, hasLength(2));
    expect(applies.last.params['dryRun'], isFalse);
  });

  testWidgets('取消预检不会执行任何写操作', (tester) async {
    await openI18n(tester);
    await tester.tap(find.byKey(const ValueKey('wb.i18nActionsMenu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.i18nCompactPreview')));
    await tester.pumpAndSettle();
    gateway.calls.clear();

    await tester.tap(find.byKey(const ValueKey('wb.i18nCompactApply')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();

    expect(gateway.of(Methods.i18nCompact), isEmpty, reason: '未确认就不许删');
    expect(gateway.of(Methods.i18nSave), isEmpty);
  });

  testWidgets('同步与进度总览显示内核给出的数字', (tester) async {
    await openI18n(tester);
    expect(find.byKey(const ValueKey('wb.i18nProgress')), findsOneWidget);
    expect(find.textContaining('en　已翻译 1　缺失 1'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.i18nSyncTable')));
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.i18nSync).single.params, {
      'table': 'Item',
    }, reason: '本表同步必须带表名');
    expect(find.textContaining('已同步 1 张表'), findsOneWidget);
  });

  testWidgets('选择条目后显示专注编辑器和多行编辑器布局', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.i18nFocusDialog')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.i18nEditor')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.i18nEditorKey')), findsOneWidget);
    expect(find.text('Item · en'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.i18nEditorSource')), findsOneWidget);
    final field = tester.widget<TextField>(
      find.byKey(const ValueKey('wb.i18nEditorText')),
    );
    expect(field.expands, isTrue);
    expect(field.minLines, isNull);
    expect(field.maxLines, isNull);
    expect(field.textAlignVertical, TextAlignVertical.top);
    expect(field.decoration?.contentPadding, const EdgeInsets.all(10));
    expect(field.textInputAction, TextInputAction.newline);

    final source = find.byKey(const ValueKey('wb.i18nEditorSource'));
    final target = find.byKey(const ValueKey('wb.i18nEditorText'));
    final sourceBox = tester.getRect(source);
    final targetBox = tester.getRect(target);
    expect(targetBox.top, closeTo(sourceBox.top, 1));
    expect(targetBox.height, sourceBox.height);
    final sourceText = tester.getRect(
      find.descendant(of: source, matching: find.text('铁盾')),
    );
    final hint = tester.getRect(find.text('输入译文，支持多行…'));
    expect(hint.top - targetBox.top, lessThan(30));
    expect(
      hint.top - targetBox.top,
      closeTo(sourceText.top - sourceBox.top, 4),
    );
  });

  testWidgets('专注编辑器按 Enter 换行、失焦不保存', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    final field = find.byKey(const ValueKey('wb.i18nEditorText'));
    await tester.enterText(field, '第一行\n第二行');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();

    final editable = tester.widget<EditableText>(
      find.descendant(of: field, matching: find.byType(EditableText)),
    );
    expect(editable.controller.text, contains('\n'));
    expect(gateway.of(Methods.i18nSave), isEmpty, reason: 'Enter 不能触发保存');

    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.i18nSave), isEmpty, reason: '专注编辑器不能失焦自动保存');
    expect(translations.draftDirty, isTrue);
  });

  testWidgets('Ctrl/Cmd+Enter 保存并确认当前多行译文', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    await tester.enterText(
      find.byKey(const ValueKey('wb.i18nEditorText')),
      'Iron Shield\n第二条',
    );
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    final saves = gateway.of(Methods.i18nSave);
    expect(saves, hasLength(1));
    expect(saves.single.params['key'], '1002.Name');
    expect(saves.single.params['text'], 'Iron Shield\n第二条');
    expect(saves.single.params['confirmed'], isTrue);
    expect(translations.draftDirty, isFalse);
  });

  testWidgets('Esc 放弃专注编辑器草稿且不写盘', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    final field = find.byKey(const ValueKey('wb.i18nEditorText'));
    await tester.enterText(field, '临时修改');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();

    final editable = tester.widget<EditableText>(
      find.descendant(of: field, matching: find.byType(EditableText)),
    );
    expect(editable.controller.text, '');
    expect(translations.draftDirty, isFalse);
    expect(gateway.of(Methods.i18nSave), isEmpty);
  });

  testWidgets('有未保存草稿时切换条目先提示，放弃后切换', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const ValueKey('wb.i18nEditorText')),
      '未保存译文',
    );

    await tester.tap(find.byKey(const ValueKey('wb.i18nFocusClose')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nDraftPrompt')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.i18nDraftDiscard')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nFocusDialog')), findsNothing);
    await tester.tap(find.text('1001.Name').first);
    await tester.pumpAndSettle();
    expect(translations.selectedKey, '1001.Name');
    final editable = tester.widget<EditableText>(
      find.descendant(
        of: find.byKey(const ValueKey('wb.i18nEditorText')),
        matching: find.byType(EditableText),
      ),
    );
    expect(editable.controller.text, 'Iron Sword');
  });

  testWidgets('输入法组合态下 Ctrl+Enter 不提交草稿', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    final field = find.byKey(const ValueKey('wb.i18nEditorText'));
    final editable = tester.widget<EditableText>(
      find.descendant(of: field, matching: find.byType(EditableText)),
    );
    editable.controller.value = const TextEditingValue(
      text: '候',
      selection: TextSelection.collapsed(offset: 1),
      composing: TextRange(start: 0, end: 1),
    );
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(gateway.of(Methods.i18nSave), isEmpty);
  });

  testWidgets('未修改的缺失译文仍能确认，确认后按钮禁用', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    await tester.tap(find.byKey(const ValueKey('wb.i18nEditorSave')));
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.i18nSave), hasLength(1));
    expect(gateway.of(Methods.i18nSave).single.params['confirmed'], isTrue);
    expect(translations.selectedEntry?.confirmed, isTrue);
    final button = tester.widget<CtButton>(
      find.byKey(const ValueKey('wb.i18nEditorSave')),
    );
    expect(button.onPressed, isNull);
  });

  testWidgets('行内保存失败不丢输入，失焦后可重试', (tester) async {
    await openI18n(tester);
    gateway.failSave = true;
    final cell = find.byKey(const ValueKey('wb.i18nCell.1002.Name'));
    await tester.enterText(cell, 'Retry me');
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.i18nSave), hasLength(1));
    expect(find.text('Retry me'), findsOneWidget);
    gateway.failSave = false;
    await tester.tap(cell);
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    expect(gateway.of(Methods.i18nSave), hasLength(2));
    expect(translations.entries[1].text, 'Retry me');
  });

  testWidgets('专注编辑默认隐藏，窄窗口点击词条才打开', (tester) async {
    await openI18n(tester, size: const Size(1024, 700));
    expect(find.byKey(const ValueKey('wb.i18nEditor')), findsNothing);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nFocusDialog')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.i18nEditorText')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('行内编辑确认前先提交当前输入，失败时不确认也不切到专注编辑', (tester) async {
    await openI18n(tester);
    final field = find.byKey(const ValueKey('wb.i18nCell.1002.Name'));
    await tester.enterText(field, '临时译文');
    gateway.failSave = true;
    await tester.tap(find.byKey(const ValueKey('wb.i18nConfirmed.1002.Name')));
    await tester.pumpAndSettle();
    expect(translations.entries[1].confirmed, isFalse);
    expect(find.text('临时译文'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.i18nEdit.1002.Name')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nFocusDialog')), findsNothing);
    gateway.failSave = false;
    await tester.tap(find.byKey(const ValueKey('wb.i18nConfirmed.1002.Name')));
    await tester.pumpAndSettle();
    expect(translations.entries[1].text, '临时译文');
    expect(translations.entries[1].confirmed, isTrue);
  });

  testWidgets('主列表填满宽窗口，不只占内容左半部', (tester) async {
    await openI18n(tester, size: const Size(1550, 1073));
    final filters = tester.getSize(
      find.byKey(const ValueKey('wb.i18nFilters')),
    );
    final rows = tester.getSize(find.byKey(const ValueKey('wb.i18nRows')));
    expect(filters.width, greaterThan(1100));
    expect(rows.width, closeTo(filters.width, 2));
    expect(rows.height, greaterThan(500));
    expect(find.byKey(const ValueKey('wb.i18nEditor')), findsNothing);
    expect(find.byKey(const ValueKey('wb.i18nCell.1002.Name')), findsOneWidget);
  });

  for (final (label, size, pixelRatio) in [
    ('宽窗口', const Size(1550, 1073), 1.0),
    ('1024×700 的 150% 缩放', const Size(1024, 700), 1.5),
  ]) {
    testWidgets('$label 下四个工具按钮等宽等高并对齐', (tester) async {
      await openI18n(tester, size: size, pixelRatio: pixelRatio);
      final actions = [
        'wb.i18nRefresh',
        'wb.i18nSyncTable',
        'wb.i18nColumnsMenu',
        'wb.i18nActionsMenu',
      ];
      final bounds = [
        for (final action in actions)
          tester.getRect(find.byKey(ValueKey(action))),
      ];
      for (final rect in bounds) {
        expect(rect.size, const Size(92, 40));
        expect(rect.top, bounds.first.top);
      }
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('窄窗口筛选栏与列表同宽，词条仍可直接输入', (tester) async {
    await openI18n(tester, size: const Size(1024, 700));
    final filters = tester.getSize(
      find.byKey(const ValueKey('wb.i18nFilters')),
    );
    final rows = tester.getSize(find.byKey(const ValueKey('wb.i18nRows')));
    expect(rows.width, closeTo(filters.width, 2));
    expect(find.byKey(const ValueKey('wb.i18nCell.1002.Name')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('长原文在有限高度内滚动，不会撑开专注编辑区', (tester) async {
    gateway.longSource = List.filled(80, '一段较长的原文').join('\n');
    await openI18n(tester, size: const Size(1024, 700));
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    final source = find.byKey(const ValueKey('wb.i18nEditorSource'));
    expect(tester.getSize(source).height, 160);
    final scrollables = find.descendant(
      of: source,
      matching: find.byType(Scrollable),
    );
    expect(scrollables, findsWidgets);
    expect(
      tester.state<ScrollableState>(scrollables.first).position.maxScrollExtent,
      greaterThan(0),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('1024×700、150% 缩放下选中编辑器无溢出', (tester) async {
    await openI18n(tester, size: const Size(1024, 700), pixelRatio: 1.5);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.i18nEditorText')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('聚焦翻译编辑器时 Ctrl+S 不触发翻译写入', (tester) async {
    await openI18n(tester);
    await tester.tap(find.text('1002.Name').first);
    await tester.pumpAndSettle();
    gateway.calls.clear();

    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.keyS);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    await tester.pumpAndSettle();

    expect(gateway.of(Methods.i18nSave), isEmpty);
  });
}
