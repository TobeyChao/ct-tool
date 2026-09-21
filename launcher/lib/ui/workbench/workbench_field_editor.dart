import 'package:flutter/material.dart';

import '../../services/protocol/protocol.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import 'workbench_models.dart';

/// 属性区里的字段/资源编辑器（native-flutter-workbench 任务 3.2）。
///
/// 一切改动只落草稿命令，成败由内核候选裁决：类型表达式、属性名、索引 kind
/// 都不在客户端做白名单校验，只约束输入形态（例如展开组数必须是整数）。
class WorkbenchFieldEditor extends StatefulWidget {
  const WorkbenchFieldEditor({
    super.key,
    required this.resource,
    required this.ownerId,
    this.field,
    this.fieldOrdinal,
    this.namedTypes = const [],
    this.problems = const [],
    this.disabled = false,
    this.hint,
    this.onSetType,
    this.onSetProperty,
    this.onMoveField,
    this.onDeleteField,
    this.onSetIndexes,
    this.onRenameEnumItem,
  });

  final WorkbenchResource resource;

  /// 内核资源 id（`table:Item` 形态）：字段级命令的 owner 必须是它。
  final String ownerId;
  final WorkbenchField? field;

  /// 当前行位置：rename_enum_item 需要 originalOrdinal，move_field 需要来源下标。
  final int? fieldOrdinal;

  /// 可引用的具名类型（取自内核清单里的 record/enum 名，不是客户端造的表）。
  final List<String> namedTypes;

  /// 内核候选里属于当前资源/字段的问题（原文展示）。
  final List<Issue> problems;
  final bool disabled;
  final String? hint;

  final void Function(String typeText)? onSetType;
  final void Function(String property, Object? value)? onSetProperty;
  final void Function(int to)? onMoveField;
  final VoidCallback? onDeleteField;
  final void Function(List<String> kinds)? onSetIndexes;
  final void Function(String newName, int ordinal)? onRenameEnumItem;

  @override
  State<WorkbenchFieldEditor> createState() => _WorkbenchFieldEditorState();
}

class _WorkbenchFieldEditorState extends State<WorkbenchFieldEditor> {
  late final TextEditingController _type = TextEditingController(
    text: widget.field?.type ?? '',
  );
  late final TextEditingController _comment = TextEditingController(
    text: widget.field?.description ?? '',
  );
  late final TextEditingController _ref = TextEditingController(
    text: widget.field?.constraints ?? '',
  );
  late final TextEditingController _columns = TextEditingController(
    text: widget.field?.excelColumns?.toString() ?? '',
  );
  late final TextEditingController _item = TextEditingController(
    text: widget.field?.name ?? '',
  );

