import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:ct_launcher/services/panel_service.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/ui/pages/settings_page.dart';

void main() {
  Widget wrap(SettingsStore settings, PanelService panel) {
    return MaterialApp(
      home: Scaffold(body: SettingsPage(settings: settings, panel: panel)),
    );
  }

  testWidgets('面板运行中：工作区/端口禁用并提示先停止服务', (tester) async {
    final settings = SettingsStore()
      ..workspacePath = '/tmp/gd'
      ..port = 8000;
    final panel = PanelService(settings: settings)
      ..status = PanelStatus.running;

    await tester.pumpWidget(wrap(settings, panel));
    await tester.pump();

    final wsField = tester.widget<TextField>(
      find.byWidgetPredicate(
        (w) => w is TextField && w.controller?.text == '/tmp/gd',
      ),
    );
    final portField = tester.widget<TextField>(
      find.byWidgetPredicate(
        (w) => w is TextField && w.controller?.text == '8000',
      ),
    );
    expect(wsField.enabled, isFalse);
    expect(portField.enabled, isFalse);

    final browse = tester.widget<TextButton>(
      find.widgetWithText(TextButton, '浏览…'),
    );
    expect(browse.onPressed, isNull);
    expect(find.textContaining('先停止服务'), findsOneWidget);
  });

  testWidgets('面板停止时：工作区/端口可修改', (tester) async {
    final settings = SettingsStore()
      ..workspacePath = '/tmp/gd'
      ..port = 8000;
    final panel = PanelService(settings: settings);

    await tester.pumpWidget(wrap(settings, panel));
    await tester.pump();

    final wsField = tester.widget<TextField>(
      find.byWidgetPredicate(
        (w) => w is TextField && w.controller?.text == '/tmp/gd',
      ),
    );
    final browse = tester.widget<TextButton>(
      find.widgetWithText(TextButton, '浏览…'),
    );
    expect(wsField.enabled, isTrue);
    expect(browse.onPressed, isNotNull);
    expect(find.textContaining('先停止服务'), findsNothing);
  });
}
