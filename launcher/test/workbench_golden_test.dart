import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/dev/component_gallery.dart';
import 'package:ct_launcher/ui/workbench/mock/mock_data.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 1.4 截图矩阵：1440x900 / 1280x800 / 1024x700 × 100%/125%/150% 缩放。
///
/// 说明：flutter_tester 无 CJK 字体，截图中中文为占位方块；
/// 矩阵用于验证布局、对齐与溢出，字体渲染一致性以真机运行为准（见 5.1/5.5）。
/// 更新方式：`flutter test test/workbench_golden_test.dart --update-goldens`。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  SharedPreferences.setMockInitialValues({});

  const sizes = <String, Size>{
    '1440x900': Size(1440, 900),
    '1280x800': Size(1280, 800),
    '1024x700': Size(1024, 700),
  };
  const scales = <String, double>{'s100': 1.0, 's125': 1.25, 's150': 1.5};

  Future<void> pumpAt(
    WidgetTester tester,
    MockScenario scenario,
    Size size,
    double scale,
  ) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MediaQuery(
        data: MediaQueryData(textScaler: TextScaler.linear(scale)),
        child: MaterialApp(
          theme: buildCtTheme(),
          home: WorkbenchScreen(
            data: mockWorkspaceFor(scenario),
            workspaceKey: 'golden-${scenario.name}',
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  // 正常场景 × 尺寸/缩放矩阵
  for (final sizeEntry in sizes.entries) {
    for (final scaleEntry in scales.entries) {
      final sizeName = sizeEntry.key;
      final size = sizeEntry.value;
      final scaleName = scaleEntry.key;
      final scale = scaleEntry.value;
      testWidgets('workbench normal $sizeName $scaleName', (tester) async {
        await pumpAt(tester, MockScenario.normal, size, scale);
        await expectLater(
          find.byType(WorkbenchScreen),
          matchesGoldenFile('goldens/workbench_${sizeName}_$scaleName.png'),
        );
      });
    }
  }

  // 状态场景 × 默认尺寸
  for (final scenario in MockScenario.values) {
    testWidgets('workbench scenario ${scenario.name}', (tester) async {
      await pumpAt(tester, scenario, const Size(1280, 800), 1.0);
      await expectLater(
        find.byType(WorkbenchScreen),
        matchesGoldenFile('goldens/workbench_scenario_${scenario.name}.png'),
      );
    });
  }

  // 1024x700 下手动展开全部辅助区（长文本场景，验证截断而非遮挡）
  testWidgets('workbench 1024x700 panels expanded longText', (tester) async {
    await pumpAt(tester, MockScenario.longText, const Size(1024, 700), 1.0);
    // 断点按整窗宽度：1024 下资源区保持展开、属性区折叠。把确实折叠掉的区逐个点开，
    // 目标是「全部展开时长文本只截断不遮挡」。
    for (final zone in const ['resource', 'inspector']) {
      final strip = find.byKey(ValueKey('wb.strip.$zone'));
      if (strip.evaluate().isNotEmpty) {
        await tester.tap(
          find.descendant(of: strip, matching: find.byType(IconButton)),
        );
        await tester.pump();
      }
    }
    expect(find.byKey(const ValueKey('wb.resourcePanel')), findsOneWidget);
    expect(find.byKey(const ValueKey('wb.inspectorPanel')), findsOneWidget);
    await expectLater(
      find.byType(WorkbenchScreen),
      matchesGoldenFile('goldens/workbench_1024x700_expanded_longtext.png'),
    );
  });

  // 控件样板页（1.2）
  testWidgets('component gallery', (tester) async {
    tester.view.physicalSize = const Size(1280, 1500);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: const Scaffold(body: ComponentGallery()),
      ),
    );
    await tester.pump();
    await expectLater(
      find.byType(ComponentGallery),
      matchesGoldenFile('goldens/component_gallery.png'),
    );
  });
}
