import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/protocol/protocol.dart';
import '../../state/translation_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/search_picker.dart';
import '../widgets/status_badge.dart';

/// 翻译模块（native-flutter-workbench 任务 4.1–4.3）。
///
/// 表/语言/状态筛选与分页都由内核执行；译文失焦即单条 `i18n.save`；
/// 清理 orphan 先 dry-run 预检、再要用户显式确认才执行。
class WorkbenchI18nView extends StatefulWidget {
  const WorkbenchI18nView({
    super.key,
    required this.repo,
    required this.tables,
    this.busyElsewhere,
  });

  final TranslationRepository repo;

  /// 可翻译的表（含 i18n 字段的判定由内核给出，这里只列资源清单里的表）。
  final List<String> tables;

  /// 其它模块占用内核（导出/保存等）时提示用。
  final String? busyElsewhere;

  @override
  State<WorkbenchI18nView> createState() => _WorkbenchI18nViewState();
}

class _WorkbenchI18nViewState extends State<WorkbenchI18nView> {
  final Map<String, GlobalKey<_EditableCellState>> _cellKeys = {};

  GlobalKey<_EditableCellState> _cellKey(String key) =>
      _cellKeys.putIfAbsent(key, () => GlobalKey<_EditableCellState>());

  @override
  void initState() {
    super.initState();
    widget.repo.addListener(_changed);
    if (widget.repo.table.isEmpty && widget.tables.isNotEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.repo.selectTable(widget.tables.first);
      });
    }
  }

  void _changed() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    widget.repo.removeListener(_changed);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final repo = widget.repo;
    return LayoutBuilder(
      key: const ValueKey('wb.i18nView'),
      builder: (context, bounds) {
        final header = Padding(
          padding: const EdgeInsets.fromLTRB(
            ctGapLg,
            ctGapMd,
            ctGapLg,
            ctGapSm,
          ),
          child: CtPageHeader(
            title: '翻译',
            subtitle: '逐条校对译文；长文案可打开专注编辑。',
            trailing: _operationState(repo),
          ),
        );
        final controls = Padding(
          padding: const EdgeInsets.symmetric(horizontal: ctGapLg),
          child: _filters(repo),
        );
        final progress = Padding(
          padding: const EdgeInsets.symmetric(horizontal: ctGapLg),
          child: _progress(repo),
        );
        final notices = Padding(
          padding: const EdgeInsets.symmetric(horizontal: ctGapLg),
          child: _notices(repo),
        );
        final rows = Padding(
          padding: const EdgeInsets.fromLTRB(
            ctGapLg,
            ctGapSm,
            ctGapLg,
            ctGapLg,
          ),
          child: _table(repo),
        );
        if (bounds.maxHeight < 590) {
          // 高缩放/矮窗口时让整页可滚动，表格仍保持自己的有限高度。
          return SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                header,
                controls,
                progress,
                notices,
                SizedBox(height: 320, child: rows),
              ],
            ),
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            header,
            controls,
            progress,
            notices,
            Expanded(child: rows),
          ],
        );
      },
    );
  }

  Future<bool> _confirmDraftChange(TranslationRepository repo) async {
    if (!repo.draftDirty) return true;
    final action = await showDialog<_DraftAction>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        key: const ValueKey('wb.i18nDraftPrompt'),
        title: const Text('有未保存的译文'),
        content: Text('${repo.selectedKey ?? '当前条目'} 的修改尚未保存。'),
        actions: [
          CtButton.ghost(
            '取消',
            onPressed: () => Navigator.pop(dialogContext, _DraftAction.cancel),
          ),
          CtButton.ghost(
            '放弃修改',
            key: const ValueKey('wb.i18nDraftDiscard'),
            onPressed: () => Navigator.pop(dialogContext, _DraftAction.discard),
          ),
          CtButton.accent(
            '保存并继续',
            key: const ValueKey('wb.i18nDraftSave'),
            onPressed: () => Navigator.pop(dialogContext, _DraftAction.save),
          ),
        ],
      ),
    );
    if (!mounted) return false;
    switch (action) {
      case _DraftAction.save:
        return repo.saveDraft();
      case _DraftAction.discard:
        repo.discardDraft();
        return true;
      case _DraftAction.cancel:
      case null:
        return false;
    }
  }

  Future<bool> _commitInlineEdits(TranslationRepository repo) async {
    for (final entry in repo.entries) {
      final state = _cellKeys[entry.key]?.currentState;
      if (state != null && !await state.commit()) return false;
    }
    return true;
  }

  Future<void> _openFocusedEditor(
    TranslationRepository repo,
    I18nEntry entry,
  ) async {
    if (!await (_cellKeys[entry.key]?.currentState?.commit() ??
            Future.value(true)) ||
        !mounted) {
      return;
    }
    if (!await _confirmDraftChange(repo) || !mounted) return;
    repo.selectEntry(entry.key);
    if (repo.selectedKey != entry.key) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => Dialog(
        key: const ValueKey('wb.i18nFocusDialog'),
        child: SizedBox(
          width: 820,
          height: MediaQuery.sizeOf(dialogContext).height * 0.78,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  ctGapLg,
                  ctGapSm,
                  ctGapSm,
                  0,
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        '专注编辑',
                        style: ctText(size: ctFontMd, weight: FontWeight.w600),
                      ),
                    ),
                    IconButton(
                      key: const ValueKey('wb.i18nFocusClose'),
                      tooltip: '关闭专注编辑',
                      icon: const Icon(Icons.close),
                      onPressed: () async {
                        if (await _confirmDraftChange(repo) &&
                            dialogContext.mounted) {
                          Navigator.pop(dialogContext);
                        }
                      },
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(ctGapLg),
                  child: _focusedEditor(repo),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _confirmRow(TranslationRepository repo, I18nEntry entry) async {
    if (!await (_cellKeys[entry.key]?.currentState?.commit() ??
            Future.value(true)) ||
        !mounted) {
      return;
    }
    final current = repo.entries
        .where((item) => item.key == entry.key)
        .firstOrNull;
    if (current == null) return;
    await repo.saveRow(
      key: current.key,
      text: current.text,
      confirmed: !current.confirmed,
    );
  }

  Future<void> _changeTable(TranslationRepository repo, String value) async {
    if (value == repo.table || !await _commitInlineEdits(repo)) return;
    if (!await _confirmDraftChange(repo) || !mounted) return;
    await repo.selectTable(value);
  }

  Future<void> _changeLang(TranslationRepository repo, String value) async {
    if (value == repo.lang || !await _commitInlineEdits(repo)) return;
    if (!await _confirmDraftChange(repo) || !mounted) return;
    await repo.selectLang(value);
  }

  Future<void> _changeFilter(
    TranslationRepository repo,
    TranslationFilter value,
  ) async {
    if (value == repo.filter || !await _commitInlineEdits(repo)) return;
    if (!await _confirmDraftChange(repo) || !mounted) return;
    await repo.selectFilter(value);
  }

  Future<void> _refresh(TranslationRepository repo) async {
    if (!await _commitInlineEdits(repo) || !mounted) return;
    if (!await _confirmDraftChange(repo) || !mounted) return;
    await repo.refresh();
  }

  // ---- 筛选与操作 ----

  Widget _operationState(TranslationRepository repo) {
    if (!repo.busy) {
      return const CtStatusBadge(label: '就绪', tone: CtBadgeTone.ok, dot: false);
    }
    final label = repo.saving
        ? '正在保存译文'
        : repo.syncing
        ? '正在同步语言键'
        : '正在读取译文';
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        const SizedBox(width: ctGapSm),
        Text(
          label,
          style: ctText(size: ctFontXs, color: ctInk2),
        ),
      ],
    );
  }

  Widget _filters(TranslationRepository repo) => Container(
    key: const ValueKey('wb.i18nFilters'),
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: ctGapMd, vertical: ctGapSm),
    decoration: BoxDecoration(
      color: ctSurface,
      borderRadius: ctRadiusMdAll,
      border: Border.all(color: ctBorder),
    ),
    child: LayoutBuilder(
      builder: (context, constraints) {
        final selectors = Wrap(
          spacing: ctGapMd,
          runSpacing: ctGapXs,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            _labelled(
              '表',
              170,
              CtSearchPicker(
                key: const ValueKey('wb.i18nTable'),
                keyPrefix: 'wb.i18nTable',
                title: '选择表',
                value: repo.table,
                options: widget.tables,
                enabled: !repo.busy,
                onChanged: (value) => _changeTable(repo, value),
              ),
            ),
            _labelled(
              '语言',
              130,
              CtSearchPicker(
                key: const ValueKey('wb.i18nLang'),
                keyPrefix: 'wb.i18nLang',
                title: '选择语言',
                value: repo.lang,
                options: repo.langNames,
                enabled: !repo.busy,
                onChanged: (value) => _changeLang(repo, value),
              ),
            ),
            _labelled(
              '状态',
              130,
              _dropdown<TranslationFilter>(
                key: 'wb.i18nStatus',
                value: repo.filter,
                items: [
                  for (final item in TranslationFilter.values)
                    DropdownMenuItem(value: item, child: Text(item.label)),
                ],
                onChanged: repo.busy
                    ? null
                    : (v) => _changeFilter(repo, v ?? TranslationFilter.all),
              ),
            ),
          ],
        );
        final actions = _toolbarActions(repo);
        if (constraints.maxWidth >= 1060) {
          return Row(
            children: [
              Expanded(child: selectors),
              const SizedBox(width: ctGapMd),
              actions,
            ],
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            selectors,
            const SizedBox(height: ctGapXs),
            Align(alignment: Alignment.centerRight, child: actions),
          ],
        );
      },
    ),
  );

  static const double _actionWidth = 92;
  static const double _actionHeight = 40;

  Widget _toolbarActions(TranslationRepository repo) => Wrap(
    spacing: ctGapXs,
    runSpacing: ctGapXs,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [
      SizedBox(
        width: _actionWidth,
        height: _actionHeight,
        child: CtButton.ghost(
          '刷新',
          key: const ValueKey('wb.i18nRefresh'),
          onPressed: repo.busy ? null : () => _refresh(repo),
        ),
      ),
      SizedBox(
        width: _actionWidth,
        height: _actionHeight,
        child: CtButton.ghost(
          '同步本表',
          key: const ValueKey('wb.i18nSyncTable'),
          onPressed: repo.busy || !repo.canQuery
              ? null
              : () async {
                  if (await _commitInlineEdits(repo)) {
                    await repo.sync(scopedToTable: true);
                  }
                },
        ),
      ),
      SizedBox(
        width: _actionWidth,
        height: _actionHeight,
        child: PopupMenuButton<String>(
          key: const ValueKey('wb.i18nColumnsMenu'),
          popUpAnimationStyle: ctMenuStyle(context),
          tooltip: '选择列表显示内容',
          onSelected: repo.toggleColumn,
          itemBuilder: (context) => [
            for (final column in const [
              'source',
              'text',
              'confirmed',
              'status',
            ])
              CheckedPopupMenuItem<String>(
                key: ValueKey('wb.i18nColumn.$column'),
                value: column,
                checked: repo.shown(column),
                child: Text(_columnLabel(column)),
              ),
          ],
          child: const _ToolbarMenuLabel('列'),
        ),
      ),
      SizedBox(
        width: _actionWidth,
        height: _actionHeight,
        child: PopupMenuButton<String>(
          key: const ValueKey('wb.i18nActionsMenu'),
          popUpAnimationStyle: ctMenuStyle(context),
          tooltip: '更多翻译操作',
          enabled: !repo.busy && repo.canQuery,
          onSelected: (value) async {
            if (!await _commitInlineEdits(repo)) return;
            switch (value) {
              case 'sync':
                await repo.sync();
              case 'compact':
                await _previewCompact(repo);
            }
          },
          itemBuilder: (context) => const [
            PopupMenuItem<String>(
              value: 'sync',
              child: Text('同步全库', key: ValueKey('wb.i18nSync')),
            ),
            PopupMenuItem<String>(
              value: 'compact',
              child: Text('清理孤立预检', key: ValueKey('wb.i18nCompactPreview')),
            ),
          ],
          child: _ToolbarMenuLabel('更多', enabled: !repo.busy && repo.canQuery),
        ),
      ),
    ],
  );

  String _columnLabel(String column) => switch (column) {
    'source' => '原文',
    'text' => '译文',
    'confirmed' => '确认',
    _ => '状态',
  };

  Widget _labelled(String label, double width, Widget child) => Row(
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

  Widget _dropdown<T>({
    required String key,
    required T value,
    required List<DropdownMenuItem<T>> items,
    required void Function(T?)? onChanged,
  }) {
    final selected = items.firstWhere(
      (item) => item.value == value,
      orElse: () => items.first,
    );
    return PopupMenuButton<T>(
      key: ValueKey(key),
      tooltip: '选择状态',
      enabled: onChanged != null,
      initialValue: selected.value,
      position: PopupMenuPosition.under,
      popUpAnimationStyle: ctMenuStyle(context),
      onSelected: (value) => onChanged?.call(value),
      itemBuilder: (context) => [
        for (final item in items)
          PopupMenuItem<T>(value: item.value, child: item.child),
      ],
      child: Container(
        height: 32,
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(
              color: onChanged == null ? ctBorderStrong : ctInk3,
            ),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: DefaultTextStyle(
                style: ctText(
                  size: ctFontSm,
                  color: onChanged == null ? ctInk3 : ctInk,
                ),
                child: selected.child,
              ),
            ),
            Icon(
              Icons.arrow_drop_down,
              color: onChanged == null ? ctInk3 : ctInk2,
            ),
          ],
        ),
      ),
    );
  }

  // ---- 进度总览（i18n.status） ----

  Widget _progress(TranslationRepository repo) {
    if (repo.langs.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: ctGapSm),
      child: Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton.icon(
          key: const ValueKey('wb.i18nProgress'),
          onPressed: () => _showProgress(repo),
          icon: const Icon(Icons.bar_chart_outlined, size: 17),
          label: Text('全库进度 · ${repo.langs.length} 种语言'),
        ),
      ),
    );
  }

  Future<void> _showProgress(TranslationRepository repo) => showDialog<void>(
    context: context,
    builder: (dialogContext) => Dialog(
      key: const ValueKey('wb.i18nProgressDialog'),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: 620,
          maxHeight: (MediaQuery.sizeOf(dialogContext).height - 48).clamp(
            0.0,
            560.0,
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(ctGapXl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '全库翻译进度',
                      style: ctText(size: ctFontLg, weight: FontWeight.w600),
                    ),
                  ),
                  IconButton(
                    key: const ValueKey('wb.i18nProgressClose'),
                    tooltip: '关闭进度',
                    onPressed: () => Navigator.pop(dialogContext),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              Text(
                '共 ${repo.langs.length} 种语言',
                style: ctText(size: ctFontSm, color: ctInk3),
              ),
              const SizedBox(height: ctGapLg),
              Flexible(
                fit: FlexFit.loose,
                child: ListView.separated(
                  key: const ValueKey('wb.i18nProgressList'),
                  shrinkWrap: true,
                  itemCount: repo.langs.length,
                  separatorBuilder: (_, _) => const SizedBox(height: ctGapSm),
                  itemBuilder: (context, index) {
                    final lang = repo.langs[index];
                    return Container(
                      key: ValueKey('wb.i18nProgress.${lang.lang}'),
                      padding: const EdgeInsets.all(ctGapMd),
                      decoration: BoxDecoration(
                        color: lang.lang == repo.lang
                            ? ctAccentSofter
                            : ctSurface,
                        border: Border.all(color: ctBorder),
                        borderRadius: ctRadiusMdAll,
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            lang.lang,
                            style: ctText(
                              size: ctFontMd,
                              weight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(height: ctGapSm),
                          Wrap(
                            spacing: ctGapLg,
                            runSpacing: ctGapXs,
                            children: [
                              _progressCount('已翻译', lang.translated),
                              _progressCount('缺失', lang.missing),
                              _progressCount('过期', lang.stale),
                              _progressCount('孤立', lang.orphan),
                            ],
                          ),
                        ],
                      ),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _progressCount(String label, int count) => SizedBox(
    width: 116,
    child: Row(
      children: [
        Text(
          label,
          style: ctText(size: ctFontXs, color: ctInk3),
        ),
        const SizedBox(width: ctGapSm),
        Expanded(
          child: Tooltip(
            message: '$count',
            child: Text(
              '$count',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: ctMono.copyWith(fontSize: ctFontSm, color: ctInk2),
            ),
          ),
        ),
      ],
    ),
  );

  Widget _notices(TranslationRepository repo) {
    final blocks = <Widget>[];
    if (widget.busyElsewhere != null) {
      blocks.add(
        _banner(widget.busyElsewhere!, ctWarn, ctWarnSoft, 'wb.i18nBlocked'),
      );
    }
    if (repo.error != null) {
      blocks.add(_banner(repo.error!, ctDanger, ctDangerSoft, 'wb.i18nError'));
    }
    if (repo.notice != null) {
      blocks.add(_banner(repo.notice!, ctInk2, ctSurface2, 'wb.i18nNotice'));
    }
    if (repo.lastCompact != null && repo.lastCompact!.dryRun) {
      final found = repo.lastCompact!;
      blocks.add(
        Container(
          key: const ValueKey('wb.i18nCompactPlan'),
          margin: const EdgeInsets.only(bottom: ctGapSm),
          padding: const EdgeInsets.all(ctGapMd),
          decoration: BoxDecoration(
            color: ctWarnSoft,
            borderRadius: ctRadiusMdAll,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '预检结果：将清理 ${found.removed} 条孤立，'
                '范围=${repo.lastCompact!.entries.isEmpty ? '全部语言' : '当前清单'}',
                style: ctText(size: ctFontSm),
              ),
              for (final key in found.entries.take(10))
                Text(key, style: ctMono.copyWith(fontSize: ctFontXs)),
              const SizedBox(height: ctGapSm),
              Row(
                children: [
                  CtButton.ghost(
                    '确认清理',
                    key: const ValueKey('wb.i18nCompactApply'),
                    onPressed: repo.busy
                        ? null
                        : () => _confirmAndApply(repo, found),
                  ),
                  const SizedBox(width: ctGapSm),
                  Text('未确认前不会写任何文件', style: ctText(size: ctFontXs)),
                ],
              ),
            ],
          ),
        ),
      );
    }
    if (blocks.isEmpty) return const SizedBox.shrink();
    return Column(children: blocks);
  }

  Widget _banner(String text, Color fg, Color bg, String key) => Container(
    key: ValueKey(key),
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: ctGapSm),
    padding: const EdgeInsets.symmetric(horizontal: ctGapMd, vertical: ctGapSm),
    decoration: BoxDecoration(color: bg, borderRadius: ctRadiusSmAll),
    child: Text(
      text,
      style: ctText(size: ctFontSm, color: fg),
    ),
  );

  // ---- 译文表 ----

  Widget _table(TranslationRepository repo) => LayoutBuilder(
    builder: (context, bounds) {
      final compact = bounds.maxWidth < 900;
      final stacked = bounds.maxWidth < 530;
      return Container(
        key: const ValueKey('wb.i18nRows'),
        width: double.infinity,
        decoration: BoxDecoration(
          color: ctSurface,
          borderRadius: ctRadiusMdAll,
          border: Border.all(color: ctBorder),
        ),
        child: Column(
          children: [
            if (!compact && repo.canQuery) _tableHeader(repo),
            Expanded(
              child: !repo.canQuery
                  ? Center(child: _hint('选择表与语言后开始翻译'))
                  : repo.entries.isEmpty && !repo.loading
                  ? Center(child: _hint('当前筛选下没有条目', key: 'wb.i18nEmpty'))
                  : ListView.builder(
                      itemCount: repo.entries.length,
                      itemBuilder: (context, index) => _row(
                        repo,
                        repo.entries[index],
                        compact: compact,
                        stacked: stacked,
                      ),
                    ),
            ),
            if (repo.canQuery) _pagination(repo),
          ],
        ),
      );
    },
  );

  Widget _tableHeader(TranslationRepository repo) => Container(
    height: ctRowMd,
    padding: const EdgeInsets.symmetric(horizontal: ctGapMd),
    decoration: const BoxDecoration(
      color: ctSurface2,
      border: Border(bottom: BorderSide(color: ctBorder)),
    ),
    child: Row(
      children: [
        SizedBox(
          width: 180,
          child: Text(
            '键',
            style: ctText(size: ctFontXs, color: ctInk2),
          ),
        ),
        if (repo.shown('source'))
          Expanded(
            flex: 3,
            child: Text(
              '原文',
              style: ctText(size: ctFontXs, color: ctInk2),
            ),
          ),
        if (repo.shown('text'))
          Expanded(
            flex: 4,
            child: Text(
              '译文',
              style: ctText(size: ctFontXs, color: ctInk2),
            ),
          ),
        const SizedBox(width: 172, child: Text('状态 / 操作')),
      ],
    ),
  );

  Widget _row(
    TranslationRepository repo,
    I18nEntry entry, {
    required bool compact,
    required bool stacked,
  }) {
    final source = Text(
      entry.source,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
      style: ctText(size: ctFontSm),
    );
    final target = _translationCell(repo, entry);
    return Container(
      key: ValueKey('wb.i18nRow.${entry.key}'),
      decoration: BoxDecoration(
        color: repo.selectedKey == entry.key ? ctAccentSofter : null,
        border: const Border(bottom: BorderSide(color: ctBorder)),
      ),
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapMd,
        vertical: ctGapXs,
      ),
      child: compact
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(child: _keyLabel(repo, entry)),
                    _rowActions(repo, entry),
                  ],
                ),
                if (repo.shown('source') || repo.shown('text')) ...[
                  const SizedBox(height: ctGapXs),
                  if (stacked)
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (repo.shown('source')) source,
                        if (repo.shown('text')) target,
                      ],
                    )
                  else
                    Row(
                      children: [
                        if (repo.shown('source'))
                          Expanded(flex: 3, child: source),
                        if (repo.shown('source') && repo.shown('text'))
                          const SizedBox(width: ctGapMd),
                        if (repo.shown('text'))
                          Expanded(flex: 4, child: target),
                      ],
                    ),
                ],
              ],
            )
          : Row(
              children: [
                SizedBox(width: 180, child: _keyLabel(repo, entry)),
                if (repo.shown('source')) Expanded(flex: 3, child: source),
                if (repo.shown('text')) Expanded(flex: 4, child: target),
                _rowActions(repo, entry),
              ],
            ),
    );
  }

  Widget _keyLabel(TranslationRepository repo, I18nEntry entry) => InkWell(
    onTap: repo.busy ? null : () => _openFocusedEditor(repo, entry),
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: ctGapSm),
      child: Text(
        entry.key,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: ctMono.copyWith(
          fontSize: ctFontXs,
          color: repo.busy ? ctInk3 : ctPrimary,
        ),
      ),
    ),
  );

  Widget _rowActions(TranslationRepository repo, I18nEntry entry) => SizedBox(
    width: 172,
    child: Row(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        if (repo.shown('status')) _statusBadge(entry.status),
        if (repo.shown('confirmed'))
          Tooltip(
            message: entry.confirmed ? '取消确认' : '确认译文',
            child: IconButton(
              key: ValueKey('wb.i18nConfirmed.${entry.key}'),
              icon: Icon(
                entry.confirmed ? Icons.verified : Icons.check_circle_outline,
                size: 19,
              ),
              color: entry.confirmed ? ctAccent : ctInk3,
              disabledColor: const Color(0xFF8A958D),
              onPressed: repo.busy ? null : () => _confirmRow(repo, entry),
            ),
          ),
        IconButton(
          key: ValueKey('wb.i18nEdit.${entry.key}'),
          tooltip: '专注编辑',
          icon: const Icon(Icons.open_in_full, size: 17),
          onPressed: repo.busy ? null : () => _openFocusedEditor(repo, entry),
        ),
      ],
    ),
  );

  Widget _translationCell(TranslationRepository repo, I18nEntry entry) =>
      _EditableCell(
        key: _cellKey(entry.key),
        textKey: 'wb.i18nCell.${entry.key}',
        initial: entry.text,
        enabled: !repo.busy,
        onSave: (text) => repo.saveRow(
          key: entry.key,
          text: text,
          confirmed: entry.confirmed,
        ),
        onCancelEdit: repo.cancelEdit,
      );

  Widget _statusBadge(I18nStatus status) {
    final (label, tone) = switch (status) {
      I18nStatus.translated => ('已翻译', CtBadgeTone.ok),
      I18nStatus.missing => ('缺失', CtBadgeTone.warn),
      I18nStatus.stale => ('过期', CtBadgeTone.busy),
      I18nStatus.orphan => ('孤立', CtBadgeTone.danger),
    };
    return CtStatusBadge(label: label, tone: tone, dot: false);
  }

  Widget _pagination(TranslationRepository repo) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(horizontal: ctGapMd, vertical: ctGapXs),
    decoration: const BoxDecoration(
      border: Border(top: BorderSide(color: ctBorder)),
    ),
    child: Wrap(
      spacing: ctGapMd,
      runSpacing: ctGapXs,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        Text(
          '已取 ${repo.shownCount} 条（代次 ${repo.revision}）',
          key: const ValueKey('wb.i18nCount'),
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
        CtButton.ghost(
          '加载更多',
          key: const ValueKey('wb.i18nMore'),
          onPressed: repo.canLoadMore && !repo.busy
              ? () async {
                  if (await _commitInlineEdits(repo)) await repo.loadMore();
                }
              : null,
        ),
      ],
    ),
  );

  Widget _hint(String text, {String? key}) => Container(
    key: key == null ? null : ValueKey(key),
    width: double.infinity,
    padding: const EdgeInsets.all(ctGapMd),
    decoration: BoxDecoration(color: ctSurface2, borderRadius: ctRadiusMdAll),
    child: Text(
      text,
      style: ctText(size: ctFontSm, color: ctInk2),
    ),
  );

  // ---- 专注编辑器与清理确认 ----

  Widget _focusedEditor(TranslationRepository repo) {
    if (!repo.canQuery) {
      return _hint('选择表与语言后即可编辑译文');
    }
    final entry = repo.selectedEntry;
    if (entry == null) {
      return _hint('选择一个条目开始专注编辑', key: 'wb.i18nEditorEmpty');
    }
    return Container(
      key: const ValueKey('wb.i18nEditor'),
      padding: const EdgeInsets.all(ctGapMd),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: _FocusedEditor(
        key: ValueKey('wb.i18nEditor.${entry.key}'),
        repo: repo,
        entry: entry,
      ),
    );
  }

  Future<void> _previewCompact(TranslationRepository repo) async {
    final plan = await repo.compactPreview();
    if (!mounted || plan == null) return;
    setState(() {});
  }

  Future<void> _confirmAndApply(
    TranslationRepository repo,
    I18nCompactResult plan,
  ) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        key: const ValueKey('wb.i18nCompactConfirm'),
        title: const Text('确认清理孤立译文？'),
        content: Text(
          '将删除 ${plan.removed} 条孤儿条目（内核预检给出的键）：\n'
          '${plan.entries.take(8).join('\n')}'
          '${plan.entries.length > 8 ? '\n…共 ${plan.entries.length} 条' : ''}',
        ),
        actions: [
          CtButton.ghost(
            '取消',
            onPressed: () => Navigator.pop(dialogContext, false),
          ),
          CtButton.accent(
            '确认清理',
            key: const ValueKey('wb.i18nCompactGo'),
            onPressed: () => Navigator.pop(dialogContext, true),
          ),
        ],
      ),
    );
    if (go != true) return;
    await repo.compactApply();
    await repo.refresh();
  }
}

