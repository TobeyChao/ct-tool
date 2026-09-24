import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../theme.dart';
import '../tokens.dart';
import 'common.dart';

/// 用于工作区选项可能持续增长的单选控件。
class CtSearchPicker extends StatelessWidget {
  const CtSearchPicker({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    required this.title,
    required this.keyPrefix,
    this.emptyLabel = '（未选择）',
    this.includeEmpty = true,
    this.enabled = true,
    this.monospace = false,
  });

  final String value;
  final List<String> options;
  final ValueChanged<String> onChanged;
  final String title;
  final String keyPrefix;
  final String emptyLabel;
  final bool includeEmpty;
  final bool enabled;
  final bool monospace;

  @override
  Widget build(BuildContext context) {
    final current = value.trim();
    final known = {...options}.where((option) => option.isNotEmpty).toList()
      ..sort();
    final unknown = current.isNotEmpty && !known.contains(current);
    final display = current.isEmpty ? emptyLabel : current;
    final style = monospace ? ctMono : ctText(size: ctFontSm);

    return Material(
      color: ctSurface,
      borderRadius: ctRadiusSmAll,
      child: InkWell(
        key: ValueKey('$keyPrefix.picker'),
        borderRadius: ctRadiusSmAll,
        onTap: !enabled
            ? null
            : () async {
                final chosen = await showDialog<String>(
                  context: context,
                  builder: (context) => _SearchDialog(
                    keyPrefix: keyPrefix,
                    title: title,
                    current: current,
                    options: known,
                    unknown: unknown,
                    includeEmpty: includeEmpty,
                    emptyLabel: emptyLabel,
                    monospace: monospace,
                  ),
                );
                if (chosen != null && chosen != current) onChanged(chosen);
              },
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            border: Border.all(color: enabled ? ctBorderStrong : ctBorder),
            borderRadius: ctRadiusSmAll,
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  display,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: style.copyWith(
                    fontSize: ctFontSm,
                    fontWeight: FontWeight.w400,
                    color: !enabled
                        ? ctInk3
                        : unknown
                        ? ctDanger
                        : ctInk,
                  ),
                ),
              ),
              const SizedBox(width: ctGapXs),
              Icon(
                Icons.search,
                size: 15,
                color: enabled ? ctInk3 : ctBorderStrong,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SearchDialog extends StatefulWidget {
  const _SearchDialog({
    required this.keyPrefix,
    required this.title,
    required this.current,
    required this.options,
    required this.unknown,
    required this.includeEmpty,
    required this.emptyLabel,
    required this.monospace,
  });

  final String keyPrefix;
  final String title;
  final String current;
  final List<String> options;
  final bool unknown;
  final bool includeEmpty;
  final String emptyLabel;
  final bool monospace;

  @override
  State<_SearchDialog> createState() => _SearchDialogState();
}

class _SearchDialogState extends State<_SearchDialog> {
  final _search = TextEditingController();
  final _scroll = ScrollController();
  int _highlight = 0;

  @override
  void initState() {
    super.initState();
    _search.addListener(_onSearch);
  }

  @override
  void dispose() {
    _search.removeListener(_onSearch);
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _onSearch() {
    setState(() => _highlight = 0);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  List<String> get _matches {
    final query = _search.text.trim().toLowerCase();
    final options = <String>[
      if (widget.includeEmpty) '',
      if (widget.unknown) widget.current,
      ...widget.options,
    ];
    return options.where((option) {
      final label = option.isEmpty ? widget.emptyLabel : option;
      return label.toLowerCase().contains(query);
    }).toList();
  }

  void _move(int delta, int length) {
    if (length == 0) return;
    setState(() => _highlight = (_highlight + delta).clamp(0, length - 1));
    if (_scroll.hasClients) {
      _scroll.animateTo(
        (_highlight * 38.0).clamp(0.0, _scroll.position.maxScrollExtent),
        duration: ctMotionFast,
        curve: ctMotionCurve,
      );
    }
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    final matches = _matches;
    if (event.logicalKey == LogicalKeyboardKey.arrowDown) {
      _move(1, matches.length);
      return KeyEventResult.handled;
    }
    if (event.logicalKey == LogicalKeyboardKey.arrowUp) {
      _move(-1, matches.length);
      return KeyEventResult.handled;
    }
    if (event.logicalKey == LogicalKeyboardKey.enter ||
        event.logicalKey == LogicalKeyboardKey.numpadEnter) {
      if (matches.isNotEmpty) {
        Navigator.pop(
          context,
          matches[_highlight.clamp(0, matches.length - 1)],
        );
      }
      return KeyEventResult.handled;
    }
    if (event.logicalKey == LogicalKeyboardKey.escape) {
      Navigator.pop(context);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final matches = _matches;
    return AlertDialog(
      key: ValueKey('${widget.keyPrefix}.dialog'),
      titlePadding: const EdgeInsets.fromLTRB(ctGapLg, ctGapMd, ctGapSm, 0),
      contentPadding: const EdgeInsets.fromLTRB(ctGapLg, ctGapMd, ctGapLg, 0),
      title: Row(
        children: [
          Text(widget.title, style: ctPageTitleStyle),
          const Spacer(),
          IconButton(
            tooltip: '关闭',
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.close, size: 18),
          ),
        ],
      ),
      content: SizedBox(
        width: 520,
        height: 480,
        child: Column(
          children: [
            Focus(
              onKeyEvent: _onKey,
              child: TextField(
                key: ValueKey('${widget.keyPrefix}.search'),
                controller: _search,
                autofocus: true,
                style: ctText(size: ctFontSm),
                decoration: ctInputDecoration().copyWith(
                  hintText: '搜索${widget.title.replaceFirst('选择', '')}…',
                  prefixIcon: const Icon(Icons.search, size: 17),
                  suffixIcon: _search.text.isEmpty
                      ? null
                      : IconButton(
                          tooltip: '清空',
                          onPressed: _search.clear,
                          icon: const Icon(Icons.close, size: 16),
                        ),
                ),
              ),
            ),
            const SizedBox(height: ctGapSm),
            Expanded(
              child: matches.isEmpty
                  ? Center(
                      child: Text(
                        '没有匹配的选项',
                        style: ctText(size: ctFontSm, color: ctInk3),
                      ),
                    )
                  : ListView.builder(
                      key: ValueKey('${widget.keyPrefix}.list'),
                      controller: _scroll,
                      itemCount: matches.length,
                      itemBuilder: (context, index) {
                        final option = matches[index];
                        final selected = option == widget.current;
                        final active = index == _highlight;
                        return InkWell(
                          key: ValueKey('${widget.keyPrefix}.option.$option'),
                          onTap: () => Navigator.pop(context, option),
                          child: Container(
                            height: 38,
                            padding: const EdgeInsets.symmetric(
                              horizontal: ctGapSm,
                            ),
                            decoration: BoxDecoration(
                              color: active
                                  ? ctAccentSofter
                                  : Colors.transparent,
                              borderRadius: ctRadiusSmAll,
                            ),
                            child: Row(
                              children: [
                                SizedBox(
                                  width: 20,
                                  child: selected
                                      ? const Icon(
                                          Icons.check,
                                          size: 15,
                                          color: ctAccent,
                                        )
                                      : null,
                                ),
                                Expanded(
                                  child: Text(
                                    option.isEmpty ? widget.emptyLabel : option,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style:
                                        (widget.monospace
                                                ? ctMono
                                                : ctText(size: ctFontSm))
                                            .copyWith(
                                              fontSize: ctFontSm,
                                              color:
                                                  widget.unknown &&
                                                      option == widget.current
                                                  ? ctDanger
                                                  : selected
                                                  ? ctPrimary
                                                  : ctInk,
                                              fontWeight: selected
                                                  ? FontWeight.w600
                                                  : FontWeight.w400,
                                            ),
                                  ),
                                ),
                                if (widget.unknown && option == widget.current)
                                  Text(
                                    '当前值未识别',
                                    style: ctText(
                                      size: ctFontXs,
                                      color: ctDanger,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
      ],
    );
  }
}
