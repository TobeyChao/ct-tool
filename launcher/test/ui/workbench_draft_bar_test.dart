import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:ct_launcher/ui/workbench/workbench_shortcuts.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 全局草稿条 + 净差异 + 步骤撤销 + 放弃确认 + 快捷键 + 帮助
/// （native-flutter-workbench 任务 4.9，含 3.7 的 Quick Open 键位）。
class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<Map<String, Object?>> candidates = [];
  final List<Map<String, Object?>> saves = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-bar';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 5,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 1,
          'records': 0,
          'enums': 1,
        };
      case Methods.resourcesList:
        return {
          'revision': 5,
          'schemaRevision': 'baseline-sha',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
            {
              'name': 'Quality',
              'kind': 'enum',
              'sourcePath': 'config/schemas/quality.yaml',
            },
          ],
        };
      case Methods.schemaCandidate:
        candidates.add(params);
        return {
          'candidateHash': 'hash-bar',
          'draftGeneration': params['draftGeneration'],
          'netDiff': {
            'added': [
              {'kind': 'table', 'name': 'Hero'},
            ],
            'removed': <Object?>[],
            'changed': [
              {
                'kind': 'enum',
                'name': 'Quality',
                'change': 'modified',
                'fields': [
                  {
                    'name': 'Legendary',
                    'change': 'renamed',
                    'oldName': 'Mythic',
                    'details': ['ordinal 1 → 3 · wire 风险'],
                  },
                ],
              },
            ],
          },
          'problems': <Object?>[],
        };
      case Methods.schemaSave:
        saves.add(params);
        return {'schemaRevision': 'new-baseline-bar'};
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

