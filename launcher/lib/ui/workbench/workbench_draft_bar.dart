import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/workbench_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';
import 'workbench_models.dart';

/// 跨模块全局草稿条（native-flutter-workbench 任务 4.9）。
///
/// 一切数字都来自内核：草稿步数是本地命令日志的游标，净差异与阻塞问题来自
/// `schema.candidate`；候选没算过时直说"净差异未计算"，界面不自己推断 diff。
class WorkbenchDraftBar extends StatelessWidget {
  const WorkbenchDraftBar({
    super.key,
    required this.data,
    required this.repo,
    this.onSave,
    this.onQuickOpen,
    this.onHelp,
  });

  final WorkbenchData data;
  final WorkbenchRepository? repo;

  /// 保存成功后壳层还要刷新预览/给提示，所以由屏外回调接管。
  final VoidCallback? onSave;
  final VoidCallback? onQuickOpen;
  final VoidCallback? onHelp;

  @override
  Widget build(BuildContext context) {
    final draft = repo;
    final found = draft?.candidate;
    final diff = found?.netDiff;
    final summary = draft == null
        ? '样板数据：草稿条未接内核'
        : '草稿 ${draft.draftCount} 步 · '
              '${diff == null ? '净差异未计算' : '净差异 ${diff.added.length + diff.changed.length + diff.removed.length} 个资源'}'
              ' · ${draft.draftPersistLabel}';
    return Container(
      key: const ValueKey('wb.draftBar'),
      width: double.infinity,
      height: ctRowMd,
      padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        children: [
          const Icon(Icons.edit_note, size: 15, color: ctInk3),
          const SizedBox(width: ctGapSm),
          if (draft != null && draft.hasDraft)
            CtStatusBadge(
              label: '未保存',
              tone: found == null ? CtBadgeTone.info : CtBadgeTone.warn,
              dot: false,
            ),
          if (draft != null && draft.hasDraft) const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              summary,
              key: const ValueKey('wb.draftSummary'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
          ),
          _button(
            keyName: 'wb.draftQuickOpen',
            label: '跳转',
            tooltip: 'Quick Open（Ctrl/Cmd+P）：按名字跳到资源',
            onPressed: onQuickOpen,
          ),
          _button(
            keyName: 'wb.draftHistory',
            label: '步骤',
            tooltip: '草稿步骤明细，可逐步撤销到任意一步（Ctrl/Cmd+Z 逐步撤销）',
            onPressed: draft == null || draft.commands.isEmpty
                ? null
                : () => showWorkbenchDraftSteps(context, draft),
          ),
          _button(
            keyName: 'wb.draftDiff',
            label: '净差异',
            tooltip: '打开候选净差异（Ctrl/Cmd+Shift+D）',
            onPressed: draft == null
                ? null
                : () => showWorkbenchNetDiff(context, data: data, repo: draft),
          ),
          _button(
            keyName: 'wb.draftUndo',
            label: '撤销',
            tooltip: '撤销一步草稿（Ctrl/Cmd+Z）',
            onPressed: draft == null || !draft.canUndo ? null : draft.undoDraft,
          ),
          _button(
            keyName: 'wb.draftRedo',
            label: '重做',
            tooltip: '重做一步草稿（Ctrl/Cmd+Shift+Z）',
            onPressed: draft == null || !draft.canRedo ? null : draft.redoDraft,
          ),
          _button(
            keyName: 'wb.draftDiscard',
            label: '放弃',
            tooltip: '丢弃全部草稿命令（需确认，不改工作区文件）',
            onPressed: draft == null || !draft.hasDraft
                ? null
                : () => confirmWorkbenchDiscard(context, draft),
          ),
          _button(
            keyName: 'wb.draftHelp',
            label: '帮助',
            tooltip: '帮助与关于（F1）：版本、协议、业务范围与键位',
            onPressed: onHelp,
          ),
          _button(
            keyName: 'wb.draftSave',
            label: '保存',
            tooltip: '保存草稿为 YAML（Ctrl/Cmd+S）：仅改 schema 文件',
            onPressed: draft == null || !draft.canSave ? null : onSave,
          ),
        ],
      ),
    );
  }

  Widget _button({
    required String keyName,
    required String label,
    required String tooltip,
    VoidCallback? onPressed,
  }) => Tooltip(
    message: tooltip,
    child: TextButton(
      key: ValueKey(keyName),
      onPressed: onPressed,
      style: TextButton.styleFrom(
        minimumSize: const Size(0, ctRowSm),
        padding: const EdgeInsets.symmetric(horizontal: ctGapSm),
        foregroundColor: onPressed == null ? ctInk3 : ctInk,
      ),
      child: Text(label, style: ctText(size: ctFontSm)),
    ),
  );
}

