import 'package:flutter/material.dart';

import '../services/panel_service.dart';
import '../services/settings_store.dart';
import '../theme.dart';
import 'pages/logs_page.dart';
import 'pages/overview_page.dart';
import 'pages/settings_page.dart';
import 'widgets/common.dart';

enum _Tab { overview, logs, settings }

/// 启动器主界面壳：左侧导航 + 右侧内容区，负责页签切换与侧栏状态。
class LauncherScreen extends StatefulWidget {
  const LauncherScreen({super.key, required this.settings, required this.panel});

  final SettingsStore settings;
  final PanelService panel;

  @override
  State<LauncherScreen> createState() => _LauncherScreenState();
}

class _LauncherScreenState extends State<LauncherScreen> {
  _Tab _tab = _Tab.overview;

  @override
  void initState() {
    super.initState();
    // 侧栏状态行依赖 panel 状态与端口，变化时刷新
    widget.panel.addListener(_onChanged);
    widget.settings.addListener(_onChanged);
  }

  @override
  void dispose() {
    widget.panel.removeListener(_onChanged);
    widget.settings.removeListener(_onChanged);
    super.dispose();
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion =
        MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    return Scaffold(
      body: Row(
        children: [
          _buildSideNav(),
          const VerticalDivider(width: 1, thickness: 1, color: ctBorder),
          Expanded(
            child: AnimatedSwitcher(
              duration: reduceMotion
                  ? Duration.zero
                  : const Duration(milliseconds: 180),
              child: KeyedSubtree(
                key: ValueKey(_tab),
                child: _buildPage(),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSideNav() {
    final s = panelStatusPresentation(
      widget.panel.status,
      widget.panel.failureReason,
    );
    return Container(
      width: 176,
      decoration: const BoxDecoration(
        color: ctSurface,
        border: Border(right: BorderSide(color: ctBorder)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 44),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                CtBrandMark(),
                SizedBox(width: 9),
                Text(
                  'ct Launcher',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          const SizedBox(height: 22),
          CtNavItem(
            icon: Icons.power_settings_new,
            label: '概览',
            selected: _tab == _Tab.overview,
            onTap: () => setState(() => _tab = _Tab.overview),
          ),
          CtNavItem(
            icon: Icons.terminal,
            label: '日志',
            selected: _tab == _Tab.logs,
            onTap: () => setState(() => _tab = _Tab.logs),
          ),
          CtNavItem(
            icon: Icons.tune,
            label: '设置',
            selected: _tab == _Tab.settings,
            onTap: () => setState(() => _tab = _Tab.settings),
          ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
            child: Row(
              children: [
                Container(
                  width: 9,
                  height: 9,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: s.dot,
                    boxShadow: [
                      BoxShadow(
                        color: s.dot.withValues(alpha: 0.3),
                        blurRadius: 0,
                        spreadRadius: 3,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  s.title,
                  style: const TextStyle(fontSize: 12, color: ctInk2),
                ),
                const Spacer(),
                Text(
                  '${widget.settings.port}',
                  style: ctMono.copyWith(fontSize: 11, color: ctInk3),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPage() {
    return switch (_tab) {
      _Tab.overview =>
        OverviewPage(panel: widget.panel, settings: widget.settings),
      _Tab.logs => LogsPage(panel: widget.panel),
      _Tab.settings => SettingsPage(
          settings: widget.settings,
          panel: widget.panel,
        ),
    };
  }
}
