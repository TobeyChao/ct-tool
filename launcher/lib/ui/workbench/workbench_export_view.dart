import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/export_runner.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';

/// 导出模块（2026-09-22：按 Web 导出页收敛信息层级）。
///
/// 页面只保留 Web 同款三类内容：标题区的状态与动作、执行进度、本次导出上下文。
/// 表/语言过滤、独立校验、独立部署和运行日志不再出现在本页；导出仍由内核在发布前
/// 完整校验，失败问题直接归入执行进度。
class WorkbenchExportView extends StatelessWidget {
  const WorkbenchExportView({
    super.key,
    required this.runner,
    this.blockReason,
  });

  final ExportRunner runner;

  /// 写入口不可用的原因（内核未就绪/协议不兼容/能力缺失）；null 表示可用。
  final String? blockReason;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: runner,
      builder: (context, _) {
        return CtPageContent(
          key: const ValueKey('wb.exportView'),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _header(),
              if (_hasHints) ...[const SizedBox(height: ctGapMd), _hints()],
              const SizedBox(height: ctGapLg),
              LayoutBuilder(
                builder: (context, constraints) {
                  final progress = _progressCard();
                  final contextCard = _contextCard();
                  if (constraints.maxWidth >= 880) {
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(child: progress),
                        const SizedBox(width: ctGapLg),
                        SizedBox(width: 280, child: contextCard),
                      ],
                    );
                  }
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      progress,
                      const SizedBox(height: ctGapMd),
                      contextCard,
                    ],
                  );
                },
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _header() {
    final heading = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('导出', style: ctPageTitleStyle),
        const SizedBox(height: ctGapXs),
        Text(
          '增量导出：校验通过后复用未变化产物，生成 JSON、FBS、Binary 与 C#/Lua Accessor。',
          style: ctPageSubtitleStyle,
        ),
      ],
    );
    final actions = _actionBar();
    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= 820) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(child: heading),
              const SizedBox(width: ctGapLg),
              actions,
            ],
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            heading,
            const SizedBox(height: ctGapMd),
            actions,
          ],
        );
      },
    );
  }

  Widget _actionBar() {
    final blocked = blockReason != null;
    final running = runner.running;
    return Wrap(
      spacing: ctGapSm,
      runSpacing: ctGapSm,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _phaseBadge(),
        if (running)
          CtButton.ghost(
            '取消',
            key: const ValueKey('wb.exportCancel'),
            onPressed: runner.runningRequestId == null ? null : runner.cancel,
          ),
        CtButton.ghost(
          '强制全量重建',
          key: const ValueKey('wb.exportForce'),
          onPressed: blocked || running
              ? null
              : () => runner.startExport(forced: true),
        ),
        CtButton.accent(
          runner.last == null ? '开始导出' : '重新导出',
          key: const ValueKey('wb.exportRun'),
          onPressed: blocked || running
              ? null
              : () => runner.startExport(forced: false),
        ),
      ],
    );
  }

  Widget _phaseBadge() {
    final (label, tone) = switch (runner.phase) {
      RunnerPhase.idle => ('准备就绪', CtBadgeTone.info),
      RunnerPhase.running => ('导出中', CtBadgeTone.busy),
      RunnerPhase.succeeded => ('导出成功', CtBadgeTone.ok),
      RunnerPhase.cancelled => ('已取消', CtBadgeTone.neutral),
      RunnerPhase.failed => ('导出中止', CtBadgeTone.danger),
      RunnerPhase.unknown => ('终态未知', CtBadgeTone.warn),
    };
    return CtStatusBadge(
      key: const ValueKey('wb.exportPhase'),
      label: label,
      tone: tone,
      dot: false,
    );
  }

  bool get _hasHints =>
      blockReason != null || runner.needsUserDecision || runner.error != null;

  Widget _hints() {
    final blocks = <Widget>[];
    if (blockReason != null) {
      blocks.add(
        _banner(
          key: const ValueKey('wb.exportBlocked'),
          text: blockReason!,
          fg: ctWarn,
          bg: ctWarnSoft,
        ),
      );
    }
    if (runner.needsUserDecision) {
      blocks.add(
        _banner(
          key: const ValueKey('wb.exportUnknown'),
          text:
              '连接断开，上一次任务终态未知：没有自动重放写请求。'
              '请先在「历史」确认结果，再决定是否重试。',
          fg: ctDanger,
          bg: ctDangerSoft,
        ),
      );
    }
    if (runner.error != null) {
      blocks.add(
        _banner(
          key: const ValueKey('wb.exportError'),
          text: runner.error!,
          fg: ctDanger,
          bg: ctDangerSoft,
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final block in blocks)
          Padding(
            padding: const EdgeInsets.only(bottom: ctGapSm),
            child: block,
          ),
      ],
    );
  }

  Widget _progressCard() {
    final progress = runner.progress;
    final result = runner.running ? null : runner.result;
    final issues = runner.running
        ? <Issue>[for (final event in runner.liveIssues) event.issue]
        : runner.issues;
    final lastStage = result != null && result.stages.isNotEmpty
        ? result.stages.last.name
        : '—';

    return _card(
      key: const ValueKey('wb.exportProgress'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '执行进度',
                style: ctText(size: ctFontSm, weight: FontWeight.w600),
              ),
              const Spacer(),
              Text(
                '任务状态自动更新',
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
            ],
          ),
          const SizedBox(height: ctGapSm),
          Text(
            _progressMessage(progress, result),
            key: const ValueKey('wb.exportMessage'),
            style: ctText(size: ctFontSm, color: ctInk2),
          ),
          if (runner.running) ...[
            const SizedBox(height: ctGapMd),
            if (progress == null || progress.total <= 0)
              const LinearProgressIndicator(minHeight: 4)
            else
              LinearProgressIndicator(
                value: progress.done / progress.total,
                minHeight: 4,
              ),
          ],
          if (progress != null && runner.running) ...[
            const SizedBox(height: ctGapMd),
            _stageCell(
              index: 1,
              label: '${progress.stage} ${progress.done}/${progress.total}',
              active: true,
            ),
          ] else if (result != null && result.stages.isNotEmpty) ...[
            const SizedBox(height: ctGapMd),
            Wrap(
              spacing: ctGapSm,
              runSpacing: ctGapSm,
              children: [
                for (final (index, stage) in result.stages.indexed)
                  _stageCell(
                    index: index + 1,
                    label: stage.name,
                    done: true,
                    elapsedMs: stage.elapsedMs,
                  ),
              ],
            ),
          ],
          if (issues.isNotEmpty) ...[
            const SizedBox(height: ctGapMd),
            for (final (index, issue) in issues.take(5).indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: ctGapXs),
                child: Text(
                  '${issue.code}：${issue.message}',
                  key: ValueKey('wb.exportIssue.$index'),
                  style: ctText(size: ctFontSm, color: ctDanger),
                ),
              ),
            if (issues.length > 5)
              Text(
                '其余 ${issues.length - 5} 个问题可在「历史」查看。',
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
          ],
          if (runner.running || result != null) ...[
            const SizedBox(height: ctGapMd),
            Wrap(
              spacing: ctGapLg,
              runSpacing: ctGapXs,
              children: [
                _stat('已导出', '${result?.tables ?? 0} 张表'),
                _stat('当前阶段', progress?.stage ?? lastStage),
                _stat('耗时', _elapsed(result?.durationMs)),
              ],
            ),
          ],
          if (!runner.running &&
              result == null &&
              runner.phase == RunnerPhase.idle)
            Padding(
              padding: const EdgeInsets.only(top: ctGapMd),
              child: Text(
                '还没有导出记录',
                key: const ValueKey('wb.exportEmpty'),
                style: ctText(size: ctFontSm, color: ctInk3),
              ),
            ),
        ],
      ),
    );
  }

  String _progressMessage(ProgressEvent? progress, ExportResult? result) {
    if (runner.running) {
      return progress == null
          ? '正在准备导出…'
          : '${progress.stage} · ${progress.done}/${progress.total}';
    }
    if (result != null) {
      return '导出完成：${result.tables} 张表 · ${_elapsed(result.durationMs)}';
    }
    if (runner.needsUserDecision) return '连接已断开，任务终态未知';
    if (runner.phase == RunnerPhase.cancelled) return '本次导出已取消';
    if (runner.phase == RunnerPhase.failed) {
      return runner.last?.message ?? runner.error ?? '导出中止';
    }
    return '完成首次导出后，这里会保留阶段结果';
  }

  Widget _stageCell({
    required int index,
    required String label,
    bool active = false,
    bool done = false,
    int? elapsedMs,
  }) {
    final tone = active
        ? ctAccent
        : done
        ? ctPrimary
        : ctBorderStrong;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: ctGapSm, vertical: 6),
      decoration: BoxDecoration(
        color: active ? ctAccentSoft : ctSurface2,
        borderRadius: ctRadiusSmAll,
        border: Border.all(color: tone),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 18,
            height: 18,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: active ? ctAccent : ctSurface,
              shape: BoxShape.circle,
              border: Border.all(color: tone),
            ),
            child: Text(
              '$index',
              style: ctText(
                size: 10,
                weight: FontWeight.w600,
                color: active ? Colors.white : ctInk2,
              ),
            ),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: ctText(size: ctFontXs, color: ctInk2),
          ),
          if (elapsedMs != null) ...[
            const SizedBox(width: 6),
            Text(
              '${elapsedMs}ms',
              style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
            ),
          ],
        ],
      ),
    );
  }

  Widget _contextCard() {
    final result = runner.result;
    final output = runner.workspaceRoot.isEmpty
        ? '—'
        : '${runner.workspaceRoot}/output';
    return _card(
      key: const ValueKey('wb.exportContext'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '本次导出',
            style: ctText(size: ctFontSm, weight: FontWeight.w700, height: 1.2),
          ),
          const SizedBox(height: 10),
          _contextRow('构建模式', runner.all ? '强制全量重建' : '增量导出'),
          _contextRow('执行结果', _resultLabel(result)),
          _contextRow('产物目录', output, path: true),
        ],
      ),
    );
  }

  String _resultLabel(ExportResult? result) {
    if (runner.running) {
      return runner.progress == null
          ? '准备中'
          : '进行中 · ${runner.progress!.stage}';
    }
    if (result != null) {
      return '成功 · ${result.tables} 张表 · ${_elapsed(result.durationMs)}';
    }
    return switch (runner.phase) {
      RunnerPhase.cancelled => '已取消',
      RunnerPhase.failed => runner.last?.message ?? '导出中止',
      RunnerPhase.unknown => '终态未知',
      _ => '暂无记录',
    };
  }

  Widget _contextRow(String label, String value, {bool path = false}) {
    final decoration = const BoxDecoration(
      border: Border(top: BorderSide(color: ctBorder)),
    );
    if (path) {
      return Container(
        padding: const EdgeInsets.symmetric(vertical: 9),
        decoration: decoration,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: ctText(size: ctFontXs, color: ctInk3, height: 1.4),
            ),
            const SizedBox(height: ctGapXs),
            Text(
              value,
              style: ctMono.copyWith(fontSize: 11, height: 1.55, color: ctInk2),
            ),
          ],
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 9),
      decoration: decoration,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 82,
            child: Text(
              label,
              style: ctText(size: ctFontXs, color: ctInk3, height: 1.4),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              value,
              style: ctText(
                size: ctFontSm,
                weight: FontWeight.w600,
                color: ctInk,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _stat(String label, String value) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '$label ',
          style: ctText(size: ctFontXs, color: ctInk3),
        ),
        Text(
          value,
          style: ctText(size: ctFontSm, weight: FontWeight.w600),
        ),
      ],
    );
  }

  String _elapsed(int? milliseconds) =>
      '${((milliseconds ?? 0) / 1000).toStringAsFixed(2)}s';

  Widget _card({Key? key, required Widget child}) {
    return Container(
      key: key,
      width: double.infinity,
      padding: const EdgeInsets.all(ctGapMd),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: child,
    );
  }

  Widget _banner({
    Key? key,
    required String text,
    required Color fg,
    required Color bg,
  }) {
    return Container(
      key: key,
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapMd,
        vertical: ctGapSm,
      ),
      decoration: BoxDecoration(color: bg, borderRadius: ctRadiusSmAll),
      child: Text(
        text,
        style: ctText(size: ctFontSm, color: fg),
      ),
    );
  }
}