/// 候选净差异对话框：内容逐条取自内核响应，含字段/枚举成员风险明细。
Future<void> showWorkbenchNetDiff(
  BuildContext context, {
  required WorkbenchData data,
  required WorkbenchRepository repo,
}) async {
  await repo.requestCandidate();
  if (!context.mounted) return;
  final found = repo.candidate;
  final error = repo.draftError;
  final paths = {for (final r in data.resources) r.name: r.path};
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('净差异（由内核候选计算）'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                error ??
                    (found == null
                        ? '尚未取得候选'
                        : 'candidateHash ${found.candidateHash}'),
                key: const ValueKey('wb.candidateHash'),
                style: ctMono.copyWith(fontSize: ctFontSm),
              ),
              const SizedBox(height: ctGapXs),
              Text(
                '基线 schemaRevision ${_short(repo.schemaBaseline)}（保存须同时匹配候选哈希）',
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
              if (found != null) ...[
                const SizedBox(height: ctGapMd),
                _group(
                  keyName: 'wb.diff.added',
                  title: '新增 ${found.netDiff.added.length}',
                  refs: found.netDiff.added,
                  paths: paths,
                ),
                _group(
                  keyName: 'wb.diff.changed',
                  title: '修改 ${found.netDiff.changed.length}',
                  refs: found.netDiff.changed,
                  paths: paths,
                ),
                _group(
                  keyName: 'wb.diff.removed',
                  title: '删除 ${found.netDiff.removed.length}',
                  refs: found.netDiff.removed,
                  paths: paths,
                ),
                const SizedBox(height: ctGapMd),
                Text(
                  '阻塞问题 ${found.problems.length}',
                  key: const ValueKey('wb.diff.problems'),
                  style: ctText(size: ctFontSm, color: ctDanger),
                ),
                for (final problem in found.problems)
                  Text('  ✗ ${problem.resource ?? ''} ${problem.message}'),
              ],
              const SizedBox(height: ctGapMd),
              Text(
                '说明：内核候选给的是资源级净差异（含字段与枚举成员的 change/oldName/ordinal 风险），'
                '候选 YAML 不落盘，因此这里不是逐行文本 diff；逐行对比请在保存前用编辑器 diff 工具比对 schema 源文件。',
                key: const ValueKey('wb.diff.scope'),
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('关闭'),
        ),
      ],
    ),
  );
}

/// 草稿步骤明细：每步一条命令，可把游标移到任意一步之后（逐字段撤销）。
Future<void> showWorkbenchDraftSteps(
  BuildContext context,
  WorkbenchRepository repo,
) async {
  final steps = repo.draftOutline;
  final cursor = repo.draftCursor;
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('草稿步骤'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '游标 $cursor/${steps.length}：只有游标之前的命令会送给内核算候选。',
                key: const ValueKey('wb.draftSteps.cursor'),
                style: ctText(size: ctFontSm, color: ctInk2),
              ),
              const SizedBox(height: ctGapSm),
              TextButton(
                key: const ValueKey('wb.draftSteps.baseline'),
                onPressed: cursor == 0
                    ? null
                    : () {
                        repo.undoTo(0);
                        Navigator.pop(dialogContext);
                      },
                child: const Text('回到基线（全部步骤不生效）'),
              ),
              for (final (step, label, applied) in steps)
                Row(
                  key: ValueKey('wb.draftStep.$step'),
                  children: [
                    Icon(
                      applied
                          ? Icons.check_circle
                          : Icons.radio_button_unchecked,
                      size: 15,
                      color: applied ? ctAccent : ctInk3,
                    ),
                    const SizedBox(width: ctGapSm),
                    Text(
                      '$step. ',
                      style: ctText(size: ctFontSm, color: ctInk3),
                    ),
                    Expanded(
                      child: Text(
                        label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: ctText(size: ctFontSm),
                      ),
                    ),
                    TextButton(
                      key: ValueKey('wb.draftSteps.stop.$step'),
                      onPressed: step == cursor
                          ? null
                          : () {
                              repo.undoTo(step);
                              Navigator.pop(dialogContext);
                            },
                      child: const Text('停在此处'),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('关闭'),
        ),
      ],
    ),
  );
}

/// 放弃草稿必须确认：说清楚丢的是内存草稿与用户目录草稿文件，不碰工作区 YAML。
Future<void> confirmWorkbenchDiscard(
  BuildContext context,
  WorkbenchRepository repo,
) async {
  final steps = repo.draftCount;
  final ok = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('放弃草稿？'),
      content: Text(
        '将丢弃 $steps 步未保存的草稿命令，并清掉用户目录里的草稿文件。'
        '工作区的 YAML、Excel、翻译表和导出产物都不会被改动。',
        key: const ValueKey('wb.draftDiscard.body'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext, false),
          child: const Text('取消'),
        ),
        TextButton(
          key: const ValueKey('wb.draftDiscard.confirm'),
          onPressed: () => Navigator.pop(dialogContext, true),
          style: TextButton.styleFrom(foregroundColor: ctDanger),
          child: const Text('确认丢弃'),
        ),
      ],
    ),
  );
  if (ok == true) repo.discardDraft();
}

Widget _group({
  required String keyName,
  required String title,
  required List<ResourceRef> refs,
  required Map<String, String> paths,
}) {
  const marks = {'added': '+', 'removed': '-', 'modified': '~', 'renamed': '~'};
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(title, key: ValueKey(keyName)),
      for (final ref in refs) ...[
        Text(
          '  ${marks[ref.change] ?? '~'} '
          '${ref.oldName == null ? '${ref.kind}:${ref.name}' : '${ref.kind}:${ref.oldName} → ${ref.kind}:${ref.name}'}'
          '  ${paths[ref.name] ?? '（当前清单里没有该文件）'}',
          style: ctMono.copyWith(fontSize: ctFontXs),
        ),
        for (final field in ref.fields)
          Text(
            '      ${field.change} ${field.oldName == null ? field.name : '${field.oldName} → ${field.name}'}'
            '${field.details.isEmpty ? '' : '：${field.details.join('，')}'}',
            key: ValueKey('$keyName.field.${ref.name}.${field.name}'),
            style: ctText(size: ctFontXs, color: ctWarn),
          ),
      ],
    ],
  );
}

String _short(String revision) =>
    revision.length <= 12 ? revision : '${revision.substring(0, 12)}…';
