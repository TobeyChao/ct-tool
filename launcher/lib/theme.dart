import 'package:flutter/material.dart';

// 与 Web 面板一致的深林绿设计令牌（见 tool/docs/design/launcher-mockup-v2.html）
const Color ctBg = Color(0xFFF5F6F4);
const Color ctSurface = Color(0xFFFFFFFF);
const Color ctSurface2 = Color(0xFFF0F2EE);
const Color ctBorder = Color(0xFFE1E6DD);
const Color ctBorderStrong = Color(0xFFCBD2C6);
const Color ctInk = Color(0xFF1B241F);
const Color ctInk2 = Color(0xFF5A645E);
const Color ctInk3 = Color(0xFF8B948E);
const Color ctPrimary = Color(0xFF1B4332);
const Color ctPrimaryHover = Color(0xFF153728);
const Color ctAccent = Color(0xFF2F7A56);
const Color ctAccentHover = Color(0xFF266544);
const Color ctAccentSoft = Color(0xFFD8F3DC);
const Color ctAccentSofter = Color(0xFFECF7ED);
const Color ctGold = Color(0xFFC9A227);
const Color ctGoldSoft = Color(0xFFF7EECB);
const Color ctDanger = Color(0xFFB23B3B);
const Color ctDangerSoft = Color(0xFFF9E8E8);
const Color ctWarn = Color(0xFFB7791F);
const Color ctWarnSoft = Color(0xFFF9EFD9);
const Color ctLogBg = Color(0xFF121A16);
const Color ctLogBorder = Color(0xFF26332C);
const Color ctLogText = Color(0xFFB9C9C0);

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
    fontFamilyFallback: const ['PingFang SC', 'Microsoft YaHei', 'Segoe UI'],
  );
}
