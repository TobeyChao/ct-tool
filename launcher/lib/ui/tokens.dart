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

// ---- 圆角 ----
const double ctRadiusSm = 6;
const double ctRadiusMd = 8;
const double ctRadiusLg = 12;

/// 常用圆角（避免散落 magic number）
final BorderRadius ctRadiusSmAll = BorderRadius.circular(ctRadiusSm);
final BorderRadius ctRadiusMdAll = BorderRadius.circular(ctRadiusMd);
final BorderRadius ctRadiusLgAll = BorderRadius.circular(ctRadiusLg);

// ---- 字号 ----
const double ctFontXs = 11;
const double ctFontSm = 12;
const double ctFontMd = 13;
const double ctFontLg = 14;
const double ctFontXl = 18;
const double ctFontXxl = 26;

// ---- 行高与控件高度 ----
const double ctRowSm = 28; // 表格行 / 资源树行
const double ctRowMd = 36; // 导航项、任务行、面板头
const double ctRowLg = 44; // 表单行
const double ctToolbarHeight = 44;

// ---- 边框与焦点 ----
const double ctBorderWidth = 1;
const double ctFocusBorderWidth = 1.5;

// ---- 工作台布局 ----
const double ctNavRailWidth = 56;
const double ctResourcePanelDefault = 240;
const double ctResourcePanelMin = 180;
const double ctResourcePanelMax = 380;
const double ctInspectorDefault = 300;
const double ctInspectorMin = 240;
const double ctInspectorMax = 440;
const double ctTaskPanelDefault = 190;
const double ctTaskPanelMin = 140;
const double ctTaskPanelMax = 320;
const double ctCollapsedStripWidth = 32;

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
  double? height,
}) {
  return TextStyle(
    fontSize: size,
    color: color,
    fontWeight: weight,
    height: height,
  );
}
