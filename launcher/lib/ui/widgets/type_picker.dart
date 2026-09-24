import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../theme.dart';
import '../tokens.dart';
import 'common.dart';
import 'search_picker.dart';
import 'status_badge.dart';

const ctScalarTypeNames = <String>[
  'int8',
  'uint8',
  'int16',
  'uint16',
  'int32',
  'uint32',
  'int64',
  'uint64',
  'float',
  'double',
  'bool',
  'string',
];

/// 把类型表达式拆成可选择的基础类型与容器开关。
///
/// 只接受内核文法的单层 `vector<T>`；无法识别的内容原样保留在基础类型里，
/// 交给内核候选报错，界面不静默改写用户已有 schema。
({String base, bool vector}) ctSplitTypeExpression(String value) {
  final text = value.trim();
  if (text.startsWith('vector<') && text.endsWith('>')) {
    final element = text.substring('vector<'.length, text.length - 1).trim();
    if (element.isNotEmpty && !element.contains('vector<')) {
      return (base: element, vector: true);
    }
  }
  return (base: text, vector: false);
}

String ctJoinTypeExpression({required String base, required bool vector}) {
  final name = base.trim();
  return vector ? 'vector<$name>' : name;
}

/// 打开类型选择器并返回完整类型表达式；取消返回 null。
Future<String?> showCtTypePickerDialog(
  BuildContext context, {
  required String value,
  required List<String> namedTypes,
  String keyPrefix = 'ct.type',
}) async {
  final parsed = ctSplitTypeExpression(value);
  final named = {...namedTypes}.toList()..sort();
  final known = <String>{...ctScalarTypeNames, ...named};
  final base = parsed.base.isEmpty ? 'int32' : parsed.base;
  final unknown = base.isNotEmpty && !known.contains(base) ? base : null;
  final picked = await showDialog<String>(
    context: context,
    builder: (dialogContext) => _TypeSearchDialog(
      keyPrefix: keyPrefix,
      current: base,
      namedTypes: named,
      unknown: unknown,
    ),
  );
  if (picked == null) return null;
  return ctJoinTypeExpression(base: picked, vector: parsed.vector);
}

/// 类型表达式选择器：基础类型用可搜索列表，`vector<T>` 保留显式开关。
///
/// 具名类型必须来自当前工作区资源清单中的 Record / Enum；没有可靠清单时
/// 不展示“自由输入”兜底，避免再次把非法类型直接写进草稿。
class CtTypePicker extends StatelessWidget {
  const CtTypePicker({
    super.key,
    required this.value,
    required this.namedTypes,
    required this.onChanged,
    this.enabled = true,
    this.keyPrefix = 'ct.type',
  });

  final String value;
  final List<String> namedTypes;
  final ValueChanged<String> onChanged;
  final bool enabled;
  final String keyPrefix;

