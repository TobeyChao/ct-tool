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
  Size size = const Size(1280, 800),
  double scale = 1.0,
  String workspaceKey = 'mock-test',
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(data: data, workspaceKey: workspaceKey),
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

  testWidgets('四区壳渲染：资源区/编辑区/属性区/任务区与 MOCK 标识', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    expect(find.text('资源'), findsOneWidget);
    expect(find.text('属性'), findsOneWidget);
    expect(find.text('任务'), findsOneWidget);
    expect(find.text('保存'), findsOneWidget);
    expect(find.textContaining('模拟数据（MOCK）'), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.inspectorPanel')), findsOneWidget);
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
    expect(find.text('暂无任务'), findsOneWidget);
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

  testWidgets('忙碌：锁定提示与运行中任务进度', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.busy));
    expect(find.textContaining('导出进行中'), findsOneWidget);
    expect(find.text('运行中'), findsOneWidget);
    expect(find.text('1 进行中'), findsOneWidget);
    await tester.tap(find.text('hero').first);
    await tester.pump();
    final save = tester.widget<CtButton>(find.byKey(const ValueKey('wb.save')));
    expect(save.onPressed, isNull);
  });

  testWidgets('最小窗口 1024x700 + 150% 缩放 + 长文本：无溢出且辅助区自动折叠', (tester) async {
    await pumpWorkbench(
      tester,
      mockWorkspaceFor(MockScenario.longText),
      size: const Size(1024, 700),
      scale: 1.5,
    );
    // 窄窗口首帧自动折叠资源区与属性区
    expect(find.byKey(const ValueKey('wb.strip.resource')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.strip.inspector')), findsOneWidget);
    // 手动展开后仍不得溢出（FlutterError 会使测试失败）
    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('wb.strip.resource')),
        matching: find.byType(IconButton),
      ),
    );
    await tester.pump();
    await tester.tap(
      find.descendant(
        of: find.byKey(const ValueKey('wb.strip.inspector')),
        matching: find.byType(IconButton),
      ),
    );
    await tester.pump();
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsOneWidget);
    await tester.tap(
      find
          .text('英雄配置表_超长名称_hero_config_with_a_very_long_english_suffix_v2')
          .first,
    );
    await tester.pump();
  });

  testWidgets('1280x800 + 125% 缩放：全部场景渲染无溢出', (tester) async {
    for (final scenario in MockScenario.values) {
      await pumpWorkbench(
        tester,
        mockWorkspaceFor(scenario),
        scale: 1.25,
        workspaceKey: 'mock-test-$scenario',
      );
      await tester.tap(find.text('任务'));
      await tester.pump();
    }
  });

  testWidgets('模块切换：未接入模块显示占位与计划任务号', (tester) async {
    await pumpWorkbench(tester, mockWorkspaceFor(MockScenario.normal));
    await tester.tap(find.text('翻译'));
    await tester.pump();
    expect(find.textContaining('需要接上内核数据源'), findsOneWidget);
    await tester.tap(find.text('历史'));
    await tester.pump();
    expect(find.textContaining('任务 4.8'), findsOneWidget);
    await tester.tap(find.text('总览'));
    await tester.pump();
    expect(find.text('工作区总览'), findsOneWidget);
  });
}
