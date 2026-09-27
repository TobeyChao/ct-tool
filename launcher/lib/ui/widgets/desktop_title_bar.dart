import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import '../../theme.dart';
import '../tokens.dart';
import 'common.dart';
import 'status_badge.dart';
import 'titlebar_control_area.dart';

/// 一条应用菜单动作。标题栏只负责展示与回调，不把具体业务命令耦合进控件。
@immutable
class CtTitleBarAction {
  const CtTitleBarAction({
    required this.label,
    required this.onSelected,
    this.shortcut,
    this.enabled = true,
    this.selected = false,
  });

  final String label;
  final VoidCallback onSelected;
  final String? shortcut;
  final bool enabled;
  final bool selected;
}

/// 标题栏菜单。动作索引在打开菜单时固定，避免回调期间列表变化导致误触发。
@immutable
class CtTitleBarMenu {
  const CtTitleBarMenu({required this.label, required this.actions});

  final String label;
  final List<CtTitleBarAction> actions;
}

/// 无边框窗口使用的应用内标题栏。
///
/// 窗口拖动/双击最大化由 `window_manager` 的 [DragToMoveArea] 负责；窗口按钮
/// 复用同一插件的 Windows 11 度量，避免自行画一套容易产生命中区差异的图标。
class CtDesktopTitleBar extends StatelessWidget {
  const CtDesktopTitleBar({
    super.key,
    required this.title,
    this.subtitle,
    this.menus = const [],
    this.statusLabel,
    this.statusTone = CtBadgeTone.neutral,
    this.onQuickOpen,
    this.sidebarWidth,
    this.sidebarToggle,
    this.isMaximized = false,
    this.showWindowControls = true,
    this.leadingInset = 0,
    this.onMinimize,
    this.onToggleMaximize,
    this.onClose,
  });

  final String title;
  final String? subtitle;
  final List<CtTitleBarMenu> menus;
  final String? statusLabel;
  final CtBadgeTone statusTone;
  final VoidCallback? onQuickOpen;

  /// 侧栏切换按钮与工作区标题；macOS 中标题允许跨过侧栏边界。
  final double? sidebarWidth;
  final Widget? sidebarToggle;
  final bool isMaximized;
  final bool showWindowControls;

