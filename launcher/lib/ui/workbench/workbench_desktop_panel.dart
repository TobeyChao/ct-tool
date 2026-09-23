import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/desktop_state.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';

/// 桌面状态视图：日志与历史作为侧栏模块独立展示。
///
/// 数据来自 `logs.list`（模块/级别筛选 + 游标翻页）与
/// `history.list`（最新在前、最多保留 5 条）。

/// 有界日志列表；模块/级别筛选与分页都由内核执行。
class WorkbenchLogView extends StatelessWidget {
  const WorkbenchLogView({super.key, required this.state});

  final DesktopStateRepository state;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => _logs(state),
    );
  }

  Widget _logs(DesktopStateRepository state) {
    const modules = ['全部', 'export', 'i18n', 'deploy', 'recover', 'control'];
    const levels = ['全部', 'info', 'warn', 'error'];
    return _DesktopPageFrame(
      header: const CtPageHeader(title: '日志', subtitle: '查看原生内核产生的模块日志。'),
      controls: CtSurfaceCard(
        padding: const EdgeInsets.all(ctGapSm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '模块',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
            const SizedBox(height: ctGapXs),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final module in modules)
                  CtChoicePill(
                    key: ValueKey('wb.logModule.$module'),
                    label: module,
                    selected: (state.logModule ?? '全部') == module,
                    dense: true,
                    onTap: () => state.setLogFilter(
                      module: module == '全部' ? null : module,
                      level: state.logLevel,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: ctGapSm),
            Text(
              '级别',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
            const SizedBox(height: ctGapXs),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final level in levels)
                  CtChoicePill(
                    key: ValueKey('wb.logLevel.$level'),
                    label: level,
                    selected: (state.logLevel ?? '全部') == level,
                    dense: true,
                    onTap: () => state.setLogFilter(
                      module: state.logModule,
                      level: level == '全部' ? null : level,
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
      child: CtSurfaceCard(
        padding: EdgeInsets.zero,
        child: state.logs.isEmpty
            ? _empty(state.busy ? '读取中…' : '没有符合条件的日志')
            : ListView.builder(
                key: const ValueKey('wb.logList'),
                itemCount: state.logs.length + (state.logsHasMore ? 1 : 0),
                itemBuilder: (context, index) {
                  if (index >= state.logs.length) {
                    return Padding(
                      padding: const EdgeInsets.all(ctGapSm),
                      child: Center(
                        child: CtButton.ghost(
                          '加载更多日志',
                          key: const ValueKey('wb.loadMoreLogs'),
                          onPressed: state.loadMoreLogs,
                        ),
                      ),
                    );
                  }
                  final entry = state.logs[index];
                  return ListTile(
                    key: const ValueKey('wb.logRow'),
                    dense: true,
                    title: Text(
                      '[${entry.module}] ${entry.message}',
                      style: ctMono.copyWith(fontSize: ctFontXs),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(
                      '${entry.level}${entry.requestId == null ? '' : ' · 请求 #${entry.requestId}'}',
                      style: ctText(size: ctFontXs, color: ctInk3),
                    ),
                  );
                },
              ),
      ),
    );
  }
}

Widget _empty(String text) => Center(
  child: Padding(
    padding: const EdgeInsets.all(ctGapLg),
    child: Text(
      text,
      style: ctText(size: ctFontSm, color: ctInk3),
    ),
  ),
);

/// 最近五次导出（内核 `history.list`，最新在前、跨重启保留）。
class WorkbenchHistoryView extends StatelessWidget {
  const WorkbenchHistoryView({super.key, required this.state});

  final DesktopStateRepository state;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: state,
      builder: (context, _) => _history(context),
    );
  }

  Widget _history(BuildContext context) {
    final entries = state.history;
    return _DesktopPageFrame(
      header: const CtPageHeader(title: '历史', subtitle: '查看最近 5 次发布记录。'),
      child: CtSurfaceCard(
        padding: EdgeInsets.zero,
        child: entries.isEmpty
            ? Center(
                child: Text(
                  '还没有发布记录；成功导出后会保留最近 5 次。',
                  key: const ValueKey('wb.historyEmpty'),
                  style: ctText(size: ctFontSm, color: ctInk3),
                ),
              )
            : ListView.builder(
                key: const ValueKey('wb.historyList'),
                padding: const EdgeInsets.symmetric(vertical: ctGapSm),
                itemCount: entries.length,
                itemBuilder: (context, index) {
                  final entry = entries[index];
                  final (label, tone) = _result(entry);
                  return ListTile(
                    key: const ValueKey('wb.historyRow'),
                    dense: true,
                    leading: CtStatusBadge(
                      label: label,
                      tone: tone,
                      dot: false,
                    ),
                    title: Text(
                      '${entry.scope} · ${entry.tables} 张表',
                      style: ctText(size: ctFontSm, weight: FontWeight.w600),
                    ),
                    subtitle: Text(
                      '${entry.time} · ${entry.elapsed.toStringAsFixed(2)}s'
                      '${entry.forced ? ' · 强制重建' : ''}'
                      '${entry.error.isEmpty ? '' : ' · ${entry.error}'}',
                      style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk2),
                    ),
                  );
                },
              ),
      ),
    );
  }

  /// 旧状态码归一：只认内核会写出的 `success`，其余原样展示为“未知（原码）”。
  static (String label, CtBadgeTone tone) _result(HistoryEntry entry) {
    return switch (entry.result) {
      'success' => ('成功', CtBadgeTone.ok),
      'cancelled' => ('已取消', CtBadgeTone.neutral),
      'error' || 'failed' => ('失败', CtBadgeTone.danger),
      final other => ('未知（$other）', CtBadgeTone.neutral),
    };
  }
}

class _DesktopPageFrame extends StatelessWidget {
  const _DesktopPageFrame({
    required this.header,
    required this.child,
    this.controls,
  });

  final Widget header;
  final Widget? controls;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(ctGapLg),
      child: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: ctPageMaxWidth),
          child: SizedBox(
            width: double.infinity,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                header,
                if (controls != null) ...[
                  const SizedBox(height: ctGapMd),
                  controls!,
                ],
                const SizedBox(height: ctGapSm),
                Expanded(child: child),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
