import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/tokens.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/mock/mock_data.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<void> pumpWorkbench(
  WidgetTester tester,
  MockWorkspaceData data, {
  // 默认按受支持的最大档量测：侧栏 248 + 资源 220 + 属性 280 在 1440 可全展开。
  Size size = const Size(1440, 900),
  double scale = 1.0,
  String workspaceKey = 'mock-test',
  bool showDesktopTitleBar = false,
  double titleBarLeadingInset = 0,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: data,
          workspaceKey: workspaceKey,
          showDesktopTitleBar: showDesktopTitleBar,
          titleBarLeadingInset: titleBarLeadingInset,
          showWindowControls: false,
        ),
      ),
    ),
  );
  // 等异步布局加载 + 自动折叠 postFrame
  await tester.pump();
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('三区壳渲染：资源区/编辑区/属性区', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    expect(find.text('资源'), findsOneWidget);
    expect(find.text('属性'), findsOneWidget);
    expect(find.text('保存'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.kernelStatus')), findsNothing);
    expect(find.byKey(const ValueKey('wb.settingsDivider')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.moduleHeader')), findsNothing);
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.inspectorPanel')), findsOneWidget);

    final sidebar = tester.getRect(find.byKey(const ValueKey('wb.sidebar')));
    final settings = tester.getRect(find.byKey(const ValueKey('wb.nav.设置')));
    final leftGap = settings.left - sidebar.left;
    final rightGap = sidebar.right - settings.right;
    final bottomGap = sidebar.bottom - settings.bottom;
    expect(leftGap, moreOrLessEquals(rightGap, epsilon: 0.1));
    expect(leftGap, moreOrLessEquals(bottomGap, epsilon: 0.1));
  });

  testWidgets('生产标题栏不渲染旧菜单与侧栏品牌头', (tester) async {
    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.normal),
      showDesktopTitleBar: true,
    );

    final titleBar = find.byKey(const ValueKey('ct.desktopTitleBar'));
    expect(titleBar, findsOneWidget);
    expect(
      (tester.widget<Container>(titleBar).decoration! as BoxDecoration).border,
      isNull,
    );
    void expectJoinedEdge(String railKey) {
      final rail = tester.getRect(find.byKey(ValueKey(railKey)));
      final sidebarEdge = tester.getRect(
        find.byKey(const ValueKey('ct.titleBar.sidebarEdge')),
      );
      final contentEdge = tester.getRect(
        find.byKey(const ValueKey('ct.titleBar.contentEdge')),
      );
      expect(sidebarEdge.right, rail.right);
      expect(sidebarEdge.bottom, rail.top);
      expect(contentEdge.left, rail.right);
      expect(contentEdge.bottom, tester.getRect(titleBar).bottom);
    }

    expectJoinedEdge('wb.sidebar');
    expect(
      find.descendant(of: titleBar, matching: find.byType(CtBrandMark)),
      findsOneWidget,
    );
    expect(
      find.descendant(of: titleBar, matching: find.text('gd')),
      findsOneWidget,
    );
    for (final label in ['文件', '编辑', '视图', '帮助']) {
      expect(find.text(label), findsNothing);
    }
    final toggle = find.byKey(const ValueKey('wb.collapse.sidebar'));
    expect(toggle, findsOneWidget);
    expect(find.text('工作流'), findsOneWidget);
    expect(
      tester.getRect(toggle).center.dy,
      lessThan(tester.getRect(find.byKey(const ValueKey('wb.sidebar'))).top),
    );
    expect(
      tester.getRect(find.text('工作流')).top,
      lessThan(
        tester.getRect(find.byKey(const ValueKey('wb.sidebar'))).top + 45,
      ),
    );
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.iconRail')), findsOneWidget);
    expectJoinedEdge('wb.iconRail');
    final railCenter = tester
        .getRect(find.byKey(const ValueKey('wb.iconRail')))
        .center
        .dx;
    final expandCenter = tester
        .getRect(find.byKey(const ValueKey('wb.expand.sidebar')))
        .center
        .dx;
    final navCenter = tester
        .getRect(find.byKey(const ValueKey('wb.navTap.Schema')))
        .center
        .dx;
    expect(expandCenter, closeTo(railCenter, 0.5));
    expect(expandCenter, closeTo(navCenter, 0.5));
    expect(
      find.descendant(of: titleBar, matching: find.byType(CtBrandMark)),
      findsNothing,
    );
    expect(
      find.descendant(of: titleBar, matching: find.text('gd')),
      findsNothing,
    );
    expect(
      find.descendant(of: titleBar, matching: find.text('Schema')),
      findsNothing,
    );
    await tester.tap(find.byKey(const ValueKey('wb.expand.sidebar')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.sidebar')), findsOneWidget);
    expect(
      find.descendant(of: titleBar, matching: find.text('gd')),
      findsOneWidget,
    );
  });

  testWidgets('无标题栏的侧栏展开按钮与图标导航水平对齐', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    await tester.tap(find.byKey(const ValueKey('wb.collapse.sidebar')));
    await tester.pumpAndSettle();
    final rail = tester.getRect(find.byKey(const ValueKey('wb.iconRail')));
    final expand = tester.getRect(
      find.byKey(const ValueKey('wb.expand.sidebar')),
    );
    final nav = tester.getRect(find.byKey(const ValueKey('wb.navTap.Schema')));
    expect(expand.center.dx, closeTo(rail.center.dx, 0.5));
    expect(expand.center.dx, closeTo(nav.center.dx, 0.5));
  });

  testWidgets('交通灯占满窄栏时展开按钮在栏内居中', (tester) async {
    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.normal),
      showDesktopTitleBar: true,
      titleBarLeadingInset: 72,
    );
    await tester.tap(find.byKey(const ValueKey('wb.collapse.sidebar')));
    await tester.pumpAndSettle();
    final rail = tester.getRect(find.byKey(const ValueKey('wb.iconRail')));
    final expand = find.byKey(const ValueKey('wb.expand.sidebar'));
    expect(tester.getRect(expand).center.dx, closeTo(rail.center.dx, 0.5));
    expect(tester.getRect(expand).top, greaterThanOrEqualTo(rail.top));
    expect(tester.takeException(), isNull);
    await tester.tap(expand);
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.sidebar')), findsOneWidget);
  });

  testWidgets('选择资源与字段后属性区联动', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    await tester.tap(find.text('hero').first);
    await tester.pump();
    expect(find.text('字段 · 8'), findsOneWidget);
    await tester.tap(find.text('base_hp'));
    await tester.pump();
    expect(find.text('字段名'), findsOneWidget);
    expect(find.text('默认值'), findsWidgets);
  });

  testWidgets('侧栏可折叠为图标栏，保留导航并按工作区恢复', (tester) async {
    final data = mockWorkspaceFor(MockScenario.normal);
    await pumpWorkbench(tester, data, workspaceKey: 'sidebar-a');
    expect(find.byTooltip('收起侧栏'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wb.collapse.sidebar')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.iconRail')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.sidebar')), findsNothing);
    expect(
      tester.getSize(find.byKey(const ValueKey('wb.iconRail'))).width,
      ctNavRailWidth,
    );
    await tester.tap(find.byKey(const ValueKey('wb.navTap.总览')));
    await tester.pumpAndSettle();
    expect(find.text('工作区总览'), findsOneWidget);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('wb.sidebar-a.collapse.v2.sidebar'), isTrue);

    await tester.pumpWidget(const SizedBox());
    await pumpWorkbench(tester, data, workspaceKey: 'sidebar-a');
    expect(find.byKey(const ValueKey('wb.iconRail')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wb.expand.sidebar')));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.sidebar')), findsOneWidget);
    expect(prefs.getBool('wb.sidebar-a.collapse.v2.sidebar'), isFalse);
  });

  testWidgets('资源区可折叠为窄条并恢复', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    await tester.tap(find.byKey(const ValueKey('wb.collapse.resource')));
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsNothing);
    expect(find.byKey(const ValueKey('wb.strip.resource')), findsOneWidget);
    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('wb.strip.resource')),
        matching: find.byType(IconButton),
      ),
    );
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsOneWidget);
  });

  testWidgets('资源和属性窄条的展开按钮与各自窄条水平居中', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    for (final zone in const ['resource', 'inspector']) {
      await tester.tap(find.byKey(ValueKey('wb.collapse.$zone')));
      await tester.pumpAndSettle();
      final strip = find.byKey(ValueKey('wb.strip.$zone'));
      final expand = find.descendant(
        of: strip,
        matching: find.byType(IconButton),
      );
      expect(expand, findsOneWidget);
      expect(
        tester.getRect(expand).center.dx,
        closeTo(tester.getRect(strip).center.dx, 0.5),
      );
      await tester.tap(expand);
      await tester.pumpAndSettle();
      expect(find.byKey(ValueKey('wb.strip.$zone')), findsNothing);
    }
  });

  testWidgets('资源区折叠使用 200ms 过渡', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));

    final expandedResourceWidth = tester
        .getSize(find.byKey(const ValueKey('wb.resourcePanel')))
        .width;
    await tester.tap(find.byKey(const ValueKey('wb.collapse.resource')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    final resourceMotion = find
        .ancestor(
          of: find.byKey(const ValueKey('wb.strip.resource')),
          matching: find.byType(AnimatedSize),
        )
        .first;
    final midResourceWidth = tester.getSize(resourceMotion).width;
    expect(midResourceWidth, lessThan(expandedResourceWidth));
    expect(midResourceWidth, greaterThan(ctCollapsedStripWidth));
    await tester.pumpAndSettle();
    expect(tester.getSize(resourceMotion).width, ctCollapsedStripWidth);
  });

  testWidgets('拖拽手柄调整资源区宽度并按工作区记忆', (tester) async {
    final data = mockWorkspaceFor(MockScenario.normal);
    await pumpWorkbench(tester, data, size: const Size(1440, 900));
    await tester.drag(
      find.byKey(const ValueKey('wb.handle.resource')),
      const Offset(40, 0),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
    expect(
      tester.getSize(find.byKey(const ValueKey('wb.resourcePanel'))).width,
      ctResourcePanelDefault + 40,
    );

    // 重启（新 State）后保持宽度：同一 workspaceKey 读取持久化布局
    await tester.pumpWidget(const SizedBox());
    await pumpWorkbench(tester, data, size: const Size(1440, 900));
    expect(
      tester.getSize(find.byKey(const ValueKey('wb.resourcePanel'))).width,
      ctResourcePanelDefault + 40,
    );
  });

  testWidgets('空工作区：空态与新建入口', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.empty));
    expect(find.text('工作区还没有任何资源'), findsOneWidget);
    expect(find.text('新建资源'), findsOneWidget);
    expect(find.text('从左侧选择资源，或新建 Table / Record / Enum'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('wb.emptyNewTable')));
    await tester.pump();
    expect(find.text('界面样板未连接原生内核，无法新建资源'), findsOneWidget);
  });

  testWidgets('加载失败：错误面板与重试入口', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.loadError));
    expect(find.text('资源加载失败'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
    expect(find.textContaining('hero.yaml'), findsWidgets);
  });

  testWidgets('候选冲突：警告条展示且保存锁定', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.conflict));
    expect(find.textContaining('候选已过期'), findsOneWidget);
    expect(find.text('放弃并重载'), findsOneWidget);
    final save = tester.widget<CtButton>(find.byKey(const ValueKey('wb.save')));
    expect(save.onPressed, isNull);
    await tester.tap(find.text('hero').first);
    await tester.pump();
    expect(find.textContaining('候选已过期'), findsOneWidget);
    final save2 = tester.widget<CtButton>(
      find.byKey(const ValueKey('wb.save')),
    );
    expect(save2.onPressed, isNull);
  });

  testWidgets('忙碌：锁定写入口并提供查看导出入口', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.busy));
    expect(find.textContaining('导出进行中'), findsOneWidget);
    expect(find.text('查看导出'), findsOneWidget);
    await tester.tap(find.text('hero').first);
    await tester.pump();
    final save = tester.widget<CtButton>(find.byKey(const ValueKey('wb.save')));
    expect(save.onPressed, isNull);
  });

  testWidgets('1024x700 + 150% 缩放 + 长文本：无溢出，辅助区按优先级自动折叠', (tester) async {
    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.longText),
      size: const Size(1024, 700),
      scale: 1.5,
      workspaceKey: 'mock-1024',
    );
    // 断点按整窗宽度算：1024 先收起属性区，再收起资源区，优先保住六列表格。
    expect(
      find.byKey(const ValueKey('wb.strip.inspector')),
      findsOneWidget,
      reason: '窗口 1024 < 1360：属性区应自动折叠',
    );
    expect(
      find.byKey(const ValueKey('wb.strip.resource')),
      findsOneWidget,
      reason: '窗口 1024 < 1120：资源区应自动折叠，但保留可展开窄条',
    );
    expect(
      find.byKey(const ValueKey('wb.sidebar')),
      findsOneWidget,
      reason: '窗口 1024 ≥ 740：侧栏保持文字形态',
    );
    // 手动展开两个辅助区后仍不得溢出（FlutterError 会让本用例直接失败）。
    for (final zone in const ['resource', 'inspector']) {
      await tester.tap(
        find.descendant(
          of: find.byKey(ValueKey('wb.strip.$zone')),
          matching: find.byType(IconButton),
        ),
      );
      await tester.pumpAndSettle();
    }
    await tester.tap(
      find
          .text('英雄配置表_超长名称_hero_config_with_a_very_long_english_suffix_v2')
          .first,
    );
    await tester.pump();
  });

  testWidgets('自动折叠不落盘，旧断点偏好被忽略，手动展开才按工作区恢复', (tester) async {
    SharedPreferences.setMockInitialValues({
      'wb.mock-collapse.inspectorCollapsed': false,
    });
    final data = mockWorkspaceFor(MockScenario.normal);
    await pumpWorkbench(
      tester,
      data,
      size: const Size(1280, 800),
      workspaceKey: 'mock-collapse',
    );
    expect(
      find.byKey(const ValueKey('wb.strip.inspector')),
      findsOneWidget,
      reason: '旧 key 不能被当作手动展开而覆盖新断点',
    );

    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('wb.strip.inspector')),
        matching: find.byType(IconButton),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.inspectorPanel')), findsOneWidget);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('wb.mock-collapse.collapse.v2.inspector'), isFalse);

    await tester.pumpWidget(const SizedBox());
    await pumpWorkbench(
      tester,
      data,
      size: const Size(1280, 800),
      workspaceKey: 'mock-collapse',
    );
    expect(
      find.byKey(const ValueKey('wb.inspectorPanel')),
      findsOneWidget,
      reason: '用户手动展开后，同一工作区重启应恢复',
    );
  });

  testWidgets('900 宽折资源区、700 宽侧栏收成图标栏（断点按整窗宽度）', (tester) async {
    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.longText),
      size: const Size(900, 700),
      workspaceKey: 'mock-900',
    );
    expect(find.byKey(const ValueKey('wb.strip.resource')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.sidebar')), findsOneWidget);

    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.longText),
      size: const Size(700, 700),
      workspaceKey: 'mock-700',
    );
    expect(
      find.byKey(const ValueKey('wb.iconRail')),
      findsOneWidget,
      reason: '窗口 700 < 740：侧栏收成 56px 图标栏（web 的抽屉断点）',
    );
    expect(find.byKey(const ValueKey('wb.nav.设置')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('wb.settingsDivider.compact')),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const ValueKey('wb.expand.sidebar')));
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.sidebar')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.kernelStatus')), findsNothing);
    expect(find.byKey(const ValueKey('wb.kernelStatus.compact')), findsNothing);
    expect(find.byKey(const ValueKey('wb.nav.设置')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.settingsDivider')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('wb.settingsDivider.compact')),
      findsNothing,
    );
    expect(find.byKey(const ValueKey('wb.docsEntry')), findsNothing);
  });

  testWidgets('1280x800 + 125% 缩放：全部场景渲染无溢出', (tester) async {
    for (final scenario in MockScenario.values) {
      await pumpWorkbench(
        tester,
        mockWorkspaceFor(scenario),
        scale: 1.25,
        workspaceKey: 'mock-test-$scenario',
      );
    }
  });

  testWidgets('模块切换：未接入模块与无数据记录页都给出明确空态', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    await tester.tap(find.text('翻译'));
    await tester.pump();
    expect(find.textContaining('需要接上内核数据源'), findsOneWidget);
    await tester.tap(find.text('历史'));
    await tester.pump();
    expect(find.textContaining('需要接上内核数据源'), findsOneWidget);
    await tester.tap(find.text('总览'));
    await tester.pump();
    expect(find.text('工作区总览'), findsOneWidget);
  });
}
