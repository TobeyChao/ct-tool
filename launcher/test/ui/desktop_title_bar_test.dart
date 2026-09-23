import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/desktop_title_bar.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
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
  });
}