/// 失焦即保存的单格编辑器；Esc 放弃并恢复原值（任务 4.2）。
class _EditableCell extends StatefulWidget {
  const _EditableCell({
    super.key,
    required this.initial,
    required this.textKey,
    required this.enabled,
    required this.onSave,
    this.onCancelEdit,
  });

  final String initial;
  final String textKey;
  final bool enabled;
  final Future<bool> Function(String text) onSave;
  final VoidCallback? onCancelEdit;

  @override
  State<_EditableCell> createState() => _EditableCellState();
}

class _EditableCellState extends State<_EditableCell> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.initial,
  );
  final FocusNode _focus = FocusNode();
  bool _dirty = false;
  Future<bool>? _pendingSave;

  @override
  void initState() {
    super.initState();
    _focus.addListener(_onFocusChange);
  }

  @override
  void didUpdateWidget(_EditableCell old) {
    super.didUpdateWidget(old);
    if (old.initial != widget.initial && !_focus.hasFocus) {
      _controller.text = widget.initial;
      _dirty = false;
    }
  }

  void _onFocusChange() {
    if (!_focus.hasFocus && _dirty) commit();
  }

  Future<bool> commit() {
    if (_pendingSave case final pending?) return pending;
    if (!_dirty) return Future.value(true);
    final pending = _submit();
    _pendingSave = pending;
    pending.whenComplete(() => _pendingSave = null);
    return pending;
  }

  Future<bool> _submit() async {
    final text = _controller.text;
    final saved = await widget.onSave(text);
    if (!mounted) return saved;
    // 失败时保留输入；保存期间又有输入时不能误标记为已保存。
    setState(() => _dirty = !saved || _controller.text != text);
    return !_dirty;
  }

  void _cancel() {
    _controller.text = widget.initial;
    _dirty = false;
    widget.onCancelEdit?.call();
    _focus.unfocus();
    setState(() {});
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    if (_controller.value.composing.isValid ||
        event.logicalKey != LogicalKeyboardKey.escape) {
      return KeyEventResult.ignored;
    }
    _cancel();
    return KeyEventResult.handled;
  }

  @override
  void dispose() {
    _focus.removeListener(_onFocusChange);
    _focus.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Focus(
      canRequestFocus: false,
      onKeyEvent: _onKey,
      child: TextField(
        key: ValueKey(widget.textKey),
        controller: _controller,
        focusNode: _focus,
        enabled: widget.enabled,
        style: ctText(size: ctFontSm),
        decoration: const InputDecoration(
          isDense: true,
          hintText: '输入译文…',
          contentPadding: EdgeInsets.symmetric(
            horizontal: ctGapSm,
            vertical: ctGapSm,
          ),
          border: OutlineInputBorder(),
        ),
        onChanged: (value) => setState(() {
          _dirty = value != widget.initial;
        }),
        onSubmitted: (_) => commit(),
      ),
    );
  }
}

