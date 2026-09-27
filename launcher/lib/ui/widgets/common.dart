import 'dart:io';

import 'package:flutter/material.dart';

import '../../theme.dart';
import '../tokens.dart';

/// 页面共享的排版常量
const TextStyle ctMono = TextStyle(
  fontFamily: ctMonoFamily,
  fontFamilyFallback: ctMonoFallback,
  fontFeatures: [FontFeature.tabularFigures()],
);

const TextStyle ctPageTitleStyle = TextStyle(
  fontSize: 17,
  fontWeight: FontWeight.w600,
  height: 1.2,
  letterSpacing: -0.2,
);

/// 页面标题下的一行说明，保持次要信息安静、可扫读。
const TextStyle ctPageSubtitleStyle = TextStyle(
  fontSize: ctFontSm,
  color: ctInk3,
  height: 1.4,
);

/// 非 Schema 页面统一的内容容器。
///
/// 大窗口限制阅读宽度，小窗口保持自然收缩；页面滚动由这里统一承载。
class CtPageContent extends StatelessWidget {
  const CtPageContent({
    super.key,
    required this.child,
    this.maxWidth = ctPageMaxWidth,
    this.padding = const EdgeInsets.all(ctGapXl),
  });

  final Widget child;
  final double maxWidth;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: padding,
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: SizedBox(width: double.infinity, child: child),
        ),
      ),
    );
  }
}

/// 页面内标题。标题属于内容，不额外占一条全局标题栏。
class CtPageHeader extends StatelessWidget {
  const CtPageHeader({
    super.key,
    required this.title,
    required this.subtitle,
    this.trailing,
  });

  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: ctPageTitleStyle),
              const SizedBox(height: ctGapXs),
              Text(subtitle, style: ctPageSubtitleStyle),
            ],
          ),
        ),
        if (trailing != null) ...[const SizedBox(width: ctGapLg), trailing!],
      ],
    );
  }
}

/// 统一的低对比内容卡片。
class CtSurfaceCard extends StatelessWidget {
  const CtSurfaceCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(ctGapMd),
    this.color = ctSurface,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: child,
    );
  }
}

/// 分组卡片：设置页与属性区共用的圆角矩形分组。
///
/// 白底 + `ctBorder` 描边 + 12px 圆角，条目之间自动补一条顶线；标题与说明作为卡片抬头。
/// 条目自己只管内容，内边距与分隔线统一由这里给，避免各页各写一套。
class CtGroupCard extends StatelessWidget {
  const CtGroupCard({
    super.key,
    this.title,
    this.description,
    required this.children,
  });

  final String? title;
  final String? description;
  final List<Widget> children;

  static const EdgeInsets _itemPadding = EdgeInsets.fromLTRB(
    ctGapLg,
    14,
    ctGapLg,
    14,
  );

  @override
  Widget build(BuildContext context) {
    return Container(
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: ctSurface,
        border: Border.all(color: ctBorder),
        borderRadius: ctRadiusLgAll,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (title != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(ctGapLg, 14, ctGapLg, 0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title!,
                    style: ctText(
                      size: ctFontSm,
                      color: ctInk,
                      weight: FontWeight.w600,
                    ),
                  ),
                  if (description != null) ...[
                    const SizedBox(height: ctGapXs),
                    Text(
                      description!,
                      style: ctText(size: ctFontXs, color: ctInk3, height: 1.4),
                    ),
                  ],
                ],
              ),
            ),
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const Divider(height: 1, thickness: 1, color: ctBorder),
            Padding(padding: _itemPadding, child: children[i]),
          ],
        ],
      ),
    );
  }
}

/// 复选框：描述**对象属性**的布尔标记——字段是否本地化、是否仅服务端、表有没有 codename 索引、
/// Excel 是否拆成多列。这类「是 / 否」是实体上的一个属性值，与同类属性并列，所以用勾选。
///
/// 语义分工：**开关某个行为的设置项用 [CtSwitch]**，实体的属性标记用本控件；
/// 全项目只留这两种布尔外观，不要再各自用 Switch/Checkbox 拼。
class CtCheckbox extends StatelessWidget {
  const CtCheckbox({
    super.key,
    required this.value,
    required this.onChanged,
    this.tooltip,
  });

