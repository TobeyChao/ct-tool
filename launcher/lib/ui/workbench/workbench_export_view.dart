import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/export_runner.dart';
import '../../state/validate_runner.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';

/// 导出模块（native-flutter-workbench 任务 4.4/4.6）。
///
/// 过滤条件一比一映射内核 `export` 参数：`table`/`lang` 是可选过滤（都不填即全量），
/// `all` 是**强制重建**（绕过解析/校验/生成缓存），不是「全部表」。
/// 导出不带部署：「独立部署」是另一个按钮、另一条 `deploy` 请求。
class WorkbenchExportView extends StatefulWidget {
  const WorkbenchExportView({
    super.key,
    required this.runner,
    this.validate,
    required this.tables,
    this.languages = const [],
    this.blockReason,
    this.onLocateIssue,
  });

  final ExportRunner runner;

  /// 只读校验运行器（任务 5.4 前置）：为 null 时不显示校验入口。
  final ValidateRunner? validate;

  /// 可过滤的表名（来自内核 `resources.list` 的 table 类资源）。
  final List<String> tables;

  /// 可选语言码（来自 `i18n.status`）；为空时退回自由输入。
  final List<String> languages;

  /// 写入口不可用的原因（内核未就绪/协议不兼容/能力缺失）；null 表示可用。
  final String? blockReason;

  /// 点击问题行的「定位」：交由壳层切资源/滚动到行。
  final void Function(Issue issue)? onLocateIssue;

  @override
  State<WorkbenchExportView> createState() => _WorkbenchExportViewState();
}

class _WorkbenchExportViewState extends State<WorkbenchExportView> {
  late final TextEditingController _langText;

  @override
  void initState() {
    super.initState();
    _langText = TextEditingController(text: widget.runner.lang ?? '');
    widget.runner.addListener(_onChanged);
    widget.validate?.addListener(_onChanged);
  }

