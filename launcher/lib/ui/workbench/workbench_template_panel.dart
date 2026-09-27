import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/template_service.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';
import 'workbench_models.dart';

/// Excel 模板的预检与显式生成入口（native-flutter-workbench 任务 3.6）。
///
/// 只作用于 Table：Record/Enum 没有独立 Excel 模板，界面直接说明而不是放个假按钮。
/// 生成必须先看预检结论，内核说不行就不给点；生成成功后立刻再问一次状态。
class WorkbenchTemplatePanel extends StatefulWidget {
  const WorkbenchTemplatePanel({
    super.key,
    required this.service,
    required this.resource,
    this.blockReason,
  });

  final TemplateService service;
  final WorkbenchResource? resource;

  /// 写入口不可用的原因（内核未就绪/协议不兼容等）。
  final String? blockReason;

  @override
  State<WorkbenchTemplatePanel> createState() => _WorkbenchTemplatePanelState();
}

class _WorkbenchTemplatePanelState extends State<WorkbenchTemplatePanel> {
  @override
  void initState() {
    super.initState();
    widget.service.addListener(_changed);
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void didUpdateWidget(WorkbenchTemplatePanel old) {
    super.didUpdateWidget(old);
    if (old.resource?.name != widget.resource?.name) {
      widget.service.select(widget.resource?.name);
    }
  }

  @override
  void dispose() {
    widget.service.removeListener(_changed);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final resource = widget.resource;
    if (resource == null) return const SizedBox.shrink();
    if (resource.kind != WorkbenchResourceKind.table) {
      return Container(
        key: const ValueKey('wb.templateNotTable'),
        width: double.infinity,
        margin: const EdgeInsets.all(ctGapMd),
        padding: const EdgeInsets.all(ctGapMd),
        decoration: BoxDecoration(
          color: ctSurface2,
          borderRadius: ctRadiusMdAll,
        ),
        child: Text(
          '${resource.kind.label}「${resource.name}」没有独立 Excel 模板：'
          '模板只作用于 Table 的工作簿布局。',
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
      );
    }
    final service = widget.service;
    final plan = service.plan;
    final blocked = widget.blockReason != null;
    return Container(
      key: const ValueKey('wb.templatePanel'),
      width: double.infinity,
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: ctBorder)),
      ),
      padding: const EdgeInsets.fromLTRB(ctGapMd, ctGapSm, ctGapMd, ctGapSm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final title = Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.grid_on_outlined, size: 15, color: ctInk3),
                  const SizedBox(width: ctGapXs),
                  Text(
                    'Excel 模板',
                    style: ctText(size: ctFontSm, weight: FontWeight.w600),
                  ),
                  const SizedBox(width: ctGapSm),
                  _badge(service, blocked: blocked),
                ],
              );
              final actions = Wrap(
                spacing: ctGapSm,
                runSpacing: ctGapXs,
                children: [
                  CtButton.ghost(
                    '迁移预检',
                    key: const ValueKey('wb.templatePlan'),
                    onPressed: service.busy || blocked
                        ? null
                        : () => service.runPlan(resource.name),
                  ),
                  CtButton.accent(
                    service.busy ? '处理中…' : '生成模板',
                    key: const ValueKey('wb.templateGenerate'),
                    onPressed: service.canGenerate && !blocked
                        ? service.runGenerate
                        : null,
                  ),
                ],
              );
              final hint = plan == null && !blocked && service.error == null
                  ? Tooltip(
                      message: '生成按钮保持禁用；预检只读，不改任何文件。',
                      child: Text(
                        service.busy ? '正在预检…' : '生成前需预检 · 预检只读',
                        key: const ValueKey('wb.templateHint'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: ctText(size: ctFontXs, color: ctInk3),
                      ),
                    )
                  : null;
              if (constraints.maxWidth < 680) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        title,
                        if (hint != null) ...[
                          const Spacer(),
                          Flexible(child: hint),
                        ],
                      ],
                    ),
                    const SizedBox(height: ctGapSm),
                    Align(alignment: Alignment.centerRight, child: actions),
                  ],
                );
              }
              return Row(
                children: [
                  title,
                  if (hint != null) ...[
                    const SizedBox(width: ctGapLg),
                    Flexible(child: hint),
                  ],
                  const Spacer(),
                  actions,
                ],
              );
            },
          ),
          if (blocked) _line(widget.blockReason!, CtBadgeTone.warn),
          if (service.error != null) _line(service.error!, CtBadgeTone.danger),
          if (plan != null) ...[
            for (final action in plan.actions)
              _line('将执行：$action', CtBadgeTone.info),
            for (final issue in plan.problems) _issue(issue, danger: true),
            for (final issue in plan.warnings) _issue(issue, danger: false),
          ],
          if (service.generated != null)
            _line(
              '已生成：迁移 ${service.generated!.migratedRows} 行'
              '（模板状态已重新预检）',
              CtBadgeTone.ok,
            ),
        ],
      ),
    );
  }

  Widget _badge(TemplateService service, {required bool blocked}) {
    final plan = service.plan;
    if (blocked) {
      return const CtStatusBadge(
        label: '不可操作',
        tone: CtBadgeTone.warn,
        dot: false,
      );
    }
    if (service.busy) {
      return const CtStatusBadge(
        label: '处理中',
        tone: CtBadgeTone.busy,
        dot: false,
      );
    }
    if (plan == null) {
      return const CtStatusBadge(
        label: '未预检',
        tone: CtBadgeTone.neutral,
        dot: false,
      );
    }
    return plan.canGenerate
        ? const CtStatusBadge(label: '可生成', tone: CtBadgeTone.ok, dot: false)
        : const CtStatusBadge(
            label: '被阻塞',
            tone: CtBadgeTone.danger,
            dot: false,
          );
  }

  Widget _line(String text, CtBadgeTone tone) => Padding(
    padding: const EdgeInsets.only(top: ctGapXs),
    child: Text(
      text,
      style: ctText(
        size: ctFontSm,
        color: switch (tone) {
          CtBadgeTone.danger => ctDanger,
          CtBadgeTone.warn => ctWarn,
          CtBadgeTone.ok => ctAccentHover,
          _ => ctInk2,
        },
      ),
    ),
  );

  Widget _issue(Issue issue, {required bool danger}) => Padding(
    padding: const EdgeInsets.only(top: 2),
    child: Text(
      issue.resource == null
          ? issue.message
          : '${issue.message}（${issue.resource}）',
      key: ValueKey('wb.templateIssue.${issue.message}'),
      style: ctText(size: ctFontXs, color: danger ? ctDanger : ctWarn),
    ),
  );
}
