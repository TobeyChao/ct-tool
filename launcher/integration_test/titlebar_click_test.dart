import 'package:ct_launcher/services/window_options.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/mock/mock_data.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:macos_window_utils/macos_window_utils.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:window_manager/window_manager.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('native sidebar mouse clicks toggle Flutter without zooming', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    await windowManager.ensureInitialized();
    await windowManager.waitUntilReadyToShow(desktopWindowOptions(), () async {
      await WindowManipulator.initialize();
      await WindowManipulator.addToolbar();
      await WindowManipulator.setToolbarStyle(
        toolbarStyle: NSWindowToolbarStyle.unifiedCompact,
      );
      await windowManager.show();
      await windowManager.focus();
    });
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: mockWorkspaceFor(MockScenario.normal),
          workspaceKey: 'native-titlebar-click-test',
          showDesktopTitleBar: true,
          titleBarLeadingInset: 80,
          showWindowControls: false,
        ),
      ),
    );
    await tester.pumpAndSettle();
    const channel = MethodChannel('ct/titlebar_controls');
    final initialBounds = await windowManager.getBounds();
    final initialZoom = await windowManager.isMaximized();
    // Native NSEvents enter as device events, which the test binding normally
    // drops; opt in while exercising the actual desktop input path.
    tester.binding.shouldPropagateDevicePointerEvents = true;
    for (final interval in [40, 240]) {
      for (var i = 0; i < 2; i++) {
        final toggle = find.byKey(
          ValueKey(i == 0 ? 'wb.collapse.sidebar' : 'wb.expand.sidebar'),
        );
        expect(toggle, findsOneWidget);
        final point = tester.getCenter(toggle);
        await channel.invokeMethod<void>('testMouseClick', {
          'x': point.dx,
          'y': point.dy,
          'count': i + 1,
        });
        await tester.pumpAndSettle();
        expect(
          find.byKey(
            ValueKey(i == 0 ? 'wb.expand.sidebar' : 'wb.collapse.sidebar'),
          ),
          findsOneWidget,
        );
        expect(await windowManager.getBounds(), initialBounds);
        expect(await windowManager.isMaximized(), initialZoom);
        await tester.pump(Duration(milliseconds: interval));
      }
    }
    tester.binding.shouldPropagateDevicePointerEvents = false;
  });
}