  /// macOS 隐藏原生标题栏后为交通灯预留的左侧空间。
  final double leadingInset;
  final VoidCallback? onMinimize;
  final VoidCallback? onToggleMaximize;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    final macSidebarLayout =
        sidebarToggle != null &&
        sidebarWidth != null &&
        leadingInset >= ctNavRailWidth;
    return Container(
      key: const ValueKey('ct.desktopTitleBar'),
      height: macSidebarLayout ? 40 : ctTitleBarHeight,
      decoration: BoxDecoration(
        color: ctSurface2,
        border:
            macSidebarLayout || sidebarToggle == null || sidebarWidth == null
            ? const Border(bottom: BorderSide(color: ctBorder))
            : null,
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 1180;
          // macOS 的原生交通灯占据左端。侧栏宽度从 248 收到 56 时，
          // 切换按钮仍留在交通灯右侧的同一位置，不跟着侧栏右缘移动。
          final leadingSidebarToggle = macSidebarLayout;
          Widget dragArea(Widget child) => macSidebarLayout
              ? GestureDetector(
                  behavior: HitTestBehavior.translucent,
                  onPanStart: (_) => windowManager.startDragging(),
                  child: child,
                )
              : DragToMoveArea(child: child);
          final sidebarTitleWidth = (sidebarWidth ?? 0) - leadingInset;
          // 标题穿过侧栏边界，但要给居中的状态和快速打开留足空间。
          final macTitleWidth =
              (constraints.maxWidth / 2 -
                      leadingInset -
                      ctNavRailWidth -
                      ctGapMd -
                      (compact ? 24 : 170))
                  .clamp(0.0, 360.0);
          // 状态与快速打开在整条标题栏里水平居中：右侧只留给窗口按钮，
          // 大窗口（侧栏收起）时中间不再是一整片空白。
          final centerCluster =
              (compact || statusLabel == null) && onQuickOpen == null
              ? null
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (!compact && statusLabel != null) ...[
                      Tooltip(
                        message: statusLabel!,
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxWidth: 150),
                          child: CtStatusBadge(
                            label: statusLabel!,
                            tone: statusTone,
                            dot: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: ctGapSm),
                    ],
                    if (onQuickOpen != null)
                      _QuickOpenButton(
                        compact: compact,
                        onPressed: onQuickOpen!,
                      ),
                  ],
                );
          final identity = Row(
            children: [
              CtBrandMark(size: macSidebarLayout ? 18 : 22),
              const SizedBox(width: ctGapSm),
              Flexible(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: ctText(
                    size: ctFontSm,
                    color: ctInk,
                    weight: FontWeight.w700,
                  ),
                ),
              ),
              if (!compact && subtitle != null) ...[
                const SizedBox(width: ctGapSm),
                Container(width: 1, height: 14, color: ctBorderStrong),
                const SizedBox(width: ctGapSm),
                Flexible(
                  child: Text(
                    subtitle!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: ctText(size: ctFontXs, color: ctInk3),
                  ),
                ),
              ],
            ],
          );
          return Stack(
            children: [
              Row(
                children: [
                  if (leadingInset > 0) SizedBox(width: leadingInset),
                  if (leadingSidebarToggle)
                    SizedBox(
                      width: ctNavRailWidth,
                      child: Center(
                        child: CtTitlebarControlArea(child: sidebarToggle!),
                      ),
                    ),
                  for (final menu in menus) _TitleBarMenuButton(menu: menu),
                  if (menus.isNotEmpty) const _TitleBarDivider(),
                  if (leadingSidebarToggle && macTitleWidth > 0)
                    SizedBox(
                      width: macTitleWidth,
                      child: dragArea(
                        Padding(
                          padding: const EdgeInsets.only(left: ctGapXs),
                          child: identity,
                        ),
                      ),
                    ),
                  if (sidebarToggle != null && sidebarWidth != null) ...[
                    if (!leadingSidebarToggle &&
                        sidebarTitleWidth >= ctNavRailWidth)
                      SizedBox(
                        width: sidebarTitleWidth,
                        child: sidebarWidth! <= ctNavRailWidth
                            ? Center(child: sidebarToggle!)
                            : Row(
                                children: [
                                  Expanded(
                                    child: DragToMoveArea(
                                      child: Padding(
                                        padding: const EdgeInsets.only(
                                          left: ctGapMd,
                                        ),
                                        child: identity,
                                      ),
                                    ),
                                  ),
                                  sidebarToggle!,
                                  const SizedBox(width: ctGapSm),
                                ],
                              ),
                      ),
                    Expanded(child: dragArea(const SizedBox.expand())),
                  ] else
                    Expanded(
                      child: DragToMoveArea(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: ctGapMd,
                          ),
                          child: identity,
                        ),
                      ),
                    ),
                  if (showWindowControls) ...[
                    const SizedBox(width: ctGapXs),
                    WindowCaptionButton.minimize(
                      key: const ValueKey('ct.windowMinimize'),
                      brightness: Brightness.light,
                      onPressed: onMinimize,
                    ),
                    if (isMaximized)
                      WindowCaptionButton.unmaximize(
                        key: const ValueKey('ct.windowToggleMaximize'),
                        brightness: Brightness.light,
                        onPressed: onToggleMaximize,
                      )
                    else
                      WindowCaptionButton.maximize(
                        key: const ValueKey('ct.windowToggleMaximize'),
                        brightness: Brightness.light,
                        onPressed: onToggleMaximize,
                      ),
                    WindowCaptionButton.close(
                      key: const ValueKey('ct.windowClose'),
                      brightness: Brightness.light,
                      onPressed: onClose,
                    ),
                  ],
                ],
              ),
              if (centerCluster != null)
                Align(alignment: Alignment.center, child: centerCluster),
              if (sidebarToggle != null && sidebarWidth != null) ...[
                if (!macSidebarLayout)
                  Positioned(
                    key: const ValueKey('ct.titleBar.sidebarEdge'),
                    left: sidebarWidth! - 1,
                    top: 0,
                    bottom: 0,
                    child: const IgnorePointer(
                      child: ColoredBox(
                        color: ctBorder,
                        child: SizedBox(width: 1),
                      ),
                    ),
                  ),
                if (!macSidebarLayout)
                  Positioned(
                    key: const ValueKey('ct.titleBar.contentEdge'),
                    left: sidebarWidth!,
                    right: 0,
                    bottom: 0,
                    child: const IgnorePointer(
                      child: ColoredBox(
                        color: ctBorder,
                        child: SizedBox(height: 1),
                      ),
                    ),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _TitleBarMenuButton extends StatefulWidget {
  const _TitleBarMenuButton({required this.menu});

  final CtTitleBarMenu menu;

  @override
  State<_TitleBarMenuButton> createState() => _TitleBarMenuButtonState();
}

class _TitleBarMenuButtonState extends State<_TitleBarMenuButton> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final actions = widget.menu.actions;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: PopupMenuButton<int>(
        key: ValueKey('ct.titleBar.menu.${widget.menu.label}'),
        tooltip: widget.menu.label,
        padding: EdgeInsets.zero,
        position: PopupMenuPosition.under,
        popUpAnimationStyle: ctMenuStyle(context),
        onSelected: (index) => actions[index].onSelected(),
        itemBuilder: (context) => [
          for (var i = 0; i < actions.length; i++)
            PopupMenuItem<int>(
              value: i,
              enabled: actions[i].enabled,
              height: 34,
              padding: const EdgeInsets.symmetric(
                horizontal: ctGapSm,
                vertical: 0,
              ),
              child: _MenuActionRow(action: actions[i]),
            ),
        ],
        child: AnimatedContainer(
          duration: ctMotionDuration(context, ctMotionFast),
          curve: ctMotionCurve,
          height: ctTitleBarHeight,
          padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
          alignment: Alignment.center,
          color: _hovered ? ctAccentSofter : Colors.transparent,
          child: Text(
            widget.menu.label,
            style: ctText(size: ctFontSm, color: ctInk2),
          ),
        ),
      ),
    );
  }
}

