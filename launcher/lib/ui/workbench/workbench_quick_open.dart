import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../theme.dart';
import '../widgets/common.dart';
import '../tokens.dart';

/// Quick Open（native-flutter-workbench 任务 3.7）：Ctrl/Cmd+P 呼出。
///
/// 空查询给"最近打开"（按工作区持久化，由调用方传入），之后是 fuzzy 子序列匹配；
/// 上/下键 + 回车纯键盘可选，Esc 关闭。资源清单本身来自内核 `resources.list`。
class QuickOpenEntry {
  const QuickOpenEntry({
    required this.name,
    required this.kindLabel,
    this.path = '',
    this.refCount = 0,
  });

  final String name;
  final String kindLabel;

  /// schema 源文件相对路径（内核 sourcePath）。
  final String path;

  /// 被引用次数：0 时列表里不显示引用标记。
  final int refCount;
}

/// fuzzy 过滤：子序列必须命中；连续命中与词首命中加权，间隙扣分。
/// 空查询原样返回（调用方已按最近打开排好序）。
List<T> wbFuzzyFilter<T>(String query, List<T> items, String Function(T) text) {
  final needle = query.trim().toLowerCase();
  if (needle.isEmpty) return items;
  final order = <(int, int)>[];
  for (var i = 0; i < items.length; i++) {
    final score = _fuzzyScore(needle, text(items[i]).toLowerCase());
    if (score == null) continue;
    order.add((score, i));
  }
  order.sort((a, b) {
    final byScore = b.$1.compareTo(a.$1);
    return byScore != 0 ? byScore : a.$2.compareTo(b.$2);
  });
  return [for (final pair in order) items[pair.$2]];
}

int? _fuzzyScore(String needle, String haystack) {
  var cursor = 0;
  var score = 0;
  var gaps = 0;
  for (var i = 0; i < needle.length; i++) {
    final found = haystack.indexOf(needle[i], cursor);
    if (found < 0) return null;
    gaps += found - cursor;
    score += found == cursor ? 3 : 1;
    if (i == 0 && found == 0) score += 6;
    if (i > 0 && _isBoundary(haystack, found - 1)) score += 2;
    cursor = found + 1;
  }
  return score - gaps;
}

bool _isBoundary(String text, int index) {
  if (index < 0) return true;
  final code = text.codeUnitAt(index);
  const separators = [0x5F, 0x2D, 0x2E, 0x20, 0x3A]; // _ - . space :
  return separators.contains(code);
}

class _UpIntent extends Intent {
  const _UpIntent();
}

class _DownIntent extends Intent {
  const _DownIntent();
}

class _AcceptIntent extends Intent {
  const _AcceptIntent();
}

/// 面板度量：固定行高，滚动定位与「最多露几行」都可直接算出来。
const double _panelWidth = 560;
const double _rowHeight = 56;
const int _maxVisibleRows = 5;

/// 打开 Quick Open，返回被选中的条目（取消返回 null）。
///
/// 面板是一张白卡片：搜索行只有一条下划线（无焦点描边、无选中态），
/// 列表与卡片同宽，选中/悬停背景铺满整行，圆角由卡片裁切。
Future<QuickOpenEntry?> showWorkbenchQuickOpen(
  BuildContext context, {
  required List<QuickOpenEntry> entries,
  required List<String> recents,
}) => showDialog<QuickOpenEntry>(
  context: context,
  builder: (dialogContext) => Dialog(
    insetPadding: const EdgeInsets.symmetric(
      horizontal: ctGapXl,
      vertical: ctGapXl,
    ),
    backgroundColor: ctSurface,
    surfaceTintColor: Colors.transparent,
    clipBehavior: Clip.antiAlias,
    shape: RoundedRectangleBorder(
      borderRadius: ctRadiusLgAll,
      side: const BorderSide(color: ctBorder),
    ),
    child: ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: _panelWidth,
        maxHeight: MediaQuery.sizeOf(dialogContext).height - 2 * ctGapXl,
      ),
      child: _QuickOpenBody(
        entries: entries,
        recents: recents,
        onPick: (entry) => Navigator.pop(dialogContext, entry),
      ),
    ),
  ),
);

class _QuickOpenBody extends StatefulWidget {
  const _QuickOpenBody({
    required this.entries,
    required this.recents,
    required this.onPick,
  });

  final List<QuickOpenEntry> entries;
  final List<String> recents;
  final ValueChanged<QuickOpenEntry> onPick;

  @override
  State<_QuickOpenBody> createState() => _QuickOpenBodyState();
}

class _QuickOpenBodyState extends State<_QuickOpenBody> {
  final TextEditingController _text = TextEditingController();
  final ScrollController _scroll = ScrollController();
  int _selected = 0;

  @override
  void initState() {
    super.initState();
    _text.addListener(_onQuery);
  }

