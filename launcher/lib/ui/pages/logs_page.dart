import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../models/log_entry.dart';
import '../../services/panel_service.dart';
import '../../theme.dart';
import '../widgets/common.dart';

/// 日志页：实时滚动日志 + 复制 / 清空 / 回到底部
class LogsPage extends StatefulWidget {
  const LogsPage({super.key, required this.panel});

  final PanelService panel;

  @override
  State<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends State<LogsPage> {
  final _logController = ScrollController();
  bool _pinBottom = true;

  @override
  void initState() {
    super.initState();
    widget.panel.addListener(_onPanelChanged);
    _logController.addListener(_onLogScroll);
  }

  @override
  void dispose() {
    widget.panel.removeListener(_onPanelChanged);
    _logController.dispose();
    super.dispose();
  }

  void _onPanelChanged() {
    if (mounted) setState(() {});
    if (_pinBottom) _jumpToBottom();
  }

  void _onLogScroll() {
    final pos = _logController.position;
    if (!pos.hasContentDimensions) return;
    final nearBottom = pos.pixels >= pos.maxScrollExtent - 24;
    if (nearBottom != _pinBottom) setState(() => _pinBottom = nearBottom);
  }

  void _jumpToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_logController.hasClients) {
        _logController.jumpTo(_logController.position.maxScrollExtent);
      }
    });
  }

  Future<void> _copyLogs() async {
    await Clipboard.setData(ClipboardData(text: widget.panel.logText));
    if (!mounted) return;
    showCtToast(context, '日志已复制到剪贴板');
  }

  @override
  Widget build(BuildContext context) {
    final logs = widget.panel.logs;
    return Padding(
      padding: const EdgeInsets.fromLTRB(26, 20, 26, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('运行日志', style: ctPageTitleStyle),
              const Spacer(),
              CtButton.ghost('复制', onPressed: _copyLogs),
              const SizedBox(width: 6),
              CtButton.ghost('清空', onPressed: widget.panel.clearLogs),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: Stack(
              children: [
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: ctLogBg,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: ctLogBorder),
                  ),
                  child: logs.isEmpty
                      ? const Center(
                          child: Text(
                            '暂无日志，启动服务后这里会显示运行记录',
                            style: TextStyle(
                              fontSize: 12,
                              color: Color(0xFF5E7368),
                            ),
                          ),
                        )
                      : ListView.builder(
                          controller: _logController,
                          itemCount: logs.length,
                          itemBuilder: (_, i) => _logLine(logs[i]),
                        ),
                ),
                if (!_pinBottom)
                  Positioned(
                    right: 12,
                    bottom: 12,
                    child: FloatingActionButton.small(
                      heroTag: 'log-back-to-bottom',
                      backgroundColor: ctPrimary,
                      foregroundColor: Colors.white,
                      tooltip: '回到底部',
                      onPressed: () {
                        setState(() => _pinBottom = true);
                        _jumpToBottom();
                      },
                      child: const Icon(Icons.arrow_downward, size: 18),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          const CtFooterHint(
            child: Row(
              children: [
                Icon(Icons.info_outline, size: 14, color: ctInk3),
                SizedBox(width: 8),
                Text(
                  '日志保留最近 500 条，启动服务后自动跟随最新输出',
                  style: TextStyle(fontSize: 12, color: ctInk3),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _logLine(LogEntry e) {
    final (tag, color) = switch (e.level) {
      LogLevel.info => ('[INFO]', const Color(0xFF7FD6A8)),
      LogLevel.warn => ('[WARN]', const Color(0xFFE5C078)),
      LogLevel.error => ('[ERROR]', const Color(0xFFE8837F)),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 固定宽度前缀列：时间戳 + 级别，长行换行后消息起点对齐
          SizedBox(
            width: 142,
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(
                    text: '${e.timestamp} ',
                    style: ctMono.copyWith(
                      fontSize: 12,
                      color: const Color(0xFF6E8277),
                    ),
                  ),
                  TextSpan(
                    text: '$tag ',
                    style: ctMono.copyWith(fontSize: 12, color: color),
                  ),
                ],
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Expanded(
            child: Text(
              e.message,
              style: ctMono.copyWith(fontSize: 12, color: ctLogText),
            ),
          ),
        ],
      ),
    );
  }
}
