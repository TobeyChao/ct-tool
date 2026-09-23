/// 原生工作台统一设计令牌（数值与排版部分；颜色令牌集中在 lib/theme.dart）。
///
/// 依据 openspec/changes/native-flutter-workbench design.md 决策 2：
/// 统一颜色、字号、间距、圆角、边框、行高与焦点令牌，精简 Material 默认外观。
library;

import 'package:flutter/material.dart';

import '../theme.dart';

// ---- 间距（4px 基准网格） ----
const double ctGapXs = 4;
const double ctGapSm = 8;
const double ctGapMd = 12;
const double ctGapLg = 16;
const double ctGapXl = 24;
const double ctGapXxl = 32;

// ---- 动效 ----
// 桌面工作台只使用短促、克制的状态过渡；拖拽过程中由调用方显式关闭动画。
const Duration ctMotionFast = Duration(milliseconds: 120);
const Duration ctMotionStandard = Duration(milliseconds: 200);
const Curve ctMotionCurve = Curves.easeOut;

// ---- 圆角 ----
const double ctRadiusSm = 6;
const double ctRadiusMd = 10;
const double ctRadiusLg = 12;

/// 常用圆角（避免散落 magic number）
final BorderRadius ctRadiusSmAll = BorderRadius.circular(ctRadiusSm);
final BorderRadius ctRadiusMdAll = BorderRadius.circular(ctRadiusMd);
final BorderRadius ctRadiusLgAll = BorderRadius.circular(ctRadiusLg);

// ---- 字号 ----
const double ctFontXs = 12;
const double ctFontSm = 13;
const double ctFontMd = 14;
const double ctFontLg = 16;
const double ctFontXl = 18;
const double ctFontXxl = 28;

// ---- 行高与控件高度 ----
const double ctRowSm = 28; // 表格行 / 资源树行
const double ctRowMd = 40; // 导航项、面板头
const double ctRowLg = 44; // 表单行
const double ctToolbarHeight = 44;

/// 顶栏高度（web 的 --ct-topbar-h = 52px）
const double ctTopbarHeight = 52;

/// 无边框窗口的自绘标题栏高度；按钮仍沿用 window_manager 的 32px 命中度量。
const double ctTitleBarHeight = 38;

// ---- 边框与焦点 ----
const double ctBorderWidth = 1;
const double ctFocusBorderWidth = 1.5;

// ---- 工作台布局（宽度取自 web 的 tokens.css） ----
const double ctNavRailWidth = 56;

/// 文字侧栏宽度（web 的 --ct-sidebar-w = 236px）
const double ctSidebarWidth = 248;
const double ctSidebarMinWidth = 212;
const double ctSidebarMaxWidth = 300;

const double ctResourcePanelDefault = 240;
const double ctResourcePanelMin = 180;
const double ctResourcePanelMax = 380;
const double ctInspectorDefault = 300;
const double ctInspectorMin = 240;
const double ctInspectorMax = 440;
const double ctCollapsedStripWidth = 44;

/// 非编辑器页面的阅读宽度；避免大窗口里表单和日志横向摊得过开。
const double ctPageMaxWidth = 1080;

/// 窗口约束（design.md 决策 6：默认 1280x800，最小 1024x700）
const double ctWindowDefaultWidth = 1280;
const double ctWindowDefaultHeight = 800;
const double ctWindowMinWidth = 1024;
const double ctWindowMinHeight = 700;

/// 金色系上的可读前景（ctGold 在浅底上对比不足时使用）
const Color ctGoldText = Color(0xFF8A6D1A);

/// 统一文本样式构造（默认 13px 正文色）
TextStyle ctText({
  double size = ctFontMd,
  Color color = ctInk,
  FontWeight weight = FontWeight.w400,
  double? height = 1.35,
}) {
  return TextStyle(
    fontSize: size,
    color: color,
    fontWeight: weight,
    height: height,
  );
}
