import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/protocol/protocol.dart';
import '../../state/translation_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
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
  @override
  void initState() {
    super.initState();
    widget.repo.addListener(_changed);
    // 首屏预选第一张表（与资源区一致）：不预选就永远停在空态。
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
    return SingleChildScrollView(
      key: const ValueKey('wb.i18nView'),
      padding: const EdgeInsets.all(ctGapXl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('翻译', style: ctPageTitleStyle),
          const SizedBox(height: ctGapSm),
          _filters(repo),
          const SizedBox(height: ctGapMd),
          _progress(repo),
          const SizedBox(height: ctGapMd),
          _notices(repo),
          const SizedBox(height: ctGapSm),
          _table(repo),
          const SizedBox(height: ctGapMd),
          _pagination(repo),
        ],
      ),
    );
  }

  // ---- 筛选与操作 ----

  Widget _filters(TranslationRepository repo) {
    return Container(
      key: const ValueKey('wb.i18nFilters'),
      padding: const EdgeInsets.all(ctGapMd),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: ctGapLg,
            runSpacing: ctGapSm,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              _labelled(
                '表',
                170,
                _dropdown<String>(
                  key: 'wb.i18nTable',
                  value: repo.table,
                  items: [
                    const DropdownMenuItem(value: '', child: Text('（未选择）')),
                    for (final name in widget.tables)
                      DropdownMenuItem(value: name, child: Text(name)),
                  ],
                  onChanged: repo.busy
                      ? null
                      : (v) => repo.selectTable(v ?? ''),
                ),
              ),
              _labelled(
                '语言',
                130,
                _dropdown<String>(
                  key: 'wb.i18nLang',
                  value: repo.lang,
                  items: [
                    const DropdownMenuItem(value: '', child: Text('（未选择）')),
                    for (final name in repo.langNames)
                      DropdownMenuItem(value: name, child: Text(name)),
                  ],
                  onChanged: repo.busy ? null : (v) => repo.selectLang(v ?? ''),
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
                      : (v) => repo.selectFilter(v ?? TranslationFilter.all),
                ),
              ),
            ],
          ),
          const SizedBox(height: ctGapSm),
          Wrap(
            spacing: ctGapSm,
            runSpacing: ctGapXs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                '列显隐',
                style: ctText(size: ctFontXs, color: ctInk2),
              ),
              for (final column in const [
                'source',
                'text',
                'confirmed',
                'status',
              ])
                FilterChip(
                  key: ValueKey('wb.i18nColumn.$column'),
                  label: Text(_columnLabel(column)),
                  selected: repo.shown(column),
                  onSelected: (_) => repo.toggleColumn(column),
                ),
              const SizedBox(width: ctGapMd),
              CtButton.ghost(
                '刷新',
                key: const ValueKey('wb.i18nRefresh'),
                onPressed: repo.busy ? null : () => repo.refresh(),
              ),
              CtButton.ghost(
                '同步全库',
                key: const ValueKey('wb.i18nSync'),
                onPressed: repo.busy || !repo.canQuery
                    ? null
                    : () => repo.sync(),
              ),
              CtButton.ghost(
                '同步本表',
                key: const ValueKey('wb.i18nSyncTable'),
                onPressed: repo.busy || !repo.canQuery
                    ? null
                    : () => repo.sync(scopedToTable: true),
              ),
              CtButton.ghost(
                '清理孤立预检',
                key: const ValueKey('wb.i18nCompactPreview'),
                onPressed: repo.busy || !repo.canQuery
                    ? null
                    : () => _previewCompact(repo),
              ),
            ],
          ),
        ],
      ),
    );
  }

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
  }) => DropdownButton<T>(
    key: ValueKey(key),
    isExpanded: true,
    value: items.any((e) => e.value == value) ? value : items.first.value,
    items: items,
    onChanged: onChanged,
  );

  // ---- 进度总览（i18n.status） ----

  Widget _progress(TranslationRepository repo) {
    if (repo.langs.isEmpty) return const SizedBox.shrink();
    return Container(
      key: const ValueKey('wb.i18nProgress'),
      padding: const EdgeInsets.all(ctGapMd),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '语言进度',
            style: ctText(size: ctFontSm, weight: FontWeight.w600),
          ),
          const SizedBox(height: ctGapSm),
          for (final lang in repo.langs)
            Padding(
              padding: const EdgeInsets.only(bottom: 2),
              child: Text(
                '${lang.lang}　已翻译 ${lang.translated}　缺失 ${lang.missing}'
                '　过期 ${lang.stale}　孤立 ${lang.orphan}',
                key: ValueKey('wb.i18nProgress.${lang.lang}'),
                style: ctMono.copyWith(fontSize: ctFontXs),
              ),
            ),
        ],
      ),
    );
  }

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

  Widget _table(TranslationRepository repo) {
    if (!repo.canQuery) {
      return _hint('选择表与语言后由内核返回译文（筛选与分页都在内核执行）');
    }
    if (repo.entries.isEmpty && !repo.loading) {
      return _hint('当前筛选下没有条目', key: 'wb.i18nEmpty');
    }
    final rows = <DataRow>[];
    for (final entry in repo.entries) {
      rows.add(_row(repo, entry));
    }
    return Container(
      key: const ValueKey('wb.i18nRows'),
      decoration: BoxDecoration(
        color: ctSurface,
        borderRadius: ctRadiusMdAll,
        border: Border.all(color: ctBorder),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          columnSpacing: ctGapLg,
          dataRowMinHeight: ctRowSm,
          headingRowHeight: ctRowMd,
          columns: [
            const DataColumn(label: Text('键')),
            if (repo.shown('source')) const DataColumn(label: Text('原文')),
            if (repo.shown('text')) const DataColumn(label: Text('译文')),
            if (repo.shown('confirmed')) const DataColumn(label: Text('确认')),
            if (repo.shown('status')) const DataColumn(label: Text('状态')),
            const DataColumn(label: Text('对照')),
          ],
          rows: rows,
        ),
      ),
    );
  }

  DataRow _row(TranslationRepository repo, I18nEntry entry) {
    return DataRow(
      key: ValueKey('wb.i18nRow.${entry.key}'),
      cells: [
        DataCell(
          SizedBox(
            width: 150,
            child: Text(
              entry.key,
              style: ctMono.copyWith(fontSize: ctFontXs),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ),
        if (repo.shown('source'))
          DataCell(
            SizedBox(
              width: 150,
              child: Text(entry.source, style: ctText(size: ctFontSm)),
            ),
          ),
        if (repo.shown('text'))
          DataCell(SizedBox(width: 200, child: _translationCell(repo, entry))),
        if (repo.shown('confirmed'))
          DataCell(
            Checkbox(
              key: ValueKey('wb.i18nConfirmed.${entry.key}'),
              value: entry.confirmed,
              onChanged: repo.busy
                  ? null
                  : (v) => repo.saveRow(
                      key: entry.key,
                      text: entry.text,
                      confirmed: v ?? false,
                    ),
            ),
          ),
        if (repo.shown('status')) DataCell(_statusBadge(entry.status)),
        DataCell(
          CtButton.ghost(
            '对照',
            key: ValueKey('wb.i18nCompare.${entry.key}'),
            onPressed: () => _showCompare(entry),
          ),
        ),
      ],
    );
  }

  Widget _translationCell(TranslationRepository repo, I18nEntry entry) =>
      _EditableCell(
        key: ValueKey('wb.i18nCell.${entry.key}'),
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

  Widget _pagination(TranslationRepository repo) => Row(
    children: [
      Text(
        '已取 ${repo.shownCount} 条（代次 ${repo.revision}）',
        key: const ValueKey('wb.i18nCount'),
        style: ctText(size: ctFontSm, color: ctInk2),
      ),
      const SizedBox(width: ctGapMd),
      CtButton.ghost(
        '加载更多',
        key: const ValueKey('wb.i18nMore'),
        onPressed: repo.canLoadMore && !repo.busy
            ? () => repo.loadMore()
            : null,
      ),
    ],
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

  // ---- 长文本对照与清理确认 ----

  Future<void> _showCompare(I18nEntry entry) => showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      key: const ValueKey('wb.i18nCompareDialog'),
      title: Text(entry.key, style: ctMono.copyWith(fontSize: ctFontMd)),
      content: SizedBox(
        width: 520,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '原文',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
            SelectableText(entry.source, style: ctText(size: ctFontMd)),
            const SizedBox(height: ctGapMd),
            Text(
              '译文',
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
            SelectableText(entry.text, style: ctText(size: ctFontMd)),
          ],
        ),
      ),
      actions: [
        CtButton.ghost('关闭', onPressed: () => Navigator.pop(dialogContext)),
      ],
    ),
  );

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
    required this.enabled,
    required this.onSave,
    this.onCancelEdit,
  });

  final String initial;
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
    if (!_focus.hasFocus && _dirty) _submit();
  }

  Future<void> _submit() async {
    if (!_dirty) return;
    _dirty = false;
    await widget.onSave(_controller.text);
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
    if (event.logicalKey != LogicalKeyboardKey.escape) {
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
        key: const ValueKey('wb.i18nEditText'),
        controller: _controller,
        focusNode: _focus,
        enabled: widget.enabled,
        style: ctText(size: ctFontSm),
        decoration: const InputDecoration(isDense: true),
        onChanged: (value) => setState(() {
          _dirty = value != widget.initial;
        }),
        onSubmitted: (_) => _submit(),
      ),
    );
  }
}
