import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/panel_service.dart';
import '../../services/settings_store.dart';
import '../../services/stats_service.dart';
import '../../theme.dart';
import '../widgets/common.dart';

/// 概览页：启停状态 + 统计数据 + 工作区提示
class OverviewPage extends StatefulWidget {
  const OverviewPage({super.key, required this.panel, required this.settings});

  final PanelService panel;
  final SettingsStore settings;

  @override
  State<OverviewPage> createState() => _OverviewPageState();
}

class _OverviewPageState extends State<OverviewPage> {
  LauncherStats? _stats;

  PanelStatus get _status => widget.panel.status;

  @override
  void initState() {
    super.initState();
    widget.panel.addListener(_onPanelChanged);
    _loadStats();
  }

  @override
  void dispose() {
    widget.panel.removeListener(_onPanelChanged);
    super.dispose();
  }

  void _onPanelChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _loadStats() async {
    final stats = await StatsService.load(widget.settings.workspacePath);
    if (mounted) setState(() => _stats = stats);
  }

  Future<void> _openPanel() async {
    try {
      await openPanelInBrowser(widget.panel.baseUrl);
    } catch (_) {
      if (!mounted) return;
      showCtToast(context, '无法打开面板，请检查服务是否已启动');
    }
  }

  Future<void> _copyAddress() async {
    await Clipboard.setData(ClipboardData(text: widget.panel.baseUrl));
    if (!mounted) return;
    showCtToast(context, '地址已复制');
  }

  Future<void> _openWorkspace() async {
    final ws = widget.settings.workspacePath;
    if (ws.isEmpty) {
      showCtToast(context, '请先在工作区设置中填写路径');
      return;
    }
    await openInFileManager(ws);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(26, 20, 26, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('概览', style: ctPageTitleStyle),
          const SizedBox(height: 12),
          Expanded(
            child: Column(
              children: [
                _buildHero(),
                const SizedBox(height: 20),
                _buildStats(),
              ],
            ),
          ),
          const SizedBox(height: 8),
          CtFooterHint(child: _buildWorkspaceLine()),
        ],
      ),
    );
  }

  Widget _buildHero() {
    final s = panelStatusPresentation(_status, widget.panel.failureReason);
    final active =
        _status == PanelStatus.running || _status == PanelStatus.starting;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: ctBorder),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A1B241F),
            blurRadius: 28,
            offset: Offset(0, 8),
          ),
        ],
      ),
      child: Row(
        children: [
          _buildToggle(active),
          const SizedBox(width: 24),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 11,
                      height: 11,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: s.dot,
                        boxShadow: [
                          BoxShadow(
                            color: s.dot.withValues(alpha: 0.25),
                            blurRadius: 0,
                            spreadRadius: 4,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      s.title,
                      style: const TextStyle(
                        fontSize: 21,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  s.sub,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 13, color: ctInk2),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    _buildAddr(s.hint),
                    const SizedBox(width: 10),
                    Text(
                      s.hint,
                      style: const TextStyle(fontSize: 12, color: ctInk3),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                _buildActions(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildToggle(bool active) {
    final starting = _status == PanelStatus.starting;
    return GestureDetector(
      onTap: starting
          ? null
          : (_status == PanelStatus.running
              ? widget.panel.stop
              : widget.panel.start),
      child: Container(
        width: 104,
        height: 104,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(
            color: active ? ctAccent : ctBorderStrong,
            width: 2,
          ),
          gradient: active
              ? const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [Color(0xFF2F7A56), ctPrimary],
                )
              : null,
          color: active ? null : ctSurface,
          boxShadow: active
              ? const [
                  BoxShadow(
                    color: Color(0x592F7A56),
                    blurRadius: 30,
                    offset: Offset(0, 10),
                  ),
                ]
              : null,
        ),
        child: Stack(
          alignment: Alignment.center,
          children: [
            if (active)
              const SizedBox(
                width: 104,
                height: 104,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: Color(0x8CD8F3DC),
                ),
              ),
            Icon(
              Icons.power_settings_new,
              size: 42,
              color: active ? Colors.white : ctInk3,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAddr(String hint) {
    final running = _status == PanelStatus.running;
    return InkWell(
      onTap: running ? _copyAddress : null,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        decoration: BoxDecoration(
          color: running ? ctAccentSofter : ctSurface2,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: running ? ctAccent : ctBorder),
        ),
        child: Text(
          widget.panel.baseUrl,
          style: ctMono.copyWith(
            fontSize: 13,
            color: running ? ctAccentHover : ctInk2,
          ),
        ),
      ),
    );
  }

  Widget _buildActions() {
    final running = _status == PanelStatus.running;
    final failed = _status == PanelStatus.failed;
    return Wrap(
      spacing: 10,
      runSpacing: 8,
      children: [
        if (running) ...[
          CtButton.accent('打开面板', onPressed: _openPanel),
          CtButton.ghost('打开工作区目录', onPressed: _openWorkspace),
        ] else if (failed) ...[
          CtButton.accent('重试', onPressed: widget.panel.start),
          CtButton.ghost('打开工作区目录', onPressed: _openWorkspace),
        ] else ...[
          CtButton.ghost('打开工作区目录', onPressed: _openWorkspace),
        ],
      ],
    );
  }

  Widget _buildStats() {
    final s = _stats;
    final languages =
        s == null || s.languages.isEmpty ? '-' : s.languages.join(' / ');
    final last = s?.lastExportAt;
    String two(int n) => n.toString().padLeft(2, '0');
    final lastTime =
        last == null ? '暂无' : '${two(last.hour)}:${two(last.minute)}';
    return Row(
      children: [
        Expanded(
          child: SizedBox(
            height: 132,
            child: CtStatCard(
              number: '${s?.tableCount ?? '-'}',
              label: '数据表',
              sub: 'config/schemas',
              icon: Icons.table_chart_outlined,
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: SizedBox(
            height: 132,
            child: CtStatCard(
              number: '${s?.languages.length ?? '-'}',
              label: '导出语言',
              sub: languages,
              icon: Icons.translate,
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: SizedBox(
            height: 132,
            child: CtStatCard(
              number: lastTime,
              label: '最近导出',
              sub: last == null ? '暂无记录' : '全部表',
              icon: Icons.schedule,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildWorkspaceLine() {
    final ws = widget.settings.workspacePath;
    return Row(
      children: [
        const Icon(Icons.folder_outlined, size: 14, color: ctInk3),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            ws.isEmpty ? '工作区未配置，请到设置中选择' : ws,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: ctMono.copyWith(fontSize: 12, color: ctInk3),
          ),
        ),
      ],
    );
  }
}
