import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../state/workbench_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import 'workbench_models.dart';

/// 跨模块全局草稿条（native-flutter-workbench 任务 4.9；2026-09-21 按 web 收成 4 个动作）。
///
/// 与 web 的 `ct-draftbar` 同口径：一个状态点 + 一句可点摘要（点开「步骤 / 净差异」弹层）
/// + 撤销 / 重做 / 放弃草稿 / 保存变更；**没有草稿、没有撤销历史时整条不占位**。
/// 数字全部来自内核：净变化资源数取自 `schema.candidate` 的 netDiff，候选没算过时直说未计算。
class WorkbenchDraftBar extends StatefulWidget {
  const WorkbenchDraftBar({
    super.key,
    required this.data,
    required this.repo,
    this.onSave,
    this.onQuickOpen,
  });

  final WorkbenchData data;
  final WorkbenchRepository? repo;
  final VoidCallback? onSave;
  final VoidCallback? onQuickOpen;

  @override
  State<WorkbenchDraftBar> createState() => _WorkbenchDraftBarState();
}

class _WorkbenchDraftBarState extends State<WorkbenchDraftBar> {
  bool _candidateCheckScheduled = false;
  String? _lastCandidateAttemptKey;

  @override
  void didUpdateWidget(covariant WorkbenchDraftBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.repo, widget.repo)) {
      _lastCandidateAttemptKey = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    _scheduleCandidateCheck();
    return _buildBar(context);
  }

  /// 编辑只清候选，必须由这里立即向内核重算；否则「保存变更」会一直禁用，
  /// 用户被迫先找侧栏里的「算候选」才能保存。
  void _scheduleCandidateCheck() {
    if (_candidateCheckScheduled) return;
    _candidateCheckScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _candidateCheckScheduled = false;
      if (mounted) _requestCandidateIfNeeded();
    });
  }

  void _requestCandidateIfNeeded() {
    final repo = widget.repo;
    if (repo == null) return;
    if (repo.candidate != null) {
      _lastCandidateAttemptKey = null;
      return;
    }
    if ((!repo.hasDraft && !repo.canUndo && !repo.canRedo) ||
        repo.candidateBusy ||
        repo.editingFrozen ||
        repo.loading) {
      return;
    }
    final key = _candidateAttemptKey(repo);
    if (key == _lastCandidateAttemptKey) return;
    _lastCandidateAttemptKey = key;
    repo.requestCandidate();
  }

  /// 同一草稿只自动尝试一次；失败后保留错误，用户编辑或手动重试才会再请求。
  String _candidateAttemptKey(WorkbenchRepository repo) {
    final commands = repo.commands
        .map((command) => '${command.kind}:${command.payload}')
        .join('|');
    return '${repo.workspaceRoot}|${repo.schemaBaseline}|'
        '${repo.draftCursor}|$commands';
  }

  Widget _buildBar(BuildContext context) {
    final draft = widget.repo;
    if (draft == null) {
      return const SizedBox.shrink(key: ValueKey('wb.draftBar'));
    }
    final found = draft.candidate;
    final diff = found?.netDiff;
    final changed = diff == null
        ? 0
        : diff.added.length + diff.changed.length + diff.removed.length;
    final steps = draft.draftCount;
    if (changed == 0 &&
        steps == 0 &&
        !draft.canUndo &&
        !draft.canRedo &&
        !draft.candidateBusy &&
        draft.draftPersisted &&
        !draft.editingFrozen) {
      return const SizedBox.shrink(key: ValueKey('wb.draftBar'));
    }
    final candidatePending =
        found == null && (draft.hasDraft || draft.canUndo || draft.canRedo);
    final notes = <String>[
      if (!draft.draftPersisted) '草稿未落盘',
      if ((found?.problems.isNotEmpty ?? false) ||
          (found == null && draft.candidateProblems.isNotEmpty))
        '存在阻塞项，无法保存',
      if (found == null && draft.draftError != null) '候选失败：${draft.draftError}',
      if (draft.editingFrozen) '保存中…',
      if (draft.busy && !draft.candidateBusy && !draft.saving) '工作区忙，稍后重试',
    ];
    final summary =
        '${draft.candidateBusy ? '正在计算未保存修改…' : (candidatePending ? '未保存修改（净差异未计算）' : (changed == 0 ? '无未保存修改' : '$changed 个资源有未保存修改'))}'
        '${notes.isEmpty ? '' : ' · ${notes.join(' · ')}'}'
        '${steps == 0 ? '' : ' · 草稿 $steps 步 · ${draft.draftPersistLabel}'}';
    return Container(
      key: const ValueKey('wb.draftBar'),
      width: double.infinity,
      height: ctRowMd,
      padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
      decoration: const BoxDecoration(
        color: ctSurface2,
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          // 窄内容区或高缩放时，文字按钮会吞掉摘要空间；保留图标与 tooltip，
          // 让状态摘要始终可读（与 ZCode 的紧凑操作栏同一取舍）。
          final compact = constraints.maxWidth < 960;
          return Row(
            children: [
              Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: (found != null && found.problems.isNotEmpty)
                      ? ctDanger
                      : (changed > 0 || steps > 0 || draft.candidateBusy)
                      ? ctWarn
                      : ctAccent,
                ),
              ),
              const SizedBox(width: ctGapSm),
              Expanded(
                child: InkWell(
                  key: const ValueKey('wb.draftSummaryTap'),
                  onTap: () => showWorkbenchDraftSheet(
                    context,
                    data: widget.data,
                    repo: draft,
                  ),
                  child: Text(
                    summary,
                    key: const ValueKey('wb.draftSummary'),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: ctText(size: ctFontSm, color: ctInk2),
                  ),
                ),
              ),
              _icon(
                keyName: 'wb.draftQuickOpen',
                icon: Icons.search,
                tooltip: 'Quick Open（Ctrl/Cmd+P）：按名字跳到资源',
                onPressed: widget.onQuickOpen,
              ),
              if (compact) ...[
                _icon(
                  keyName: 'wb.draftUndo',
                  icon: Icons.undo,
                  tooltip: '撤销一步草稿（Ctrl/Cmd+Z）',
                  onPressed: !draft.canUndo ? null : draft.undoDraft,
                ),
                _icon(
                  keyName: 'wb.draftRedo',
                  icon: Icons.redo,
                  tooltip: '重做一步草稿（Ctrl/Cmd+Shift+Z）',
                  onPressed: !draft.canRedo ? null : draft.redoDraft,
                ),
                _icon(
                  keyName: 'wb.draftDiscard',
                  icon: Icons.delete_sweep_outlined,
                  tooltip: '丢弃全部草稿命令（需确认，不改工作区文件）',
                  onPressed: !draft.hasDraft
                      ? null
                      : () => confirmWorkbenchDiscard(context, draft),
                ),
                _icon(
                  keyName: 'wb.draftSave',
                  icon: Icons.save_outlined,
                  tooltip: '保存草稿为 YAML（Ctrl/Cmd+S）：仅改 schema 文件',
                  onPressed: !draft.canSave ? null : widget.onSave,
                  accent: true,
                ),
              ] else ...[
                _button(
                  keyName: 'wb.draftUndo',
                  label: '撤销',
                  tooltip: '撤销一步草稿（Ctrl/Cmd+Z）',
                  onPressed: !draft.canUndo ? null : draft.undoDraft,
                ),
                _button(
                  keyName: 'wb.draftRedo',
                  label: '重做',
                  tooltip: '重做一步草稿（Ctrl/Cmd+Shift+Z）',
                  onPressed: !draft.canRedo ? null : draft.redoDraft,
                ),
                _button(
                  keyName: 'wb.draftDiscard',
                  label: '放弃草稿',
                  tooltip: '丢弃全部草稿命令（需确认，不改工作区文件）',
                  onPressed: !draft.hasDraft
                      ? null
                      : () => confirmWorkbenchDiscard(context, draft),
                ),
                _button(
                  keyName: 'wb.draftSave',
                  label: '保存变更',
                  tooltip: '保存草稿为 YAML（Ctrl/Cmd+S）：仅改 schema 文件',
                  accent: true,
                  onPressed: !draft.canSave ? null : widget.onSave,
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _icon({
    required String keyName,
    required IconData icon,
    required String tooltip,
    VoidCallback? onPressed,
    bool accent = false,
  }) => IconButton(
    key: ValueKey(keyName),
    icon: Icon(icon, size: 17),
    tooltip: tooltip,
    onPressed: onPressed,
    splashRadius: 16,
    padding: EdgeInsets.zero,
    constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
    color: accent && onPressed != null ? ctAccent : ctInk2,
  );

  Widget _button({
    required String keyName,
    required String label,
    required String tooltip,
    VoidCallback? onPressed,
    bool accent = false,
  }) => Tooltip(
    message: tooltip,
    child: TextButton(
      key: ValueKey(keyName),
      onPressed: onPressed,
      style: TextButton.styleFrom(
        minimumSize: const Size(0, 40),
        padding: const EdgeInsets.symmetric(horizontal: ctGapSm),
        foregroundColor: accent && onPressed != null
            ? Colors.white
            : (onPressed == null ? ctInk3 : ctInk),
        backgroundColor: accent && onPressed != null
            ? ctAccent
            : Colors.transparent,
      ),
      child: Text(
        label,
        style: ctText(
          size: ctFontSm,
          weight: accent ? FontWeight.w600 : FontWeight.w400,
        ),
      ),
    ),
  );
}

/// 「步骤 / 净差异」弹层：web 版把这两件事收在同一句摘要后面，这里同口径。
Future<void> showWorkbenchDraftSheet(
  BuildContext context, {
  required WorkbenchData data,
  required WorkbenchRepository repo,
}) => showDialog<void>(
  context: context,
  builder: (dialogContext) => DefaultTabController(
    length: 2,
    child: AlertDialog(
      title: const Text('未保存修改'),
      content: SizedBox(
        width: 620,
        height: 420,
        child: Column(
          children: [
            const TabBar(
              key: ValueKey('wb.draftSheet'),
              tabs: [
                Tab(text: '步骤'),
                Tab(text: '净差异'),
              ],
            ),
            Expanded(
              child: TabBarView(
                children: [
                  _DraftStepsPane(repo: repo),
                  _NetDiffPane(data: data, repo: repo),
                ],
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('关闭'),
        ),
      ],
    ),
  ),
);

class _DraftStepsPane extends StatefulWidget {
  const _DraftStepsPane({required this.repo});

  final WorkbenchRepository repo;

  @override
  State<_DraftStepsPane> createState() => _DraftStepsPaneState();
}

class _DraftStepsPaneState extends State<_DraftStepsPane> {
  @override
  void initState() {
    super.initState();
    widget.repo.addListener(_changed);
  }

  @override
  void dispose() {
    widget.repo.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final steps = widget.repo.draftOutline;
    final cursor = widget.repo.draftCursor;
    return ListView(
      padding: const EdgeInsets.all(ctGapMd),
      children: [
        Text(
          '游标 $cursor/${steps.length}：只有游标之前的命令会送给内核算候选。',
          key: const ValueKey('wb.draftSteps.cursor'),
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
        TextButton(
          key: const ValueKey('wb.draftSteps.baseline'),
          onPressed: cursor == 0 ? null : () => widget.repo.undoTo(0),
          child: const Text('回到基线（全部步骤不生效）'),
        ),
        for (final (step, label, applied) in steps)
          Row(
            key: ValueKey('wb.draftStep.$step'),
            children: [
              Icon(
                applied ? Icons.check_circle : Icons.radio_button_unchecked,
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
                    : () => widget.repo.undoTo(step),
                child: const Text('停在此处'),
              ),
            ],
          ),
      ],
    );
  }
}

class _NetDiffPane extends StatefulWidget {
  const _NetDiffPane({required this.data, required this.repo});

  final WorkbenchData data;
  final WorkbenchRepository repo;

  @override
  State<_NetDiffPane> createState() => _NetDiffPaneState();
}

class _NetDiffPaneState extends State<_NetDiffPane> {
  @override
  void initState() {
    super.initState();
    widget.repo.addListener(_changed);
    if (widget.repo.candidate == null && !widget.repo.candidateBusy) {
      // 必须等这一帧建完再发请求：initState 里直接请求会让内核通知在 build 期间
      // 回调 setState（实测抛 markNeedsBuild() called during build）。
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => _requestCandidateOnce(),
      );
    }
  }

  /// 必须等这一帧建完再发请求：initState 里直接请求会让内核通知在 build 期间回调 setState。
  void _requestCandidateOnce() {
    if (!mounted || widget.repo.candidate != null) {
      return;
    }
    widget.repo.requestCandidate();
  }

  @override
  void dispose() {
    widget.repo.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final found = widget.repo.candidate;
    final paths = {for (final r in widget.data.resources) r.name: r.path};
    return ListView(
      padding: const EdgeInsets.all(ctGapMd),
      children: [
        Text(
          widget.repo.draftError ??
              (found == null
                  ? (widget.repo.candidateBusy ? '内核正在计算候选…' : '尚未取得候选')
                  : 'candidateHash ${found.candidateHash}'),
          key: const ValueKey('wb.candidateHash'),
          style: ctMono.copyWith(fontSize: ctFontSm),
        ),
        const SizedBox(height: ctGapMd),
        if (found != null) ...[
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
    );
  }
}

/// 放弃草稿必须二次确认：说清楚丢的是内存草稿与用户目录草稿文件，不碰工作区 YAML。
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
            '      ${field.change} '
            '${field.oldName == null ? field.name : '${field.oldName} → ${field.name}'}'
            '${field.details.isEmpty ? '' : '：${field.details.join('，')}'}',
            key: ValueKey('$keyName.field.${ref.name}.${field.name}'),
            style: ctText(size: ctFontXs, color: ctWarn),
          ),
      ],
    ],
  );
}