  @override
  void initState() {
    super.initState();
    // 输入变化要立刻反映到「是否可提交」上，否则按钮会停在旧状态；
    // 这里只重绘本面板，不做任何校验——合法性始终由内核候选判定。
    for (final c in [_type, _comment, _ref, _columns, _item]) {
      c.addListener(_refresh);
    }
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  @override
  void didUpdateWidget(WorkbenchFieldEditor old) {
    super.didUpdateWidget(old);
    final switched =
        old.resource.name != widget.resource.name ||
        old.field?.name != widget.field?.name;
    if (!switched) return;
    final field = widget.field;
    _type.text = field?.type ?? '';
    _comment.text = field?.description ?? '';
    _ref.text = field?.constraints ?? '';
    _columns.text = field?.excelColumns?.toString() ?? '';
    _item.text = field?.name ?? '';
  }

  @override
  void dispose() {
    for (final c in [_type, _comment, _ref, _columns, _item]) {
      c.removeListener(_refresh);
    }
    _type.dispose();
    _comment.dispose();
    _ref.dispose();
    _columns.dispose();
    _item.dispose();
    super.dispose();
  }

  bool get _locked => widget.disabled;

  /// 分组标题：把一屏散行收成「资源 / 字段属性 / 表级索引 / 危险操作」几段。
  Widget _groupTitle(String text, {required String key}) => Padding(
    padding: const EdgeInsets.fromLTRB(ctGapMd, ctGapMd, ctGapMd, ctGapXs),
    child: Text(
      text,
      key: ValueKey(key),
      style: ctText(
        size: ctFontXs + 0.5,
        color: ctInk3,
        weight: FontWeight.w700,
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final field = widget.field;
    final isEnum = widget.resource.kind == WorkbenchResourceKind.enumType;
    return ListView(
      key: const ValueKey('wb.fieldEditor'),
      padding: const EdgeInsets.only(bottom: ctGapMd),
      children: [
        if (field == null) ..._resourceRows(),
        if (field != null && isEnum) ..._enumItemRows(field),
        if (field != null && !isEnum) ..._fieldRows(field),
        _problemBlock(),
        if (widget.hint != null) _note(widget.hint!),
      ],
    );
  }

  // ---- 资源级 ----

  List<Widget> _resourceRows() {
    final res = widget.resource;
    final primary = _primaryOf(res);
    return [
      _groupTitle('资源', key: 'wb.group.resource'),
      _row('名称', res.name, mono: true),
      _row('类别', res.kind.label),
      _row('资源 ID', widget.ownerId, mono: true),
      _row('路径', res.path, mono: true, multiline: true),
      _row('字段数', '共 ${res.fields.length}'),
      if (res.kind == WorkbenchResourceKind.table)
        _row('主键', primary ?? '未标记', mono: true),
      if (res.kind == WorkbenchResourceKind.table)
        _checkRow(
          key: 'wb.indexCodename',
          label: 'codename 索引',
          value: res.indexes.contains('codename'),
          onChanged: _locked
              ? null
              : (on) => widget.onSetIndexes?.call(
                  on == true ? const ['codename'] : const [],
                ),
          sub:
              '状态取自内核 resources.list；勾选是覆盖式声明，取消即提交移除。'
              '要求存在非 i18n 的 CodeName 字段。',
        ),
    ];
  }

  String? _primaryOf(WorkbenchResource res) {
    for (final field in res.fields) {
      if (field.role == 'primary') return field.name;
    }
    return null;
  }

  // ---- 枚举成员 ----

  List<Widget> _enumItemRows(WorkbenchField field) {
    final ordinal = widget.fieldOrdinal ?? 0;
    final lastOrdinal = widget.resource.fields.length - 1;
    return [
      _groupTitle('枚举成员', key: 'wb.group.enum'),
      _row('枚举', widget.resource.name, mono: true),
      _row('成员', field.name, mono: true),
      _labeled(
        '改成员名',
        _item,
        'wb.enumItemName',
        CtButton.ghost(
          '改名',
          key: const ValueKey('wb.enumItemRename'),
          onPressed: _locked || _item.text.trim().isEmpty
              ? null
              : () {
                  final ordinal = widget.fieldOrdinal;
                  if (ordinal == null) return;
                  widget.onRenameEnumItem?.call(_item.text.trim(), ordinal);
                },
        ),
      ),
      _note('改名带 originalOrdinal：与内核当前顺序不一致时会被直接拒绝。'),
      _groupTitle('危险操作（顺序即 ordinal，会改既有数据 wire 值）', key: 'wb.group.danger'),
      Wrap(
        spacing: ctGapSm,
        children: [
          CtButton.ghost(
            '上移',
            key: const ValueKey('wb.enumItemUp'),
            onPressed: _locked || ordinal <= 0
                ? null
                : () => widget.onMoveField?.call(ordinal - 1),
          ),
          CtButton.ghost(
            '下移',
            key: const ValueKey('wb.enumItemDown'),
            onPressed: _locked || ordinal >= lastOrdinal
                ? null
                : () => widget.onMoveField?.call(ordinal + 2),
          ),
          CtButton.ghost(
            '删除成员',
            key: const ValueKey('wb.enumItemDelete'),
            onPressed: _locked ? null : widget.onDeleteField,
          ),
        ],
      ),
      _note(
        '重排/删除是整表改写 set_enum_values：成员顺序即 ordinal，'
        '会改变既有数据行的 wire 值，内核没有 move_field/delete_field 给 Enum。',
      ),
    ];
  }

  // ---- 字段 ----

  List<Widget> _fieldRows(WorkbenchField field) {
    final ordinal = widget.fieldOrdinal ?? 0;
    return [
      _groupTitle('字段属性', key: 'wb.group.fields'),
      _row('字段', field.name, mono: true),
      _row('角色', field.role == 'primary' ? '主键' : '普通字段'),
      _labeled(
        '类型',
        _type,
        'wb.fieldType',
        CtButton.ghost(
          '改类型',
          key: const ValueKey('wb.setFieldType'),
          onPressed: _locked || _type.text.trim() == field.type
              ? null
              : () => widget.onSetType?.call(_type.text.trim()),
        ),
      ),
      if (widget.namedTypes.isNotEmpty)
        _note('具名类型可引用：${widget.namedTypes.join('、')}'),
      _checkRow(
        key: 'wb.fieldI18n',
        label: '本地化（i18n）',
        value: field.localized,
        onChanged: _locked
            ? null
            : (v) => widget.onSetProperty?.call('i18n', v),
        sub: '只有 string 能标记，且与 server_only 互斥；由内核候选判定。',
      ),
      _checkRow(
        key: 'wb.fieldServerOnly',
        label: '仅服务端（server_only）',
        value: field.serverOnly,
        onChanged: _locked
            ? null
            : (v) => widget.onSetProperty?.call('server_only', v),
      ),
      _labeled(
        '注释',
        _comment,
        'wb.fieldComment',
        CtButton.ghost(
          '写注释',
          key: const ValueKey('wb.setFieldComment'),
          onPressed: _locked || _comment.text == field.description
              ? null
              : () => widget.onSetProperty?.call('comment', _comment.text),
        ),
      ),
      _labeled(
        'ref',
        _ref,
        'wb.fieldRef',
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            CtButton.ghost(
              '设置',
              key: const ValueKey('wb.setFieldRef'),
              onPressed: _locked
                  ? null
                  : () => widget.onSetProperty?.call('ref', _ref.text.trim()),
            ),
            CtButton.ghost(
              '清除',
              key: const ValueKey('wb.clearFieldRef'),
              onPressed: _locked || field.constraints.isEmpty
                  ? null
                  : () => widget.onSetProperty?.call('ref', ''),
            ),
          ],
        ),
      ),
      _labeled(
        '展开组数',
        _columns,
        'wb.fieldColumns',
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            CtButton.ghost(
              '设置',
              key: const ValueKey('wb.setFieldColumns'),
              onPressed: _locked
                  ? null
                  : () => widget.onSetProperty?.call(
                      'excel_columns',
                      int.tryParse(_columns.text.trim()),
                    ),
            ),
            CtButton.ghost(
              '清除',
              key: const ValueKey('wb.clearFieldColumns'),
              onPressed: _locked || field.excelColumns == null
                  ? null
                  : () => widget.onSetProperty?.call('excel_columns', null),
            ),
          ],
        ),
      ),
      _note('展开组数只适用于 vector<T>；类型不符时内核候选会报错并阻止保存。'),
      _groupTitle('危险操作（顺序影响 wire 与 ordinal）', key: 'wb.group.danger'),
      Wrap(
        spacing: ctGapSm,
        children: [
          CtButton.ghost(
            '上移',
            key: const ValueKey('wb.fieldUp'),
            onPressed: _locked || ordinal <= 0 || field.role == 'primary'
                ? null
                : () => widget.onMoveField?.call(ordinal - 1),
          ),
          CtButton.ghost(
            '下移',
            key: const ValueKey('wb.fieldDown'),
            onPressed: _locked || field.role == 'primary'
                ? null
                : () => widget.onMoveField?.call(ordinal + 2),
          ),
          CtButton.ghost(
            '删除字段',
            key: const ValueKey('wb.fieldDelete'),
            onPressed: _locked || field.role == 'primary'
                ? null
                : widget.onDeleteField,
          ),
        ],
      ),
      if (field.role == 'primary') _note('主键不可删除、不可调序；内核没有改主键命令，需要重建表。'),
    ];
  }

  Widget _problemBlock() {
    final problems = widget.problems;
    if (problems.isEmpty) return const SizedBox.shrink();
    return Container(
      key: const ValueKey('wb.fieldProblems'),
      margin: const EdgeInsets.fromLTRB(ctGapLg, ctGapSm, ctGapLg, 0),
      padding: const EdgeInsets.all(ctGapSm),
      decoration: BoxDecoration(
        color: ctDangerSoft,
        borderRadius: ctRadiusSmAll,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '内核候选问题 ${problems.length} 条',
            style: ctText(size: ctFontSm, color: ctDanger),
          ),
          const SizedBox(height: ctGapXs),
          for (final issue in problems)
            Text(
              issue.resource == null
                  ? issue.message
                  : '${issue.message}（${issue.resource}）',
              key: ValueKey('wb.fieldProblem.${issue.message}'),
              style: ctText(size: ctFontXs),
            ),
        ],
      ),
    );
  }

  Widget _labeled(
    String label,
    TextEditingController controller,
    String key,
    Widget action,
  ) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(ctGapLg, ctGapSm, ctGapLg, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: ctText(size: ctFontXs, color: ctInk2),
          ),
          const SizedBox(height: 2),
          Row(
            children: [
              Expanded(
                child: TextField(
                  key: ValueKey(key),
                  controller: controller,
                  enabled: !_locked,
                  style: ctMono.copyWith(fontSize: ctFontSm),
                  decoration: const InputDecoration(
                    isDense: true,
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: ctGapSm),
              action,
            ],
          ),
        ],
      ),
    );
  }

  /// 复选行：属性区在 ColoredBox 内，用 ListTile 会触发 debug 断言。
  Widget _checkRow({
    required String key,
    required String label,
    required bool value,
    required void Function(bool?)? onChanged,
    String? sub,
  }) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(ctGapLg, ctGapSm, ctGapLg, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Checkbox(key: ValueKey(key), value: value, onChanged: onChanged),
              const SizedBox(width: ctGapXs),
              Expanded(
                child: Text(label, style: ctText(size: ctFontSm)),
              ),
            ],
          ),
          if (sub != null)
            Padding(
              padding: const EdgeInsets.only(left: ctGapLg),
              child: Text(
                sub,
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
            ),
        ],
      ),
    );
  }

  Widget _note(String text) => Padding(
    padding: const EdgeInsets.fromLTRB(ctGapLg, ctGapXs, ctGapLg, 0),
    child: Text(
      text,
      style: ctText(size: ctFontXs, color: ctInk3),
    ),
  );

  Widget _row(
    String label,
    String value, {
    bool mono = false,
    bool multiline = false,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapLg,
        vertical: ctGapSm + 2,
      ),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: ctBorder)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 56,
            child: Text(
              label,
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
          ),
          const SizedBox(width: ctGapSm),
          Expanded(
            child: Text(
              value,
              maxLines: multiline ? 4 : 1,
              overflow: TextOverflow.ellipsis,
              style: mono
                  ? ctMono.copyWith(fontSize: ctFontSm, color: ctInk)
                  : ctText(size: ctFontSm, color: ctInk),
            ),
          ),
        ],
      ),
    );
  }
}
