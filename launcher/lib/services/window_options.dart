import 'dart:io';
import 'dart:ui' show Size;

import 'package:window_manager/window_manager.dart';

import '../theme.dart';
import '../ui/tokens.dart';

/// 原生工作台的窗口参数（任务 2.5）——唯一来源，便于直接断言。
///
/// 默认 1280×800、最小 1024×700、**可调**；不读取也不继承任何旧面板时代的
/// 固定尺寸偏好（`window_width/height/x/y/resizable/maximized` 会在
/// `SettingsStore.load()` 里作为废弃键清除）。
WindowOptions desktopWindowOptions({String title = 'ct 工作台'}) {
  final hideNativeTitleBar = Platform.isWindows || Platform.isMacOS;
  return WindowOptions(
    size: const Size(ctWindowDefaultWidth, ctWindowDefaultHeight),
    minimumSize: const Size(ctWindowMinWidth, ctWindowMinHeight),
    center: true,
    title: title,
    backgroundColor: ctSurface2,
    // Windows/macOS 去掉系统标题栏，由 WorkbenchScreen 绘制应用内标题栏。
    // macOS 继续保留原生交通灯；Windows 使用自绘最小化/最大化/关闭按钮。
    titleBarStyle: hideNativeTitleBar
        ? TitleBarStyle.hidden
        : TitleBarStyle.normal,
    windowButtonVisibility: Platform.isMacOS,
  );
}

/// 主窗口必须可拖拽改变尺寸：这是工作台三档窗口矩阵的前提。
bool get desktopWindowIsResizable => true;

/// 启动时应用的尺寸约束（供测试与真机验收对照）。
Size get desktopWindowSize =>
    const Size(ctWindowDefaultWidth, ctWindowDefaultHeight);

Size get desktopWindowMinimumSize =>
    const Size(ctWindowMinWidth, ctWindowMinHeight);
