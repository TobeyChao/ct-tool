import 'package:flutter/material.dart';

// 深林绿设计令牌：**逐值对齐 web 面板的 `web/static/styles/tokens.css`**。
// 该 CSS 文件是这套界面唯一的颜色真相源；改这里之前先改它，别在两侧各写一套。
const Color ctBg = Color(0xFFF6F7F5);
const Color ctSurface = Color(0xFFFFFFFF);
const Color ctSurface2 = Color(0xFFF2F4F1);
const Color ctBorder = Color(0xFFE4E8E0);
const Color ctBorderStrong = Color(0xFFCBD2C5);
const Color ctInk = Color(0xFF1B241F);
const Color ctInk2 = Color(0xFF5A645E);
const Color ctInk3 = Color(0xFF626C66);
const Color ctPrimary = Color(0xFF1E4635);
const Color ctPrimaryHover = Color(0xFF17382A);
const Color ctAccent = Color(0xFF2F7A56);
const Color ctAccentHover = Color(0xFF276949);
const Color ctAccentSoft = Color(0xFFDCEFE3);
const Color ctAccentSofter = Color(0xFFEDF7F0);
const Color ctGold = Color(0xFFC9A227);
const Color ctGoldSoft = Color(0xFFF7EDCB);
const Color ctDanger = Color(0xFFA83B3B);
const Color ctDangerSoft = Color(0xFFF7E7E7);
const Color ctWarn = Color(0xFFA8731F);
const Color ctWarnSoft = Color(0xFFF5ECDA);
const Color ctLogBg = Color(0xFF121A16);
const Color ctLogBorder = Color(0xFF26332C);
const Color ctLogText = Color(0xFFB9C9C0);

// 导航底色（tokens.css 的 --ct-nav / --ct-nav-rail）
const Color ctNav = Color(0xFF102219);
const Color ctNavRail = Color(0xFF19271F);

// ---- 字体 ----
// Noto Sans SC 同时覆盖中英文，避免 Windows/macOS 使用不同中文字体导致基线漂移。
// 字体与 SIL OFL 许可随应用内置，macOS 不依赖用户额外安装。
const String ctSansFamily = 'NotoSansSC';
const String ctMonoFamily = 'CascadiaMono';
const List<String> ctSansFallback = [
  'Microsoft YaHei UI',
  'Microsoft YaHei',
  'PingFang SC',
  'Segoe UI',
];
const List<String> ctMonoFallback = [
  'Cascadia Mono',
  'Consolas',
  'SF Mono',
  'Menlo',
  ctSansFamily,
];

ThemeData buildCtTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: ctPrimary,
    primary: ctPrimary,
    secondary: ctAccent,
    surface: ctSurface,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: const Color(0xFFE8EBE5),
    fontFamily: ctSansFamily,
    fontFamilyFallback: ctSansFallback,
  );
}
