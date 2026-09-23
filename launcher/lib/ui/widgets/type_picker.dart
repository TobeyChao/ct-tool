import 'package:flutter/material.dart';

import '../../theme.dart';
import '../tokens.dart';
import 'common.dart';

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

/// 类型表达式选择器：基础类型用下拉，`vector<T>` 用显式开关。
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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: InputDecorator(
                decoration: ctInputDecoration().copyWith(
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: ctGapSm,
                    vertical: 2,
                  ),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    key: ValueKey('$keyPrefix.base'),
                    value: base,
                    isExpanded: true,
                    isDense: true,
                    hint: Text(
                      '选择类型',
                      style: ctText(size: ctFontSm, color: ctInk3),
                    ),
                    items: [
                      if (unknown != null)
                        DropdownMenuItem(
                          value: unknown,
                          child: Text(
                            '$unknown（当前值未识别）',
                            overflow: TextOverflow.ellipsis,
                            style: ctMono.copyWith(
                              fontSize: ctFontSm,
                              color: ctDanger,
                            ),
                          ),
                        ),
                      const DropdownMenuItem<String>(
                        enabled: false,
                        child: _TypeMenuHeader('标量'),
                      ),
                      for (final name in ctScalarTypeNames)
                        DropdownMenuItem(
                          value: name,
                          child: Text(
                            name,
                            style: ctMono.copyWith(fontSize: ctFontSm),
                          ),
                        ),
                      if (named.isNotEmpty) ...[
                        const DropdownMenuItem<String>(
                          enabled: false,
                          child: _TypeMenuHeader('工作区具名类型'),
                        ),
                        for (final name in named)
                          DropdownMenuItem(
                            value: name,
                            child: Text(
                              name,
                              style: ctMono.copyWith(fontSize: ctFontSm),
                            ),
                          ),
                      ],
                    ],
                    onChanged: !enabled
                        ? null
                        : (next) {
                            if (next == null) return;
                            onChanged(
                              ctJoinTypeExpression(
                                base: next,
                                vector: parsed.vector,
                              ),
                            );
                          },
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
        ),
        const SizedBox(height: ctGapXs),
        Text(
          '实际写入：${ctJoinTypeExpression(base: base, vector: parsed.vector)}',
          key: ValueKey('$keyPrefix.preview'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
        ),
      ],
    );
  }
}

class _TypeMenuHeader extends StatelessWidget {
  const _TypeMenuHeader(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Text(
      label,
      style: ctText(size: ctFontXs, color: ctInk3, weight: FontWeight.w700),
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
  Widget build(BuildContext context) {
    final known = {...targets}.toList()..sort();
    final current = value.trim();
    final unknown = current.isNotEmpty && !known.contains(current)
        ? current
        : null;

    return InputDecorator(
      decoration: ctInputDecoration().copyWith(
        contentPadding: const EdgeInsets.symmetric(
          horizontal: ctGapSm,
          vertical: 2,
        ),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          key: ValueKey('$keyPrefix.picker'),
          value: current,
          isExpanded: true,
          isDense: true,
          hint: Text(
            known.isEmpty ? '没有可引用的表' : '选择目标表.主键',
            style: ctText(size: ctFontSm, color: ctInk3),
          ),
          items: [
            const DropdownMenuItem(value: '', child: Text('（未引用）')),
            if (unknown != null)
              DropdownMenuItem(
                value: unknown,
                child: Text(
                  '$unknown（当前值未识别）',
                  overflow: TextOverflow.ellipsis,
                  style: ctMono.copyWith(fontSize: ctFontSm, color: ctDanger),
                ),
              ),
            for (final target in known)
              DropdownMenuItem(
                value: target,
                child: Text(target, style: ctMono.copyWith(fontSize: ctFontSm)),
              ),
          ],
          onChanged: !enabled || known.isEmpty
              ? null
              : (next) {
                  if (next == null) return;
                  onChanged(next);
                },
        ),
      ),
    );
  }
}