  @override
  Widget build(BuildContext context) {
    final parsed = ctSplitTypeExpression(value);
    final named = {...namedTypes}.toList()..sort();
    final known = <String>{...ctScalarTypeNames, ...named};
    final base = parsed.base.isEmpty ? 'int32' : parsed.base;
    final unknown = base.isNotEmpty && !known.contains(base) ? base : null;
    final display = ctJoinTypeExpression(base: base, vector: parsed.vector);

    return Row(
      children: [
        Expanded(
          child: Material(
            color: ctSurface,
            borderRadius: ctRadiusSmAll,
            child: InkWell(
              key: ValueKey('$keyPrefix.base'),
              onTap: !enabled
                  ? null
                  : () async {
                      final picked = await showCtTypePickerDialog(
                        context,
                        value: value,
                        namedTypes: named,
                        keyPrefix: keyPrefix,
                      );
                      if (picked != null) onChanged(picked);
                    },
              borderRadius: ctRadiusSmAll,
              child: Container(
                height: 36,
                padding: const EdgeInsets.symmetric(horizontal: 10),
                decoration: BoxDecoration(
                  border: Border.all(
                    color: enabled ? ctBorderStrong : ctBorder,
                  ),
                  borderRadius: ctRadiusSmAll,
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        display,
                        key: ValueKey('$keyPrefix.value'),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: ctMono.copyWith(
                          fontSize: ctFontSm,
                          color: enabled
                              ? (unknown == null ? ctInk : ctDanger)
                              : ctInk3,
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
          ),
        ),
        const SizedBox(width: ctGapSm),
        CtChoicePill(
          key: ValueKey('$keyPrefix.vector'),
          label: 'vector<T>',
          selected: parsed.vector,
          minWidth: 88,
          tooltip: '切换为 vector<T> 容器类型',
          onTap: !enabled
              ? null
              : () => onChanged(
                  ctJoinTypeExpression(base: base, vector: !parsed.vector),
                ),
        ),
      ],
    );
  }
}

class _TypeRow {
  const _TypeRow.header(this.title) : value = null;
  const _TypeRow.option(this.value) : title = null;

  final String? title;
  final String? value;
}

class _TypeSearchDialog extends StatefulWidget {
  const _TypeSearchDialog({
    required this.keyPrefix,
    required this.current,
    required this.namedTypes,
    required this.unknown,
  });

  final String keyPrefix;
  final String current;
  final List<String> namedTypes;
  final String? unknown;

  @override
  State<_TypeSearchDialog> createState() => _TypeSearchDialogState();
}

class _TypeSearchDialogState extends State<_TypeSearchDialog> {
  final _search = TextEditingController();
  final _scroll = ScrollController();
  int _highlight = 0;

  @override
  void initState() {
    super.initState();
    _search.addListener(_onQueryChanged);
  }

  @override
  void dispose() {
    _search
      ..removeListener(_onQueryChanged)
      ..dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _onQueryChanged() {
    setState(() => _highlight = 0);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  List<_TypeRow> get _rows {
    final query = _search.text.trim().toLowerCase();
    bool matches(String value) =>
        query.isEmpty || value.toLowerCase().contains(query);

    final rows = <_TypeRow>[];
    void addGroup(String title, Iterable<String> values) {
      final filtered = values.where(matches).toList(growable: false);
      if (filtered.isEmpty) return;
      rows.add(_TypeRow.header(title));
      for (final value in filtered) {
        rows.add(_TypeRow.option(value));
      }
    }

    if (widget.unknown != null) {
      addGroup('当前值', [widget.unknown!]);
    }
    addGroup('标量', ctScalarTypeNames);
    addGroup('工作区具名类型', widget.namedTypes);
    return rows;
  }

  List<String> get _choices => [
    for (final row in _rows)
      if (row.value != null) row.value!,
  ];

  void _moveHighlight(int delta) {
    final choices = _choices;
    if (choices.isEmpty) return;
    final next = (_highlight + delta).clamp(0, choices.length - 1);
    if (next == _highlight) return;
    setState(() => _highlight = next);
    _scrollTo(choices[next]);
  }

  void _scrollTo(String choice) {
    if (!_scroll.hasClients) return;
    final rows = _rows;
    final rowIndex = rows.indexWhere((row) => row.value == choice);
    if (rowIndex < 0) return;
    final target = (rowIndex * 38.0).clamp(
      0.0,
      _scroll.position.maxScrollExtent,
    );
    _scroll.animateTo(target, duration: ctMotionFast, curve: ctMotionCurve);
  }

  void _chooseHighlighted() {
    final choices = _choices;
    if (choices.isEmpty) return;
    Navigator.pop(context, choices[_highlight.clamp(0, choices.length - 1)]);
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) return KeyEventResult.ignored;
    return switch (event.logicalKey) {
      LogicalKeyboardKey.arrowDown => () {
        _moveHighlight(1);
        return KeyEventResult.handled;
      }(),
      LogicalKeyboardKey.arrowUp => () {
        _moveHighlight(-1);
        return KeyEventResult.handled;
      }(),
      LogicalKeyboardKey.enter || LogicalKeyboardKey.numpadEnter => () {
        _chooseHighlighted();
        return KeyEventResult.handled;
      }(),
      LogicalKeyboardKey.escape => () {
        Navigator.pop(context);
        return KeyEventResult.handled;
      }(),
      _ => KeyEventResult.ignored,
    };
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows;
    final choices = _choices;
    final highlighted = choices.isEmpty
        ? null
        : choices[_highlight.clamp(0, choices.length - 1)];

    return AlertDialog(
      key: ValueKey('${widget.keyPrefix}.dialog'),
      titlePadding: const EdgeInsets.fromLTRB(ctGapLg, ctGapMd, ctGapSm, 0),
      contentPadding: const EdgeInsets.fromLTRB(ctGapLg, ctGapMd, ctGapLg, 0),
      title: Row(
        children: [
          Text('选择类型', style: ctPageTitleStyle),
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
                  hintText: '搜索类型…',
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
              child: rows.isEmpty
                  ? Center(
                      child: Text(
                        '没有匹配的类型',
                        style: ctText(size: ctFontSm, color: ctInk3),
                      ),
                    )
                  : ListView.builder(
                      key: ValueKey('${widget.keyPrefix}.list'),
                      controller: _scroll,
                      padding: EdgeInsets.zero,
                      itemCount: rows.length,
                      itemBuilder: (context, index) {
                        final row = rows[index];
                        if (row.title case final title?) {
                          return Container(
                            height: 30,
                            padding: const EdgeInsets.symmetric(
                              horizontal: ctGapSm,
                            ),
                            alignment: Alignment.centerLeft,
                            child: Text(
                              title,
                              style: ctText(
                                size: ctFontXs,
                                color: ctInk3,
                                weight: FontWeight.w700,
                              ),
                            ),
                          );
                        }
                        final value = row.value!;
                        final selected = value == widget.current;
                        final active = value == highlighted;
                        return InkWell(
                          key: ValueKey('${widget.keyPrefix}.option.$value'),
                          onTap: () => Navigator.pop(context, value),
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
                                    value,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: ctMono.copyWith(
                                      fontSize: ctFontSm,
                                      color: selected ? ctPrimary : ctInk,
                                      fontWeight: selected
                                          ? FontWeight.w600
                                          : FontWeight.w400,
                                    ),
                                  ),
                                ),
                                if (selected)
                                  const CtStatusBadge(
                                    label: '当前',
                                    tone: CtBadgeTone.info,
                                    dot: false,
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

/// `ref` 目标：只允许内核声明的「表.主键」形态。
class CtReferencePicker extends StatelessWidget {
  const CtReferencePicker({
    super.key,
    required this.value,
    required this.targets,
    required this.onChanged,
    this.enabled = true,
    this.keyPrefix = 'ct.ref',
  });

  final String value;
  final List<String> targets;
  final ValueChanged<String> onChanged;
  final bool enabled;
  final String keyPrefix;

  @override
  Widget build(BuildContext context) => CtSearchPicker(
    value: value,
    options: targets,
    onChanged: onChanged,
    title: '选择引用',
    keyPrefix: keyPrefix,
    emptyLabel: '未引用',
    enabled: enabled,
    monospace: true,
  );
}