  @override
  void dispose() {
    _text.removeListener(_onQuery);
    _text.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _onQuery() {
    setState(() => _selected = 0);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  /// 空查询：最近打开在前（按 recents 顺序），其余按名字补齐。
  List<QuickOpenEntry> get _visible {
    final byName = {for (final e in widget.entries) e.name: e};
    final head = [
      for (final name in widget.recents)
        if (byName.containsKey(name)) byName[name]!,
    ];
    final base = head.isEmpty
        ? widget.entries
        : [
            ...head,
            for (final e in widget.entries)
              if (!widget.recents.contains(e.name)) e,
          ];
    return wbFuzzyFilter<QuickOpenEntry>(
      _text.text,
      base,
      (e) => '${e.kindLabel}:${e.name} ${e.path}',
    );
  }

  void _move(int delta) {
    final count = _visible.length;
    if (count == 0) return;
    setState(() => _selected = (_selected + delta + count) % count);
    _revealSelection();
  }

  /// 键盘选择只做「最少滚动」：已经可见就不动，越过上下沿才挪一屏。
  void _revealSelection() {
    if (!_scroll.hasClients) return;
    final position = _scroll.position;
    final top = _selected * _rowHeight;
    final bottom = top + _rowHeight;
    final viewport = position.viewportDimension;
    final double? target;
    if (top < position.pixels) {
      target = top;
    } else if (bottom > position.pixels + viewport) {
      target = bottom - viewport;
    } else {
      target = null; // 已经完整可见：不动，避免列表无谓跳动。
    }
    if (target == null) return;
    _scroll.animateTo(
      target.clamp(0.0, position.maxScrollExtent),
      duration: ctMotionFast,
      curve: ctMotionCurve,
    );
  }

  void _accept() {
    final list = _visible;
    if (_selected < list.length) widget.onPick(list[_selected]);
  }

  @override
  Widget build(BuildContext context) {
    final list = _visible;
    final emptyQuery = _text.text.trim().isEmpty;
    return Shortcuts(
      shortcuts: {
        const SingleActivator(LogicalKeyboardKey.arrowUp): const _UpIntent(),
        const SingleActivator(LogicalKeyboardKey.arrowDown):
            const _DownIntent(),
        const SingleActivator(LogicalKeyboardKey.enter): const _AcceptIntent(),
        const SingleActivator(LogicalKeyboardKey.numpadEnter):
            const _AcceptIntent(),
      },
      child: Actions(
        actions: <Type, Action<Intent>>{
          _UpIntent: CallbackAction<_UpIntent>(
            onInvoke: (_) {
              _move(-1);
              return null;
            },
          ),
          _DownIntent: CallbackAction<_DownIntent>(
            onInvoke: (_) {
              _move(1);
              return null;
            },
          ),
          _AcceptIntent: CallbackAction<_AcceptIntent>(
            onInvoke: (_) {
              _accept();
              return null;
            },
          ),
        },
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _buildSearchRow(),
            Flexible(fit: FlexFit.loose, child: _buildResults(list)),
            _buildHint(list.length, emptyQuery),
          ],
        ),
      ),
    );
  }

  /// 搜索行：图标与输入框同排居中对齐，整行底边一条下划线。
  Widget _buildSearchRow() {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapLg,
        vertical: ctGapMd,
      ),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        children: [
          const Icon(Icons.search, size: 16, color: ctInk3),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: TextField(
              key: const ValueKey('wb.quickOpen.field'),
              controller: _text,
              autofocus: true,
              cursorColor: ctAccent,
              cursorWidth: 1.5,
              style: ctText(size: ctFontSm),
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: '搜资源名（留空给最近打开）',
                hintStyle: ctText(size: ctFontSm, color: ctInk3),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildResults(List<QuickOpenEntry> list) {
    if (list.isEmpty) {
      return SizedBox(
        key: const ValueKey('wb.quickOpen.results'),
        height: _rowHeight * 2,
        child: Center(
          child: Text(
            '没有匹配的资源',
            key: const ValueKey('wb.quickOpen.empty'),
            style: ctText(size: ctFontSm, color: ctInk3),
          ),
        ),
      );
    }
    return SizedBox(
      key: const ValueKey('wb.quickOpen.results'),
      height: (list.length * _rowHeight).clamp(
        _rowHeight,
        _maxVisibleRows * _rowHeight,
      ),
      child: ListView.builder(
        controller: _scroll,
        padding: EdgeInsets.zero,
        itemExtent: _rowHeight,
        itemCount: list.length,
        itemBuilder: (context, index) =>
            _buildRow(list[index], index, selected: index == _selected),
      ),
    );
  }

  /// 一行 = 类型 + 名字/路径 + 引用数；选中与悬停用同一层底色，铺满整行。
  Widget _buildRow(QuickOpenEntry entry, int index, {required bool selected}) {
    return Material(
      color: selected ? ctAccentSofter : ctSurface,
      child: InkWell(
        key: ValueKey('wb.quickOpen.row.${entry.name}.$index'),
        onTap: () => widget.onPick(entry),
        hoverColor: ctAccentSofter,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: ctGapLg),
          child: Row(
            children: [
              SizedBox(
                width: 32,
                child: Text(
                  entry.kindLabel,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
                ),
              ),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      entry.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: ctText(size: ctFontSm),
                    ),
                    if (entry.path.isNotEmpty)
                      Text(
                        entry.path,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: ctText(size: ctFontXs, color: ctInk3),
                      ),
                  ],
                ),
              ),
              if (entry.refCount > 0) ...[
                const SizedBox(width: ctGapSm),
                Text(
                  '引用 ${entry.refCount}',
                  style: ctText(size: ctFontXs, color: ctInk3),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHint(int count, bool emptyQuery) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(ctGapLg, ctGapSm, ctGapLg, ctGapMd),
      child: Text(
        emptyQuery
            ? '↑↓ 选择 · Enter 打开 · Esc 关闭 · 共 $count 项（最近打开在前）'
            : '↑↓ 选择 · Enter 打开 · Esc 关闭 · 命中 $count 项',
        key: const ValueKey('wb.quickOpen.hint'),
        textAlign: TextAlign.right,
        style: ctText(size: ctFontXs, color: ctInk3),
      ),
    );
  }
}