  final bool value;
  final ValueChanged<bool>? onChanged;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final box = SizedBox(
      width: 32,
      height: 32,
      child: Checkbox(
        value: value,
        onChanged: onChanged == null ? null : (on) => onChanged!(on ?? false),
        visualDensity: VisualDensity.compact,
        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
        activeColor: ctAccent,
        checkColor: Colors.white,
        side: const BorderSide(color: ctBorderStrong),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(ctRadiusSm),
        ),
      ),
    );
    if (tooltip == null) return box;
    return Tooltip(message: tooltip!, child: box);
  }
}

/// 开关：开关**某个行为**的设置项——开机自启、托盘常驻这类「打开 / 关闭」一件事情的条目。
///
/// 语义分工：设置项用本控件，实体的属性标记用 [CtCheckbox]。
/// 配色沿用主题的 `colorScheme.primary`，不在这里另写一套颜色。
class CtSwitch extends StatelessWidget {
  const CtSwitch({
    super.key,
    required this.value,
    required this.onChanged,
    this.tooltip,
  });

  final bool value;
  final ValueChanged<bool>? onChanged;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final control = Switch(
      value: value,
      onChanged: onChanged,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
    if (tooltip == null) return control;
    return Tooltip(message: tooltip!, child: control);
  }
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
  const CtBrandMark({super.key, this.size = 22});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: ctPrimary,
        borderRadius: BorderRadius.circular(size * 5 / 22),
      ),
      alignment: Alignment.center,
      child: Text(
        'ct',
        style: TextStyle(
          fontFamily: ctMonoFamily,
          fontFamilyFallback: ctMonoFallback,
          color: Colors.white,
          fontSize: size / 2,
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
                    fontWeight: FontWeight.w500,
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
    // 固定色会盖过 Material 的禁用态：按钮不可点时仍像绿色主操作。
    const disabledInk = Color(0xFF8A958D);
    final style = ButtonStyle(
      visualDensity: VisualDensity.compact,
      minimumSize: const WidgetStatePropertyAll(Size(0, 40)),
      padding: const WidgetStatePropertyAll(
        EdgeInsets.symmetric(horizontal: 16, vertical: 9),
      ),
      shape: WidgetStatePropertyAll(
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      textStyle: const WidgetStatePropertyAll(
        TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      ),
      side: WidgetStateProperty.resolveWith((states) {
        final disabled = states.contains(WidgetState.disabled);
        return BorderSide(
          color: disabled
              ? ctBorder
              : (_kind == _CtButtonKind.accent ? ctAccent : ctBorderStrong),
        );
      }),
      backgroundColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) {
          return _kind == _CtButtonKind.accent ? ctBorder : Colors.transparent;
        }
        return _kind == _CtButtonKind.accent ? ctAccent : Colors.transparent;
      }),
      foregroundColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) return disabledInk;
        return _kind == _CtButtonKind.accent ? Colors.white : ctInk2;
      }),
      overlayColor: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.disabled)) return Colors.transparent;
        return _kind == _CtButtonKind.accent ? ctAccentHover : ctSurface2;
      }),
    );
    return TextButton(style: style, onPressed: onPressed, child: Text(label));
  }
}

/// 固定高度的选择胶囊：选中态只改变底色、边框和字重，不增加对勾图标。
///
/// 适合会换行的筛选器；等宽标签可传 [minWidth]，避免选中时按钮自身改尺寸。
class CtChoicePill extends StatelessWidget {
  const CtChoicePill({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
    this.minWidth = 0,
    this.tooltip,
    this.dense = false,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final double minWidth;
  final String? tooltip;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    final pill = Material(
      color: selected ? ctAccentSofter : ctSurface,
      shape: StadiumBorder(
        side: BorderSide(
          color: !enabled
              ? ctBorder
              : selected
              ? ctAccent
              : ctBorderStrong,
        ),
      ),
      child: InkWell(
        onTap: onTap,
        customBorder: const StadiumBorder(),
        child: Container(
          constraints: BoxConstraints(
            minHeight: dense ? 28 : 32,
            minWidth: minWidth,
          ),
          padding: EdgeInsets.symmetric(horizontal: dense ? ctGapSm : ctGapMd),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: ctText(
                  size: ctFontXs,
                  color: !enabled
                      ? ctInk3
                      : selected
                      ? ctPrimary
                      : ctInk2,
                  weight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (tooltip == null) return pill;
    return Tooltip(message: tooltip!, child: pill);
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
            child: Text(
              label,
              style: const TextStyle(fontSize: 13, color: ctInk2),
            ),
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
        borderRadius: ctRadiusMdAll,
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
