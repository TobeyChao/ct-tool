import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/desktop_state.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';

/// 任务/日志/历史三张表的桌面状态面板（native-flutter-workbench 任务 4.5/4.8）。
///
/// 数据全部来自 `tasks.list`、`logs.list`、`history.list`：日志是有界分页列表（可继续加载），
/// 任务问题按需分页并可关闭通知，历史是内核保留的最近 5 条。
class WorkbenchDesktopPanel extends StatefulWidget {
  const WorkbenchDesktopPanel({
    super.key,
    required this.state,
    this.initialTab = 0,
  });

  final DesktopStateRepository state;
  final int initialTab;

  @override
  State<WorkbenchDesktopPanel> createState() => _WorkbenchDesktopPanelState();
}

class _WorkbenchDesktopPanelState extends State<WorkbenchDesktopPanel>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(
      length: 3,
      initialIndex: widget.initialTab,
      vsync: this,
    );
    widget.state.addListener(_onChanged);
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.state.removeListener(_onChanged);
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return Column(
      children: [
        Container(
          color: ctSurface,
          child: TabBar(
            key: const ValueKey('wb.desktopTabs'),
            controller: _tabs,
            tabs: const [
              Tab(text: '任务'),
              Tab(text: '日志'),
              Tab(text: '历史'),
            ],
          ),
        ),
        Expanded(
          child: TabBarView(
            controller: _tabs,
            children: [
              _tasks(state),
              _logs(state),
              WorkbenchHistoryView(
                key: const ValueKey('wb.historyView'),
                state: state,
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _tasks(DesktopStateRepository state) {
    if (state.tasks.isEmpty) {
      return _empty('本次连接还没有任务；导出、部署、模板与翻译都会出现在这里');
    }
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: ctGapMd),
      itemCount: state.tasks.length,
      itemBuilder: (context, index) {
        final task = state.tasks[index];
        final issues = state.issuesOf(task.id);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ListTile(
              key: ValueKey('wb.taskRow.${task.id}'),
              dense: true,
              leading: Icon(
                task.dismissed
                    ? Icons.notifications_off
                    : Icons.assignment_outlined,
                size: 16,
                color: ctInk3,
              ),
              title: Text(
                '${task.method} · ${_statusLabel(task.status)}',
                style: ctText(size: ctFontSm, weight: FontWeight.w600),
              ),
              subtitle: Text(
                task.message.isEmpty ? task.id : '${task.id} · ${task.message}',
                style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk2),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              trailing: Wrap(
                spacing: 4,
                children: [
                  CtButton.ghost(
                    '问题',
                    onPressed: () => state.loadIssues(task.id),
                  ),
                  CtButton.ghost(
                    '忽略',
                    key: ValueKey('wb.taskDismiss.${task.id}'),
                    onPressed: task.dismissed
                        ? null
                        : () => state.dismiss(task.id),
                  ),
                ],
              ),
            ),
            if (issues != null)
              Padding(
                padding: const EdgeInsets.only(left: ctGapLg, bottom: ctGapSm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '问题 ${issues.issues.length} 条（代次 ${issues.revision}）',
                      key: ValueKey('wb.taskIssues.${task.id}'),
                      style: ctText(size: ctFontXs, color: ctInk3),
                    ),
                    for (final issue in issues.issues)
                      Text(
                        '✗ ${issue.resource ?? ''} ${issue.fieldPath ?? ''} '
                        '${issue.excelRow != null ? 'Excel 第 ${issue.excelRow} 行 ' : ''}${issue.message}',
                        key: ValueKey('wb.taskIssueRow.${task.id}'),
                        style: ctText(size: ctFontXs, color: ctDanger),
                      ),
                    if (issues.nextCursor != null)
                      CtButton.ghost(
                        '更多问题',
                        onPressed: () =>
                            state.loadIssues(task.id, append: true),
                      ),
                  ],
                ),
              ),
            const Divider(height: 1),
          ],
        );
      },
    );
  }

  static String _statusLabel(TaskStatus status) => switch (status) {
    TaskStatus.running => '进行中',
    TaskStatus.success => '成功',
    TaskStatus.error => '失败',
    TaskStatus.cancelled => '已取消',
    TaskStatus.unknown => '结果未知',
  };

  Widget _logs(DesktopStateRepository state) {
    const modules = ['全部', 'export', 'i18n', 'deploy', 'recover', 'control'];
    const levels = ['全部', 'info', 'warn', 'error'];
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
            ctGapMd,
            ctGapSm,
            ctGapMd,
            ctGapSm,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 4,
                runSpacing: 4,
                children: [
                  for (final module in modules)
                    ChoiceChip(
                      key: ValueKey('wb.logModule.$module'),
                      label: Text(module, style: ctText(size: ctFontXs)),
                      selected: (state.logModule ?? '全部') == module,
                      onSelected: (_) => state.setLogFilter(
                        module: module == '全部' ? null : module,
                        level: state.logLevel,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 4,
                runSpacing: 4,
                children: [
                  for (final level in levels)
                    ChoiceChip(
                      key: ValueKey('wb.logLevel.$level'),
                      label: Text(level, style: ctText(size: ctFontXs)),
                      selected: (state.logLevel ?? '全部') == level,
                      onSelected: (_) => state.setLogFilter(
                        module: state.logModule,
                        level: level == '全部' ? null : level,
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
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
      ],
    );
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
}

/// 最近五次导出（内核 `history.list`，最新在前、跨重启保留）。
class WorkbenchHistoryView extends StatefulWidget {
  const WorkbenchHistoryView({super.key, required this.state});

  final DesktopStateRepository state;

  @override
  State<WorkbenchHistoryView> createState() => _WorkbenchHistoryViewState();
}

class _WorkbenchHistoryViewState extends State<WorkbenchHistoryView> {
  @override
  void initState() {
    super.initState();
    widget.state.addListener(_onChanged);
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.state.removeListener(_onChanged);
    super.dispose();
  }

  /// 旧状态码归一：只认内核会写出的 `success`，其余原样展示为「未知（原码）」，
  /// 不猜语义、也不谎报成功。
  static (String label, CtBadgeTone tone) _result(HistoryEntry entry) {
    return switch (entry.result) {
      'success' => ('成功', CtBadgeTone.ok),
      'cancelled' => ('已取消', CtBadgeTone.neutral),
      'error' || 'failed' => ('失败', CtBadgeTone.danger),
      final other => ('未知（$other）', CtBadgeTone.neutral),
    };
  }

  @override
  Widget build(BuildContext context) {
    final entries = widget.state.history;
    if (entries.isEmpty) {
      return Center(
        child: Text(
          '还没有导出历史；桌面导出成功后会保留最近 5 条',
          key: const ValueKey('wb.historyEmpty'),
          style: ctText(size: ctFontSm, color: ctInk3),
        ),
      );
    }
    return ListView.builder(
      key: const ValueKey('wb.historyList'),
      padding: const EdgeInsets.symmetric(vertical: ctGapSm),
      itemCount: entries.length,
      itemBuilder: (context, index) {
        final entry = entries[index];
        final (label, tone) = _result(entry);
        return ListTile(
          key: const ValueKey('wb.historyRow'),
          dense: true,
          leading: CtStatusBadge(label: label, tone: tone, dot: false),
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
    );
  }
}
