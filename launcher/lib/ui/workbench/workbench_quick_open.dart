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

/// 打开 Quick Open，返回被选中的条目（取消返回 null）。
Future<QuickOpenEntry?> showWorkbenchQuickOpen(
  BuildContext context, {
  required List<QuickOpenEntry> entries,
  required List<String> recents,
}) => showDialog<QuickOpenEntry>(
  context: context,
  builder: (dialogContext) => AlertDialog(
    title: null,
    content: SizedBox(
      width: 520,
      child: _QuickOpenBody(
        entries: entries,
        recents: recents,
        onPick: (entry) => Navigator.pop(dialogContext, entry),
      ),
    ),
    actions: const [],
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
    super.dispose();
  }

  void _onQuery() => setState(() => _selected = 0);

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
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const ValueKey('wb.quickOpen.field'),
              controller: _text,
              autofocus: true,
              decoration: const InputDecoration(
                isDense: true,
                hintText: '搜资源名（留空给最近打开）',
                prefixIcon: Icon(Icons.search, size: 18),
                border: InputBorder.none,
              ),
            ),
            const Divider(height: 1),
            Text(
              emptyQuery
                  ? '↑↓ 选择 · Enter 打开 · Esc 关闭 · 共 ${list.length} 项（最近打开在前）'
                  : '↑↓ 选择 · Enter 打开 · 命中 ${list.length} 项',
              key: const ValueKey('wb.quickOpen.hint'),
              style: ctText(size: ctFontXs, color: ctInk3),
            ),
            const SizedBox(height: ctGapXs),
            if (list.isEmpty)
              Padding(
                padding: const EdgeInsets.all(ctGapMd),
                child: Text(
                  '没有匹配的资源',
                  key: const ValueKey('wb.quickOpen.empty'),
                  style: ctText(size: ctFontSm, color: ctInk3),
                ),
              )
            else
              SizedBox(
                height: 260,
                child: ListView.builder(
                  itemCount: list.length,
                  itemBuilder: (context, index) {
                    final entry = list[index];
                    final selected = index == _selected;
                    return ListTile(
                      key: ValueKey('wb.quickOpen.row.${entry.name}.$index'),
                      dense: true,
                      selected: selected,
                      selectedTileColor: ctAccentSofter,
                      leading: Text(
                        entry.kindLabel,
                        style: ctMono.copyWith(fontSize: ctFontXs),
                      ),
                      title: Text(entry.name, style: ctText(size: ctFontSm)),
                      subtitle: entry.path.isEmpty
                          ? null
                          : Text(
                              entry.path,
                              style: ctText(size: ctFontXs, color: ctInk3),
                            ),
                      trailing: entry.refCount > 0
                          ? Text(
                              '引用 ${entry.refCount}',
                              style: ctText(size: ctFontXs, color: ctInk3),
                            )
                          : null,
                      onTap: () => widget.onPick(entry),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}