  @override
  void didUpdateWidget(covariant WorkbenchExportView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.runner, widget.runner)) {
      oldWidget.runner.removeListener(_onChanged);
      widget.runner.addListener(_onChanged);
    }
    if (!identical(oldWidget.validate, widget.validate)) {
      oldWidget.validate?.removeListener(_onChanged);
      widget.validate?.addListener(_onChanged);
    }
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.runner.removeListener(_onChanged);
    widget.validate?.removeListener(_onChanged);
    _langText.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final runner = widget.runner;
    return SingleChildScrollView(
      key: const ValueKey('wb.exportView'),
      padding: const EdgeInsets.all(ctGapXl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('导出', style: ctPageTitleStyle),
              const SizedBox(width: ctGapMd),
              _phaseBadge(runner.phase),
            ],
          ),
          const SizedBox(height: ctGapXs),
          Text(
            '导出只做本地发布与记账，不会顺带部署；部署用下面的「独立部署」。',
            style: ctText(size: ctFontSm, color: ctInk3),
          ),
          const SizedBox(height: ctGapLg),
          _filters(runner),
          const SizedBox(height: ctGapMd),
          _actions(runner),
          const SizedBox(height: ctGapMd),
          _validation(),
          const SizedBox(height: ctGapMd),
          _hints(runner),
          const SizedBox(height: ctGapMd),
          _progress(runner),
          const SizedBox(height: ctGapMd),
          _result(runner),
          const SizedBox(height: ctGapMd),
          _issues(runner),
          const SizedBox(height: ctGapMd),
          _runLog(runner),
        ],
      ),
    );
  }

  Widget _phaseBadge(RunnerPhase phase, {String key = 'wb.exportPhase'}) {
    final tone = switch (phase) {
      RunnerPhase.running => CtBadgeTone.busy,
      RunnerPhase.succeeded => CtBadgeTone.ok,
      RunnerPhase.cancelled => CtBadgeTone.neutral,
      RunnerPhase.failed => CtBadgeTone.danger,
      RunnerPhase.unknown => CtBadgeTone.warn,
      RunnerPhase.idle => CtBadgeTone.info,
    };
    return CtStatusBadge(
      key: ValueKey(key),
      label: phase.label,
      tone: tone,
      dot: false,
    );
  }

  Widget _filters(ExportRunner runner) {
    return _card(
      key: const ValueKey('wb.exportFilters'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '过滤条件',
            style: ctText(size: ctFontSm, weight: FontWeight.w600),
          ),
          const SizedBox(height: ctGapSm),
          Wrap(
            spacing: ctGapLg,
            runSpacing: ctGapSm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _labelled('表', 180, _tableDropdown(runner)),
              _labelled('语言', 180, _langControl(runner)),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Checkbox(
                    key: const ValueKey('wb.exportAll'),
                    visualDensity: VisualDensity.compact,
                    value: runner.all,
                    onChanged: runner.running
                        ? null
                        : (v) => setState(() => runner.all = v ?? false),
                  ),
                  Text(
                    '强制重建（绕过缓存）',
                    style: ctText(size: ctFontSm, color: ctInk2),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _labelled(String label, double width, Widget child) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
        const SizedBox(width: ctGapSm),
        SizedBox(width: width, child: child),
      ],
    );
  }

  Widget _tableDropdown(ExportRunner runner) {
    final value = runner.table ?? '';
    final items = <DropdownMenuItem<String>>[
      const DropdownMenuItem(value: '', child: Text('（不限定）')),
      for (final name in widget.tables)
        DropdownMenuItem(value: name, child: Text(name)),
    ];
    return DropdownButton<String>(
      key: const ValueKey('wb.exportTable'),
      isExpanded: true,
      value: items.any((e) => e.value == value) ? value : '',
      items: items,
      onChanged: runner.running
          ? null
          : (v) => setState(
              () => runner.table = (v == null || v.isEmpty) ? null : v,
            ),
    );
  }

  Widget _langControl(ExportRunner runner) {
    if (widget.languages.isEmpty) {
      return TextField(
        key: const ValueKey('wb.exportLangText'),
        controller: _langText,
        enabled: !runner.running,
        style: ctText(size: ctFontSm),
        decoration: const InputDecoration(isDense: true, hintText: '语言码，如 en'),
        onChanged: (v) => runner.lang = v.trim().isEmpty ? null : v.trim(),
      );
    }
    final value = runner.lang ?? '';
    final items = <DropdownMenuItem<String>>[
      const DropdownMenuItem(value: '', child: Text('（全部语言）')),
      for (final lang in widget.languages)
        DropdownMenuItem(value: lang, child: Text(lang)),
    ];
    return DropdownButton<String>(
      key: const ValueKey('wb.exportLang'),
      isExpanded: true,
      value: items.any((e) => e.value == value) ? value : '',
      items: items,
      onChanged: runner.running
          ? null
          : (v) => setState(
              () => runner.lang = (v == null || v.isEmpty) ? null : v,
            ),
    );
  }

  Widget _actions(ExportRunner runner) {
    final blocked = widget.blockReason != null;
    return Row(
      children: [
        CtButton.accent(
          runner.running ? '导出中…' : '导出',
          key: const ValueKey('wb.exportRun'),
          onPressed: blocked || runner.running
              ? null
              : () => runner.startExport(),
        ),
        const SizedBox(width: ctGapSm),
        CtButton.ghost(
          '独立部署',
          key: const ValueKey('wb.deployRun'),
          onPressed: blocked || runner.running
              ? null
              : () => runner.startDeploy(),
        ),
        const SizedBox(width: ctGapSm),
        CtButton.ghost(
          '取消',
          key: const ValueKey('wb.exportCancel'),
          onPressed: runner.running && runner.runningRequestId != null
              ? () => runner.cancel()
              : null,
        ),
        const SizedBox(width: ctGapMd),
        if (runner.running && runner.runningRequestId == null)
          Text(
            '取消要等内核回首个事件（带 requestId）后可用',
            style: ctText(size: ctFontXs, color: ctInk3),
          ),
      ],
    );
  }

  /// 校验入口与结果：按钮、内核摘要、问题定位（逐条取自 `validate` 回包）。
  Widget _validation() {
    final v = widget.validate;
    if (v == null) return const SizedBox.shrink();
    final runner = widget.runner;
    final blocked = widget.blockReason != null;
    final issues = v.last?.issues ?? const <Issue>[];
    return Column(
      key: const ValueKey('wb.validatePanel'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            CtButton.ghost(
              v.busy ? '校验中…' : '校验',
              key: const ValueKey('wb.validateRun'),
              onPressed: v.busy || runner.running || blocked
                  ? null
                  : () => v.run(),
            ),
            const SizedBox(width: ctGapSm),
            Flexible(
              child: Text(
                v.summaryLabel,
                key: const ValueKey('wb.validateResult'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: ctText(
                  size: ctFontSm,
                  color: v.error != null
                      ? ctDanger
                      : (v.last?.ok ?? false)
                      ? ctAccent
                      : ctInk2,
                ),
              ),
            ),
          ],
        ),
        if (runner.running)
          Text(
            '写任务进行中：校验先禁用，避免与导出抢工作区锁。',
            key: const ValueKey('wb.validateQueued'),
            style: ctText(size: ctFontXs, color: ctInk3),
          ),
        for (final entry in issues.take(5).indexed)
          Row(
            key: ValueKey('wb.validateIssue.${entry.$1}'),
            children: [
              Expanded(
                child: Text(
                  '${entry.$2.resource ?? ''} ${entry.$2.message}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: ctText(size: ctFontXs, color: ctDanger),
                ),
              ),
              if (widget.onLocateIssue != null &&
                  (entry.$2.resource ?? '').isNotEmpty)
                TextButton(
                  onPressed: () => widget.onLocateIssue!(entry.$2),
                  child: const Text('定位'),
                ),
            ],
          ),
        if (issues.length > 5)
          Text(
            '其余 ${issues.length - 5} 个问题见「历史」模块的任务问题列表。',
            key: const ValueKey('wb.validateMore'),
            style: ctText(size: ctFontXs, color: ctInk3),
          ),
      ],
    );
  }

  Widget _hints(ExportRunner runner) {
    final blocks = <Widget>[];
    if (widget.blockReason != null) {
      blocks.add(
        _banner(
          key: const ValueKey('wb.exportBlocked'),
          text: widget.blockReason!,
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
              '请先在「历史/任务」确认结果，再决定是否重试。',
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
    if (blocks.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final b in blocks)
          Padding(
            padding: const EdgeInsets.only(bottom: ctGapSm),
            child: b,
          ),
      ],
    );
  }

  Widget _progress(ExportRunner runner) {
    final event = runner.progress;
    if (event == null) return const SizedBox.shrink();
    final ratio = event.total > 0 ? event.done / event.total : null;
    return _card(
      key: const ValueKey('wb.exportProgress'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '${event.stage} ${event.done}/${event.total}',
                style: ctText(size: ctFontSm, weight: FontWeight.w600),
              ),
              const Spacer(),
              Text(
                '请求 #${event.requestId}',
                style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
              ),
            ],
          ),
          const SizedBox(height: ctGapSm),
          if (ratio == null)
            const LinearProgressIndicator(minHeight: 4)
          else
            LinearProgressIndicator(value: ratio, minHeight: 4),
        ],
      ),
    );
  }

  Widget _result(ExportRunner runner) {
    final last = runner.last;
    if (last == null) return const SizedBox.shrink();
    final result = last.result;
    final deploy = last.deploy;
    return _card(
      key: const ValueKey('wb.exportResult'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                last.kind == Methods.deploy ? '部署结果' : '导出结果',
                style: ctText(size: ctFontSm, weight: FontWeight.w600),
              ),
              const SizedBox(width: ctGapSm),
              _phaseBadge(last.phase, key: 'wb.resultPhase'),
            ],
          ),
          const SizedBox(height: ctGapSm),
          Wrap(
            spacing: ctGapLg,
            runSpacing: ctGapXs,
            children: [
              if (result != null) ...[
                _stat('表', '${result.tables}'),
                _stat('耗时', '${result.durationMs}ms'),
                _stat(
                  '缓存命中',
                  result.cache == null
                      ? '不适用'
                      : '${result.cache!.hits} / ${result.cache!.misses}',
                ),
              ],
              if (deploy != null) ...[
                _stat('同步文件', '${deploy.synced}'),
                _stat('是否已有最新', deploy.unchanged ? '是（未写入）' : '否'),
              ],
            ],
          ),
          if (last.message != null && result == null)
            Padding(
              padding: const EdgeInsets.only(top: ctGapSm),
              child: Text(last.message!, style: ctText(size: ctFontSm)),
            ),
          if (result != null && result.stages.isNotEmpty) ...[
            const SizedBox(height: ctGapSm),
            for (final stage in result.stages)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Row(
                  children: [
                    SizedBox(
                      width: 160,
                      child: Text(
                        stage.name,
                        style: ctMono.copyWith(fontSize: ctFontXs),
                      ),
                    ),
                    Text(
                      '${stage.elapsedMs}ms',
                      style: ctText(size: ctFontXs, color: ctInk2),
                    ),
                  ],
                ),
              ),
          ],
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

  Widget _issues(ExportRunner runner) {
    final issues = <Issue>[
      for (final event in runner.liveIssues) event.issue,
      ...runner.issues,
    ];
    if (issues.isEmpty) return const SizedBox.shrink();
    return _card(
      key: const ValueKey('wb.exportIssues'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '问题 ${issues.length} 条',
            style: ctText(size: ctFontSm, weight: FontWeight.w600),
          ),
          const SizedBox(height: ctGapSm),
          for (var i = 0; i < issues.length; i++) _issueRow(issues[i], i),
        ],
      ),
    );
  }

  Widget _issueRow(Issue issue, int index) {
    final where = <String>[
      if (issue.resource != null) issue.resource!,
      if (issue.fieldPath != null) issue.fieldPath!,
      if (issue.excelRow != null) '第 ${issue.excelRow} 行',
      if (issue.file != null) issue.file!,
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: ctGapXs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${issue.code}：${issue.message}',
                  key: ValueKey('wb.exportIssue.$index'),
                  style: ctText(size: ctFontSm, color: ctDanger),
                ),
                if (where.isNotEmpty)
                  Text(
                    where,
                    style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
                  ),
              ],
            ),
          ),
          CtButton.ghost(
            '定位',
            key: ValueKey('wb.exportLocate.$index'),
            onPressed: widget.onLocateIssue == null || issue.resource == null
                ? null
                : () => widget.onLocateIssue!(issue),
          ),
        ],
      ),
    );
  }

  Widget _runLog(ExportRunner runner) {
    if (runner.logLines.isEmpty) return const SizedBox.shrink();
    return _card(
      key: const ValueKey('wb.exportLog'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '本次运行（最多 ${ExportRunner.logHistory} 行）',
            style: ctText(size: ctFontSm, weight: FontWeight.w600),
          ),
          const SizedBox(height: ctGapXs),
          for (final line in runner.logLines)
            Text(
              line,
              style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk2),
            ),
        ],
      ),
    );
  }

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
