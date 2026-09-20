import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
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
                  _entry('1002.Name', '铁盾', '', false, 'missing'),
                ]
              : [_entry('1003.Name', '长弓', 'Long Bow', false, 'stale')],
          if (first && hasMore) 'nextCursor': 'cursor-2',
        };
      case Methods.i18nSave:
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

  Future<void> openI18n(WidgetTester tester) async {
    await translations.bind('D:/game/A');
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(1500, 1100);
    tester.view.devicePixelRatio = 1.0;
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
}