Future<void> _press(
  WidgetTester tester,
  LogicalKeyboardKey key, {
  LogicalKeyboardKey? modifier,
  bool shift = false,
}) async {
  final mods = <LogicalKeyboardKey>[
    ?modifier,
    if (shift) LogicalKeyboardKey.shiftLeft,
  ];
  for (final mod in mods) {
    await tester.sendKeyDownEvent(mod);
  }
  await tester.sendKeyDownEvent(key);
  await tester.sendKeyUpEvent(key);
  for (final mod in mods.reversed) {
    await tester.sendKeyUpEvent(mod);
  }
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late _FakeGateway gateway;
  late WorkbenchRepository repo;
  late SettingsStore settings;

  Future<void> pumpBar(WidgetTester tester) async {
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
          kernelSummary: const ['内核状态：已连接（core 0.9.0-test）'],
          workspaceKey: 'bar-test',
          bannerLabel: '已连接原生内核',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  /// 让焦点落在工作台内部：快捷键只在工作台子树里生效（与真实桌面一致）。
  Future<void> focusWorkbench(WidgetTester tester) async {
    await tester.tap(find.text('Item').first);
    await tester.pumpAndSettle();
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

  testWidgets('草稿条常驻跨模块：草稿步数与净差异计数都来自内核', (tester) async {
    await pumpBar(tester);
    Text summary() =>
        tester.widget<Text>(find.byKey(const ValueKey('wb.draftSummary')));

    // 无草稿、无撤销历史时整条不占位（与 web 的 hidden 同口径）
    expect(find.byKey(const ValueKey('wb.draftSummary')), findsNothing);

    repo.createTable('Hero');
    await tester.pump();
    expect(summary().data, contains('草稿 1 步'));
    expect(summary().data, contains('无未保存修改'), reason: '候选还没算，不能凭空报资源数');

    // 摘要点开弹层：净差异那个 Tab 会自己找内核要候选
    await tester.tap(find.byKey(const ValueKey('wb.draftSummaryTap')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.draftSheet')), findsOneWidget);
    await tester.tap(find.text('净差异'));
    await tester.pumpAndSettle();
    expect(gateway.candidates, hasLength(1));
    expect(
      summary().data,
      contains('2 个资源有未保存修改'),
      reason: '假网关的 netDiff 是 1 新增 + 1 修改',
    );
    expect(summary().data, isNot(contains('未落盘')));
  });

  testWidgets('净差异对话框给出改名身份与 ordinal/wire 风险明细', (tester) async {
    await pumpBar(tester);
    repo.renameEnumItem('Quality', 'Mythic', 'Legendary', 1);
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('wb.draftSummaryTap')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('净差异'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.candidateHash')), findsOneWidget);
    expect(find.text('新增 1'), findsOneWidget);
    expect(find.text('修改 1'), findsOneWidget);
    expect(find.textContaining('renamed Mythic → Legendary'), findsOneWidget);
    expect(find.textContaining('enum:Quality'), findsWidgets);
    expect(
      find.textContaining('ordinal 1 → 3 · wire 风险'),
      findsOneWidget,
      reason: '风险明细必须由内核透传，界面不自己算',
    );
    expect(find.textContaining('config/schemas/quality.yaml'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.diff.scope')), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
  });

  testWidgets('放弃草稿必须确认：取消保留、确认才清命令与游标', (tester) async {
    await pumpBar(tester);
    repo.createTable('Hero');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('wb.draftDiscard')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.draftDiscard.confirm')),
      findsOneWidget,
    );

    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(repo.hasDraft, isTrue);

    await tester.tap(find.byKey(const ValueKey('wb.draftDiscard')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.draftDiscard.confirm')));
    await tester.pumpAndSettle();
    expect(repo.hasDraft, isFalse);
    expect(repo.cursor, 0);
  });

  testWidgets('步骤面板可停在任意一步：逐字段撤销与回基线', (tester) async {
    await pumpBar(tester);
    repo.createTable('Hero');
    repo.addField('table:Hero', 'Price', 'int32');
    await tester.pump();
    expect(repo.cursor, 2);

    await tester.tap(find.byKey(const ValueKey('wb.draftSummaryTap')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.draftStep.1')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.draftStep.2')), findsOneWidget);
    // 弹层不因为一次撤销就关闭：同一层里继续点「回到基线」
    await tester.tap(find.byKey(const ValueKey('wb.draftSteps.stop.1')));
    await tester.pumpAndSettle();
    expect(repo.cursor, 1);

    await tester.tap(find.byKey(const ValueKey('wb.draftSteps.baseline')));
    await tester.pumpAndSettle();
    expect(repo.cursor, 0);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    expect(repo.commands, hasLength(2), reason: '撤销只动游标，命令历史保留可重做');
  });

  testWidgets('Ctrl/Cmd+Z 撤销、+Shift+Z 重做、+S 保存走同一批闸门', (tester) async {
    await pumpBar(tester);
    await focusWorkbench(tester);
    repo.createTable('Hero');
    await tester.pump();
    expect(repo.cursor, 1);

    await _press(
      tester,
      LogicalKeyboardKey.keyZ,
      modifier: LogicalKeyboardKey.control,
    );
    expect(repo.cursor, 0);
    await _press(
      tester,
      LogicalKeyboardKey.keyZ,
      modifier: LogicalKeyboardKey.control,
      shift: true,
    );
    expect(repo.cursor, 1);

    await repo.requestCandidate();
    await tester.pump();
    await _press(
      tester,
      LogicalKeyboardKey.keyS,
      modifier: LogicalKeyboardKey.control,
    );
    expect(gateway.saves, hasLength(1));
    expect(gateway.saves.single['candidateHash'], 'hash-bar');
  });

  testWidgets('输入框聚焦时 Ctrl+Z 让给文本撤销，草稿游标不动', (tester) async {
    await pumpBar(tester);
    await focusWorkbench(tester);
    repo.createTable('Hero');
    await tester.pump();
    // 打开改名对话框：焦点在输入框里。
    await tester.tap(find.byKey(const ValueKey('wb.renameResource')));
    await tester.pumpAndSettle();
    expect(WorkbenchShortcuts.textEditingFocused(), isTrue);

    await _press(
      tester,
      LogicalKeyboardKey.keyZ,
      modifier: LogicalKeyboardKey.control,
    );
    expect(repo.cursor, 1, reason: '文本框里的撤销不该被草稿抢走');
  });

  testWidgets('Ctrl/Cmd+P 呼出 Quick Open：空查询给最近打开，回车跳转', (tester) async {
    await pumpBar(tester);
    await focusWorkbench(tester);
    // 先点一次 Quality，让它进最近清单。
    await tester.tap(find.text('Quality').first);
    await tester.pumpAndSettle();

    await _press(
      tester,
      LogicalKeyboardKey.keyP,
      modifier: LogicalKeyboardKey.control,
    );
    expect(find.byKey(const ValueKey('wb.quickOpen.field')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.quickOpen.hint')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('wb.quickOpen.row.Quality.0')),
        matching: find.text('Quality'),
      ),
      findsOneWidget,
      reason: '空查询必须把最近打开排在最前',
    );

    // 下移一位到 Item，回车跳转。
    await _press(tester, LogicalKeyboardKey.arrowDown);
    await _press(tester, LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.quickOpen.field')), findsNothing);
    expect(repo.previewOf('Item'), isNull);
  });

  testWidgets('Quick Open fuzzy 过滤：子序列命中、无命中时明说', (tester) async {
    await pumpBar(tester);
    await focusWorkbench(tester);
    await _press(
      tester,
      LogicalKeyboardKey.keyP,
      modifier: LogicalKeyboardKey.control,
    );
    await tester.enterText(
      find.byKey(const ValueKey('wb.quickOpen.field')),
      'qua',
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('wb.quickOpen.row.Quality.0')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('wb.quickOpen.row.Item.1')), findsNothing);

    await tester.enterText(
      find.byKey(const ValueKey('wb.quickOpen.field')),
      'zzzz',
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.quickOpen.empty')), findsOneWidget);
  });

  testWidgets('F1 打开帮助：真实键位表与外部文档入口；关于里是真实版本', (tester) async {
    await pumpBar(tester);
    await focusWorkbench(tester);
    await _press(tester, LogicalKeyboardKey.f1);
    expect(find.byKey(const ValueKey('wb.help.title')), findsOneWidget);
    for (final binding in wbShortcutBindings()) {
      expect(
        find.byKey(ValueKey('wb.about.shortcut.${binding.label}')),
        findsOneWidget,
        reason: '帮助里的键位必须与实际绑定同源',
      );
    }
    // 测试环境没有 url_launcher 插件：如实报失败，不假装打开成功。
    await tester.tap(find.byKey(const ValueKey('wb.about.docs')));
    await tester.pumpAndSettle();
    final note = tester.widget<Text>(
      find.byKey(const ValueKey('wb.about.docsResult')),
    );
    expect(note.data, contains('文档：'));
    expect(note.data, isNot(contains('已在系统默认浏览器打开')));
    // 「关于」里才是内核事实
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('wb.aboutEntry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.about.title')), findsOneWidget);
    expect(find.textContaining('core 0.9.0-test'), findsOneWidget);
    await tester.tap(find.text('关闭'));
    await tester.pumpAndSettle();
  });

  testWidgets('样板数据不显示草稿条，但帮助入口仍在', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: repo,
          refresh: repo,
          settings: settings,
          workspaceKey: 'bar-mock',
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    // 样板模式没有内核草稿：条体只留 0 高度占位，不放一排灰按钮
    expect(find.byKey(const ValueKey('wb.draftSummary')), findsNothing);
    expect(find.byKey(const ValueKey('wb.draftSave')), findsNothing);
    expect(find.byKey(const ValueKey('wb.helpEntry')), findsOneWidget);
  });
}
