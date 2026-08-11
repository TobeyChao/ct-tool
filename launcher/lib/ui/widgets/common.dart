import 'dart:io';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/panel_service.dart';
import '../../theme.dart';

/// 页面共享的排版常量
const TextStyle ctMono = TextStyle(
  fontFamily: 'Menlo',
  fontFamilyFallback: ['Consolas', 'Cascadia Mono', 'SF Mono'],
);

const TextStyle ctPageTitleStyle =
    TextStyle(fontSize: 14, fontWeight: FontWeight.w600);

/// 面板状态的展示信息（唯一 switch 来源，侧栏与概览页共用）
({Color dot, String title, String sub, String hint}) panelStatusPresentation(
  PanelStatus status,
  String? failureReason,
) {
  return switch (status) {
    PanelStatus.stopped => (
        dot: ctInk3,
        title: '已停止',
        sub: '点击开关启动面板，启动后自动打开',
        hint: '未运行',
      ),
    PanelStatus.starting => (
        dot: ctGold,
        title: '正在启动',
        sub: '正在拉起本地服务，稍候…',
        hint: '连接中',
      ),
    PanelStatus.running => (
        dot: ctAccent,
        title: '运行中',
        sub: '面板服务运行中 · 点击开关可暂停',
        hint: '点击地址可复制',
      ),
    PanelStatus.failed => (
        dot: ctDanger,
        title: '启动失败',
        sub: failureReason ?? '请检查下方日志后重试',
        hint: '服务未启动',
      ),
  };
}

/// 全局轻提示（深绿浮层，替代页面内重复的 SnackBar 拼装）
void showCtToast(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..clearSnackBars()
    ..showSnackBar(
      SnackBar(
        content: Text(message, style: const TextStyle(color: Colors.white)),
        backgroundColor: ctPrimary,
        behavior: SnackBarBehavior.floating,
        duration: const Duration(milliseconds: 1600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
}

/// 用系统默认浏览器打开面板地址（概览页与托盘共用）
Future<void> openPanelInBrowser(String url) async {
  final uri = Uri.parse(url);
  if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
    // 失败提示交给调用方，这里只返回失败信号
    throw StateError('无法打开 $url');
  }
}

/// 用系统文件管理器打开目录（macOS / Windows）
Future<void> openInFileManager(String path) async {
  if (Platform.isMacOS) {
    await Process.run('open', [path]);
  } else if (Platform.isWindows) {
    await Process.run('explorer', [path]);
  }
}

/// 输入框统一样式
InputDecoration ctInputDecoration() {
  return InputDecoration(
    isDense: true,
    contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
    filled: true,
    fillColor: ctSurface,
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: ctBorderStrong),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: ctAccent, width: 1.5),
    ),
  );
}

/// 品牌标志（深绿方块 + ct 字标）
class CtBrandMark extends StatelessWidget {
  const CtBrandMark({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        color: ctPrimary,
        borderRadius: BorderRadius.circular(5),
      ),
      alignment: Alignment.center,
      child: const Text(
        'ct',
        style: TextStyle(
          fontFamily: 'Menlo',
          color: Colors.white,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// 左侧导航项
class CtNavItem extends StatelessWidget {
  const CtNavItem({
    super.key,
    required this.icon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      child: Material(
        color: selected ? ctAccentSofter : Colors.transparent,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(8),
          child: Container(
            height: 36,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: [
                Icon(icon, size: 16, color: selected ? ctPrimary : ctInk3),
                const SizedBox(width: 10),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                    color: selected ? ctPrimary : ctInk2,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 页面底部提示条：细分割线 + 提示内容，统一三页底部设计语言
class CtFooterHint extends StatelessWidget {
  const CtFooterHint({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(height: 1, thickness: 1, color: ctBorder),
        const SizedBox(height: 10),
        child,
      ],
    );
  }
}

/// 通用按钮：accent 主按钮 / ghost 次级按钮
enum _CtButtonKind { accent, ghost }

class CtButton extends StatelessWidget {
  const CtButton.accent(this.label, {super.key, required this.onPressed})
      : _kind = _CtButtonKind.accent;
  const CtButton.ghost(this.label, {super.key, required this.onPressed})
      : _kind = _CtButtonKind.ghost;

  final String label;
  final VoidCallback? onPressed;
  final _CtButtonKind _kind;

  @override
  Widget build(BuildContext context) {
    final style = ButtonStyle(
      visualDensity: VisualDensity.compact,
      padding: const WidgetStatePropertyAll(
        EdgeInsets.symmetric(horizontal: 16, vertical: 9),
      ),
      shape: WidgetStatePropertyAll(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      textStyle: const WidgetStatePropertyAll(
        TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      ),
      side: _kind == _CtButtonKind.accent
          ? const WidgetStatePropertyAll(BorderSide(color: ctAccent))
          : const WidgetStatePropertyAll(BorderSide(color: ctBorderStrong)),
      backgroundColor: switch (_kind) {
        _CtButtonKind.accent => const WidgetStatePropertyAll(ctAccent),
        _CtButtonKind.ghost => const WidgetStatePropertyAll(Colors.transparent),
      },
      foregroundColor: switch (_kind) {
        _CtButtonKind.accent => const WidgetStatePropertyAll(Colors.white),
        _CtButtonKind.ghost => const WidgetStatePropertyAll(ctInk2),
      },
      overlayColor: switch (_kind) {
        _CtButtonKind.accent => const WidgetStatePropertyAll(ctAccentHover),
        _CtButtonKind.ghost => const WidgetStatePropertyAll(ctSurface2),
      },
    );
    return TextButton(style: style, onPressed: onPressed, child: Text(label));
  }
}

/// 设置页行：标签 + 控件
class CtSettingRow extends StatelessWidget {
  const CtSettingRow({super.key, required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: ctBorder)),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 92,
            child: Text(label, style: const TextStyle(fontSize: 13, color: ctInk2)),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}

/// 概览页统计卡：图标 + 标签 + 大数字 + 副行
class CtStatCard extends StatelessWidget {
  const CtStatCard({
    super.key,
    required this.number,
    required this.label,
    required this.sub,
    required this.icon,
  });

  final String number;
  final String label;
  final String sub;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: ctBorder),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 15, color: ctInk3),
              const SizedBox(width: 8),
              Text(label, style: const TextStyle(fontSize: 12, color: ctInk2)),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            number,
            style: const TextStyle(
              fontSize: 26,
              height: 1.1,
              fontWeight: FontWeight.w700,
              color: ctPrimary,
              fontFeatures: [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(height: 6),
          Text(
            sub,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 11, color: ctInk3),
          ),
        ],
      ),
    );
  }
}