class _ToolbarMenuLabel extends StatelessWidget {
  const _ToolbarMenuLabel(this.label, {this.enabled = true});
  final String label;
  final bool enabled;

  @override
  Widget build(BuildContext context) => Container(
    width: _WorkbenchI18nViewState._actionWidth,
    height: _WorkbenchI18nViewState._actionHeight,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      border: Border.all(color: enabled ? ctBorderStrong : ctBorder),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(
          label,
          style: ctText(
            size: 13,
            color: enabled ? ctInk2 : ctInk3,
            weight: FontWeight.w600,
          ),
        ),
        const SizedBox(width: 4),
        Icon(Icons.expand_more, size: 15, color: enabled ? ctInk2 : ctInk3),
      ],
    ),
  );
}

enum _DraftAction { save, discard, cancel }

/// 专注编辑多条译文；保存只在显式按钮或 Ctrl/Cmd+Enter 时发生。
class _FocusedEditor extends StatefulWidget {
  const _FocusedEditor({super.key, required this.repo, required this.entry});

  final TranslationRepository repo;
  final I18nEntry entry;

  @override
  State<_FocusedEditor> createState() => _FocusedEditorState();
}

class _FocusedEditorState extends State<_FocusedEditor> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.repo.draftText,
  );
  final FocusNode _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    widget.repo.addListener(_onRepositoryChanged);
  }

  void _onRepositoryChanged() {
    if (!mounted) return;
    _syncController();
    setState(() {});
  }

  @override
  void didUpdateWidget(covariant _FocusedEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.entry.key != widget.entry.key ||
        _controller.text != widget.repo.draftText) {
      _syncController();
    }
  }

  void _syncController() {
    final text = widget.repo.draftText;
    if (_controller.text == text) return;
    _controller.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }

  Future<void> _save() async {
    if (widget.repo.busy) return;
    await widget.repo.saveDraft();
    if (mounted) _focus.requestFocus();
  }

  void _cancel() {
    widget.repo.discardDraft();
    if (mounted) _focus.requestFocus();
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    if (_controller.value.composing.isValid) {
      return KeyEventResult.ignored;
    }
    final enter =
        event.logicalKey == LogicalKeyboardKey.enter ||
        event.logicalKey == LogicalKeyboardKey.numpadEnter;
    final modifier =
        HardwareKeyboard.instance.isControlPressed ||
        HardwareKeyboard.instance.isMetaPressed;
    if (enter && modifier) {
      _save();
      return KeyEventResult.handled;
    }
    if (event.logicalKey == LogicalKeyboardKey.escape) {
      _cancel();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  void dispose() {
    widget.repo.removeListener(_onRepositoryChanged);
    _focus.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final repo = widget.repo;
    final dirty = repo.draftDirty;
    return Focus(
      canRequestFocus: false,
      onKeyEvent: _onKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '专注编辑',
                      style: ctText(size: ctFontSm, weight: FontWeight.w600),
                    ),
                    const SizedBox(height: ctGapXs),
                    Text(
                      widget.entry.key,
                      key: const ValueKey('wb.i18nEditorKey'),
                      style: ctMono.copyWith(fontSize: ctFontXs),
                    ),
                    const SizedBox(height: ctGapXs),
                    Text(
                      '${repo.table} · ${repo.lang}',
                      key: const ValueKey('wb.i18nEditorContext'),
                      style: ctText(size: ctFontXs, color: ctInk3),
                    ),
                  ],
                ),
              ),
              CtStatusBadge(
                label: dirty
                    ? '未保存'
                    : widget.entry.confirmed
                    ? '已确认'
                    : '待确认',
                tone: dirty || !widget.entry.confirmed
                    ? CtBadgeTone.warn
                    : CtBadgeTone.ok,
                dot: false,
              ),
            ],
          ),
          const SizedBox(height: ctGapMd),
          LayoutBuilder(
            builder: (context, constraints) {
              final source = _sourceBlock();
              final target = _targetBlock();
              if (constraints.maxWidth >= 560) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: source),
                    const SizedBox(width: ctGapLg),
                    Expanded(child: target),
                  ],
                );
              }
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  source,
                  const SizedBox(height: ctGapMd),
                  target,
                ],
              );
            },
          ),
          const SizedBox(height: ctGapMd),
          Wrap(
            spacing: ctGapSm,
            runSpacing: ctGapXs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              CtButton.ghost(
                '取消',
                key: const ValueKey('wb.i18nEditorCancel'),
                onPressed: repo.busy || !dirty ? null : _cancel,
              ),
              CtButton.accent(
                '保存并确认',
                key: const ValueKey('wb.i18nEditorSave'),
                onPressed:
                    repo.busy ||
                        (repo.selectedEntry?.confirmed == true && !dirty)
                    ? null
                    : _save,
              ),
              Text(
                'Ctrl/Cmd+Enter 保存',
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _sourceBlock() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        '原文',
        style: ctText(size: ctFontXs, color: ctInk3),
      ),
      const SizedBox(height: ctGapXs),
      Container(
        key: const ValueKey('wb.i18nEditorSource'),
        width: double.infinity,
        height: 160,
        padding: const EdgeInsets.all(ctGapSm + 2),
        decoration: BoxDecoration(
          color: ctSurface2,
          borderRadius: ctRadiusSmAll,
          border: Border.all(color: ctBorder),
        ),
        child: SingleChildScrollView(
          child: SelectableText(
            widget.entry.source,
            style: ctText(size: ctFontSm),
          ),
        ),
      ),
    ],
  );

  Widget _targetBlock() => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        '译文',
        style: ctText(size: ctFontXs, color: ctInk3),
      ),
      const SizedBox(height: ctGapXs),
      SizedBox(
        height: 160,
        child: TextField(
          key: const ValueKey('wb.i18nEditorText'),
          controller: _controller,
          focusNode: _focus,
          readOnly: widget.repo.busy,
          keyboardType: TextInputType.multiline,
          textInputAction: TextInputAction.newline,
          expands: true,
          minLines: null,
          maxLines: null,
          textAlignVertical: TextAlignVertical.top,
          style: ctText(size: ctFontSm),
          decoration: ctInputDecoration().copyWith(
            contentPadding: const EdgeInsets.all(ctGapSm + 2),
            hintText: '输入译文，支持多行…',
          ),
          onChanged: widget.repo.updateDraft,
        ),
      ),
    ],
  );
}