class _MenuActionRow extends StatelessWidget {
  const _MenuActionRow({required this.action});

  final CtTitleBarAction action;

  @override
  Widget build(BuildContext context) {
    final foreground = action.enabled ? ctInk : ctInk3;
    return Row(
      children: [
        SizedBox(
          width: 18,
          child: action.selected
              ? Icon(Icons.check, size: 15, color: foreground)
              : null,
        ),
        Expanded(
          child: Text(
            action.label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: ctText(size: ctFontSm, color: foreground),
          ),
        ),
        if (action.shortcut case final shortcut?) ...[
          const SizedBox(width: ctGapLg),
          Text(
            shortcut,
            style: ctText(size: ctFontXs, color: ctInk3),
          ),
        ],
      ],
    );
  }
}

class _TitleBarDivider extends StatelessWidget {
  const _TitleBarDivider();

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

class _QuickOpenButton extends StatelessWidget {
  const _QuickOpenButton({required this.compact, required this.onPressed});

  final bool compact;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final shortcut = Theme.of(context).platform == TargetPlatform.macOS
        ? '⌘P'
        : 'Ctrl P';
    final tooltip = '快速打开（$shortcut）';
    return Tooltip(
      message: tooltip,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: ctGapXs),
        child: Material(
          color: ctSurface,
          borderRadius: ctRadiusSmAll,
          child: InkWell(
            key: const ValueKey('ct.titleBar.quickOpen'),
            onTap: onPressed,
            borderRadius: ctRadiusSmAll,
            child: Container(
              width: compact ? 32 : 158,
              height: 28,
              padding: EdgeInsets.symmetric(horizontal: compact ? ctGapSm : 10),
              decoration: BoxDecoration(
                border: Border.all(color: ctBorderStrong),
                borderRadius: ctRadiusSmAll,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.search, size: 14, color: ctInk3),
                  if (!compact) ...[
                    const SizedBox(width: ctGapSm),
                    Expanded(
                      child: Text(
                        '快速打开',
                        overflow: TextOverflow.ellipsis,
                        style: ctText(size: ctFontXs, color: ctInk3),
                      ),
                    ),
                    Text(shortcut, style: ctText(size: 10, color: ctInk3)),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
