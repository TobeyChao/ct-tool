import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import '../theme.dart';
import '../ui/dev/component_gallery.dart';
import '../ui/tokens.dart';
import '../ui/workbench/mock/mock_data.dart';
import '../ui/workbench/workbench_screen.dart';

/// 界面样板开发入口（非生产入口）：
///
/// ```sh
/// flutter run -d windows -t lib/dev/main_dev.dart
/// ```
///
/// 提供场景 / 缩放 / 窗口尺寸切换，用于 native-flutter-workbench
/// 1.3 样板运行与 1.4 截图矩阵采集。窗口默认值与最小值与正式工作台一致。
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  const options = WindowOptions(
    size: Size(ctWindowDefaultWidth, ctWindowDefaultHeight),
    minimumSize: Size(ctWindowMinWidth, ctWindowMinHeight),
    center: true,
    title: 'ct 工作台 · 界面样板（MOCK）',
  );
  await windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.setResizable(true);
    await windowManager.show();
    await windowManager.focus();
  });
  runApp(const DevApp());
}

class DevApp extends StatefulWidget {
  const DevApp({super.key});

  @override
  State<DevApp> createState() => _DevAppState();
}

class _DevAppState extends State<DevApp> {
  static const _scales = <double>[1.0, 1.25, 1.5];
  static const _sizes = <(double, double)>[
    (1024, 700),
    (1280, 800),
    (1440, 900),
  ];

  bool _gallery = false;
  MockScenario _scenario = MockScenario.normal;
  double _scale = 1.0;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ct 工作台 · 界面样板',
      theme: buildCtTheme(),
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        backgroundColor: ctBg,
        body: Column(
          children: [
            _buildDevBar(),
            Expanded(
              // 用 textScaler 近似系统缩放（比真机整体等比缩放更严格：
              // 只放大文字不放大盘面，更容易暴露截断）。真机缩放复核在任务 5.5。
              child: MediaQuery(
                data: MediaQuery.of(
                  context,
                ).copyWith(textScaler: TextScaler.linear(_scale)),
                child: _gallery
                    ? const ComponentGallery()
                    : WorkbenchScreen(
                        key: ValueKey(_scenario),
                        data: mockWorkspaceFor(_scenario),
                        bannerLabel:
                            '界面样板 · 模拟数据（MOCK），未连接内核 · 场景：${_scenario.label} · 缩放 ${(_scale * 100).round()}%',
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDevBar() {
    return Container(
      height: 40,
      padding: const EdgeInsets.symmetric(horizontal: ctGapSm),
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(bottom: BorderSide(color: ctBorderStrong)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: ctGoldSoft,
              borderRadius: ctRadiusSmAll,
            ),
            child: const Text(
              'DEV',
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: ctGoldText,
              ),
            ),
          ),
          const SizedBox(width: ctGapSm),
          _devTab('工作台', !_gallery, () => setState(() => _gallery = false)),
          _devTab('控件样板', _gallery, () => setState(() => _gallery = true)),
          const _DevDivider(),
          const Text('场景', style: TextStyle(fontSize: 11, color: ctInk3)),
          const SizedBox(width: ctGapXs),
          DropdownButtonHideUnderline(
            child: PopupMenuButton<MockScenario>(
              tooltip: '选择场景',
              initialValue: _scenario,
              position: PopupMenuPosition.under,
              popUpAnimationStyle: ctMenuAnimationStyle,
              onSelected: (v) => setState(() => _scenario = v),
              itemBuilder: (context) => [
                for (final s in MockScenario.values)
                  PopupMenuItem(value: s, child: Text(s.label)),
              ],
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(_scenario.label, style: ctText(size: ctFontSm)),
                  const Icon(Icons.arrow_drop_down, size: 18, color: ctInk2),
                ],
              ),
            ),
          ),
          const _DevDivider(),
          const Text('缩放', style: TextStyle(fontSize: 11, color: ctInk3)),
          const SizedBox(width: ctGapXs),
          for (final s in _scales)
            _devTab(
              '${(s * 100).round()}%',
              _scale == s,
              () => setState(() => _scale = s),
            ),
          const _DevDivider(),
          const Text('窗口', style: TextStyle(fontSize: 11, color: ctInk3)),
          const SizedBox(width: ctGapXs),
          for (final (w, h) in _sizes)
            _devTab('${w.round()}×${h.round()}', false, () async {
              await windowManager.setSize(Size(w, h));
            }),
        ],
      ),
    );
  }

  Widget _devTab(String label, bool selected, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: InkWell(
        onTap: onTap,
        borderRadius: ctRadiusSmAll,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(
            color: selected ? ctAccentSofter : Colors.transparent,
            borderRadius: ctRadiusSmAll,
          ),
          child: Text(
            label,
            style: ctText(
              size: ctFontSm,
              color: selected ? ctPrimary : ctInk2,
              weight: FontWeight.w500,
            ),
          ),
        ),
      ),
    );
  }
}

class _DevDivider extends StatelessWidget {
  const _DevDivider();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 1,
      height: 18,
      margin: const EdgeInsets.symmetric(horizontal: ctGapSm),
      color: ctBorderStrong,
    );
  }
}
