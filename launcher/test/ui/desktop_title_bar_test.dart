import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/desktop_title_bar.dart';
import 'package:ct_launcher/ui/widgets/status_badge.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  /// 标题栏左侧只剩导航栏图标、右侧只剩窗口按钮时，状态与快速打开整组居中。
  testWidgets('状态徽标与快速打开在标题栏里水平居中', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: CtDesktopTitleBar(
            title: 'ct 配表工作台',
            statusLabel: '原生内核已连接',
            onQuickOpen: () {},
            sidebarWidth: 56,
            sidebarToggle: const Icon(Icons.chevron_right, size: 16),
            onMinimize: () {},
            onToggleMaximize: () {},
            onClose: () {},
          ),
        ),
      ),
    );

    final bar = tester.getRect(
      find.byKey(const ValueKey('ct.desktopTitleBar')),
    );
    final badge = tester.getRect(find.byType(CtStatusBadge));
    final quickOpen = tester.getRect(
      find.byKey(const ValueKey('ct.titleBar.quickOpen')),
    );
    // 整组（徽标左缘到快速打开右缘）的中线落在标题栏中线；两侧各留 4px 内边距。
    expect((badge.left + quickOpen.right) / 2, closeTo(bar.center.dx, 6));
    // 不再贴着窗口按钮。
    expect(bar.right - quickOpen.right, greaterThan(160));
  });

  testWidgets('自绘标题栏展示菜单、状态与窗口按钮', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    var minimized = 0;
    var toggled = 0;
    var closed = 0;
    var reloaded = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: CtDesktopTitleBar(
            title: 'ct 配表工作台',
            subtitle: 'Schema',
            statusLabel: '内核已连接',
            onQuickOpen: () {},
            menus: [
              CtTitleBarMenu(
                label: '文件',
                actions: [
                  CtTitleBarAction(
                    label: '重新加载工作区',
                    onSelected: () => reloaded++,
                  ),
                ],
              ),
            ],
            onMinimize: () => minimized++,
            onToggleMaximize: () => toggled++,
            onClose: () => closed++,
          ),
        ),
      ),
    );

    expect(find.text('ct 配表工作台'), findsOneWidget);
    expect(find.text('Schema'), findsOneWidget);
    expect(find.text('内核已连接'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('ct.titleBar.menu.文件')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重新加载工作区'));
    await tester.pumpAndSettle();
    expect(reloaded, 1);

    await tester.tap(find.byKey(const ValueKey('ct.windowMinimize')));
    await tester.tap(find.byKey(const ValueKey('ct.windowToggleMaximize')));
    await tester.tap(find.byKey(const ValueKey('ct.windowClose')));
    expect(minimized, 1);
    expect(toggled, 1);
    expect(closed, 1);
  });

  testWidgets('1024 宽窄窗口下标题栏不溢出', (tester) async {
    tester.view.physicalSize = const Size(1024, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: Scaffold(
          body: CtDesktopTitleBar(
            title: 'ct 配表工作台',
            subtitle: 'Schema',
            statusLabel: '原生内核已连接',
            onQuickOpen: () {},
            menus: [
              CtTitleBarMenu(
                label: '文件',
                actions: [CtTitleBarAction(label: '设置', onSelected: () {})],
              ),
              CtTitleBarMenu(
                label: '编辑',
                actions: [CtTitleBarAction(label: '保存草稿', onSelected: () {})],
              ),
              CtTitleBarMenu(
                label: '视图',
                actions: [CtTitleBarAction(label: '总览', onSelected: () {})],
              ),
              CtTitleBarMenu(
                label: '帮助',
                actions: [CtTitleBarAction(label: '帮助与快捷键', onSelected: () {})],
              ),
            ],
            onMinimize: () {},
            onToggleMaximize: () {},
            onClose: () {},
          ),
        ),
      ),
    );

    expect(tester.takeException(), isNull);

    // 窄窗口收起徽标，快速打开依然居中，不挤到窗口按钮上。
    final bar = tester.getRect(
      find.byKey(const ValueKey('ct.desktopTitleBar')),
    );
    expect(find.byType(CtStatusBadge), findsNothing);
    expect(
      tester
          .getRect(find.byKey(const ValueKey('ct.titleBar.quickOpen')))
          .center
          .dx,
      closeTo(bar.center.dx, 4),
    );
  });
}
