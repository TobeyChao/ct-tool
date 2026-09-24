import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/protocol/protocol.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/status_badge.dart';
import '../widgets/type_picker.dart';
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
    this.referenceTargets = const [],
    this.problems = const [],
    this.disabled = false,
    this.disabledHint,
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

  /// 可设置的 `ref` 目标（表.主键，全部取自当前内核清单）。
  final List<String> referenceTargets;

  /// 内核候选里属于当前资源/字段的问题（原文展示）。
  final List<Issue> problems;
  final bool disabled;

  /// 禁用态的可解释原因：开关仍可见，但 hover 与开关下方都要说明为什么点不了。
  final String? disabledHint;
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
  late final TextEditingController _comment = TextEditingController(
    text: widget.field?.description ?? '',
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
    for (final c in [_comment, _columns, _item]) {
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
    _comment.text = field?.description ?? '';
    _columns.text = field?.excelColumns?.toString() ?? '';
    _item.text = field?.name ?? '';
  }

  @override
  void dispose() {
    for (final c in [_comment, _columns, _item]) {
      c.removeListener(_refresh);
    }
    _comment.dispose();
    _columns.dispose();
    _item.dispose();
    super.dispose();
  }

  bool get _locked => widget.disabled;

  TextStyle get _styleLabel =>
      ctText(size: ctFontXs, color: ctInk2, weight: FontWeight.w500);

  /// 面板身份块：字段/资源名 + 副标题 + 标记，作为第一张卡片的正文。
  Widget _identityHeader({
    required String title,
    String? subtitle,
    List<Widget> badges = const [],
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: ctText(size: ctFontMd, weight: FontWeight.w700, height: 1.2),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 3),
          Text(
            subtitle,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: ctMono.copyWith(fontSize: ctFontXs, color: ctInk3),
          ),
        ],
        if (badges.isNotEmpty) ...[
          const SizedBox(height: ctGapSm),
          Wrap(spacing: 6, runSpacing: 6, children: badges),
        ],
      ],
    );
  }

  /// 属性区的一张卡片：与设置页同一个外观（见 [CtGroupCard]），左右留出面板内边距。
  Widget _card({
    Key? key,
    String? title,
    String? description,
    required List<Widget> children,
  }) => Padding(
    padding: const EdgeInsets.fromLTRB(ctGapMd, 0, ctGapMd, ctGapSm),
    child: CtGroupCard(
      key: key,
      title: title,
      description: description,
      children: children,
    ),
  );

  Widget _iconAction({
    required String key,
    required IconData icon,
    required String tooltip,
    VoidCallback? onPressed,
  }) => SizedBox(
    width: 32,
    height: 32,
    child: IconButton(
      key: ValueKey(key),
      icon: Icon(icon, size: 16),
      tooltip: tooltip,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
      onPressed: onPressed,
    ),
  );

  @override
  Widget build(BuildContext context) {
    final field = widget.field;
    final isEnum = widget.resource.kind == WorkbenchResourceKind.enumType;
    return ListView(
      key: const ValueKey('wb.fieldEditor'),
      padding: const EdgeInsets.only(top: ctGapSm, bottom: ctGapMd),
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
    final isTable = res.kind == WorkbenchResourceKind.table;
    return [
      _card(
        children: [
          _identityHeader(
            title: res.name,
            subtitle: widget.ownerId,
            badges: [
              CtStatusBadge(
                label: res.kind.label,
                tone: CtBadgeTone.info,
                dot: false,
              ),
            ],
          ),
        ],
      ),
      _card(
        title: '资源',
        children: [
          _row('路径', res.path, mono: true, multiline: true),
          _row('字段数', '${res.fields.length}'),
          if (isTable) _row('主键', primary ?? '未标记', mono: true),
          if (isTable)
            _toggleRow(
              key: 'wb.indexCodename',
              label: 'codename 索引',
              value: res.indexes.contains('codename'),
              onChanged: _locked
                  ? null
                  : (on) => widget.onSetIndexes?.call(
                      on ? const ['codename'] : const [],
                    ),
              disabledHint: widget.disabledHint,
            ),
        ],
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
      _card(
        children: [
          _identityHeader(
            title: field.name,
            subtitle: 'ordinal $ordinal',
            badges: const [
              CtStatusBadge(label: '枚举成员', tone: CtBadgeTone.info, dot: false),
            ],
          ),
        ],
      ),
      _card(
        title: '名称',
        children: [
          _inlineEdit(
            fieldKey: 'wb.enumItemName',
            controller: _item,
            dirty: _item.text.trim() != field.name,
            onSave: _item.text.trim().isEmpty ? null : _saveItemName,
            onRevert: _revertItemName,
            revertKey: 'wb.revertEnumItemName',
            saveKey: 'wb.enumItemRename',
            saveTooltip: '应用改名（Enter）',
            errorText: _item.text.trim().isEmpty ? '名称不能为空' : null,
          ),
        ],
      ),
      _card(
        key: const ValueKey('wb.group.danger'),
        title: '危险操作',
        description: '顺序即 ordinal，重排或删除会改变 wire 值。',
        children: [
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
                    : () => widget.onMoveField?.call(ordinal + 1),
              ),
              CtButton.ghost(
                '删除成员',
                key: const ValueKey('wb.enumItemDelete'),
                onPressed: _locked ? null : widget.onDeleteField,
              ),
            ],
          ),
        ],
      ),
    ];
  }

  // ---- 字段 ----

  List<Widget> _fieldRows(WorkbenchField field) {
    final ordinal = widget.fieldOrdinal ?? 0;
    final lastOrdinal = widget.resource.fields.length - 1;
    final primary = field.role == 'primary' || field.role == '主键';
    final isVector = ctSplitTypeExpression(field.type).vector;
    return [
      _card(
        children: [
          _identityHeader(
            title: field.name,
            subtitle: 'ordinal $ordinal',
            badges: [
              CtStatusBadge(
                label: primary ? '主键' : '普通字段',
                tone: primary ? CtBadgeTone.info : CtBadgeTone.neutral,
                dot: false,
              ),
              if (field.localized)
                const CtStatusBadge(
                  label: '本地化',
                  tone: CtBadgeTone.busy,
                  dot: false,
                ),
              if (field.serverOnly)
                const CtStatusBadge(
                  label: '服务端',
                  tone: CtBadgeTone.neutral,
                  dot: false,
                ),
            ],
          ),
        ],
      ),
      _card(title: '类型', children: [_typeControl(field)]),
      _card(
        title: '标记',
        children: [
          _toggleRow(
            key: 'wb.fieldI18n',
            label: '本地化（i18n）',
            value: field.localized,
            onChanged: _locked
                ? null
                : (v) => widget.onSetProperty?.call('i18n', v),
            disabledHint: widget.disabledHint,
          ),
          _toggleRow(
            key: 'wb.fieldServerOnly',
            label: '仅服务端（server_only）',
            value: field.serverOnly,
            onChanged: _locked
                ? null
                : (v) => widget.onSetProperty?.call('server_only', v),
            disabledHint: widget.disabledHint,
          ),
        ],
      ),
      _card(title: '注释', children: [_commentRow(field)]),
      _card(title: '引用', children: [_referenceControl(field)]),
      if (isVector || field.excelColumns != null)
        _card(title: 'Excel 展开', children: _excelColumnsItems(field)),
      _card(
        key: const ValueKey('wb.group.danger'),
        title: '危险操作',
        description: primary ? '主键不可删除、不可调序；需要重建表改主键。' : '顺序影响 wire 与 ordinal。',
        children: [
          Wrap(
            spacing: ctGapSm,
            children: [
              CtButton.ghost(
                '上移',
                key: const ValueKey('wb.fieldUp'),
                onPressed: _locked || ordinal <= 0 || primary
                    ? null
                    : () => widget.onMoveField?.call(ordinal - 1),
              ),
              CtButton.ghost(
                '下移',
                key: const ValueKey('wb.fieldDown'),
                onPressed: _locked || primary || ordinal >= lastOrdinal
                    ? null
                    : () => widget.onMoveField?.call(ordinal + 1),
              ),
              CtButton.ghost(
                '删除字段',
                key: const ValueKey('wb.fieldDelete'),
                onPressed: _locked || primary ? null : widget.onDeleteField,
              ),
            ],
          ),
        ],
      ),
    ];
  }

  /// 类型选择器本身：标签由卡片抬头给，这里只留控件。
  Widget _typeControl(WorkbenchField field) => CtTypePicker(
    value: field.type,
    namedTypes: widget.namedTypes,
    enabled: !_locked,
    keyPrefix: 'wb.fieldType',
    onChanged: (value) => widget.onSetType?.call(value),
  );

  /// 注释：多行输入；只有相对内核草稿值有变更时才出现「还原 / 保存」两个动作。
  Widget _commentRow(WorkbenchField field) => _inlineEdit(
    fieldKey: 'wb.fieldComment',
    controller: _comment,
    dirty: _comment.text != field.description,
    onSave: _saveComment,
    onRevert: _revertComment,
    revertKey: 'wb.revertFieldComment',
    saveKey: 'wb.setFieldComment',
    saveTooltip: '保存注释（Ctrl+Enter）',
    hintText: '字段注释，可多行',
    multiline: true,
  );

  /// Excel 展开：勾选才给组数输入，取消勾选即清掉 excel_columns。
  ///
  /// 组数只收 1~64 的整数：输入层挡掉非数字，越界由下方提示说明并禁用保存。
  List<Widget> _excelColumnsItems(WorkbenchField field) {
    final saved = field.excelColumns?.toString() ?? '';
    final text = _columns.text.trim();
    final value = int.tryParse(text);
    final valid = value != null && value >= 1 && value <= 64;
    return [
      _toggleRow(
        key: 'wb.fieldExpand',
        label: '拆成多列（excel_columns）',
        value: field.excelColumns != null,
        onChanged: _locked ? null : _toggleExpand,
        disabledHint: widget.disabledHint,
      ),
      if (field.excelColumns != null)
        _inlineEdit(
          label: '展开组数',
          fieldKey: 'wb.fieldColumns',
          controller: _columns,
          dirty: text != saved,
          onSave: valid ? _saveColumns : null,
          onRevert: _revertColumns,
          revertKey: 'wb.revertFieldColumns',
          saveKey: 'wb.setFieldColumns',
          saveTooltip: '保存展开组数（Enter）',
          hintText: '1~64',
          errorText: valid ? null : '只能填 1~64 的整数',
          keyboardType: TextInputType.number,
        ),
    ];
  }

  void _saveComment() {
    final text = _comment.text;
    if (text == widget.field?.description) return;
    widget.onSetProperty?.call('comment', text);
  }

  void _revertComment() => _restore(_comment, widget.field?.description ?? '');

  void _toggleExpand(bool on) {
    if (!on) {
      widget.onSetProperty?.call('excel_columns', null);
      return;
    }
    // 勾选后输入框必须马上有一个合法值：沿用上次填的数，否则退回最小值。
    final typed = int.tryParse(_columns.text.trim());
    final value = typed != null && typed >= 1 && typed <= 64 ? typed : 1;
    _restore(_columns, value.toString());
    widget.onSetProperty?.call('excel_columns', value);
  }

  void _saveColumns() {
    final value = int.tryParse(_columns.text.trim());
    if (value == null || value < 1 || value > 64) return;
    if (value == widget.field?.excelColumns) return;
    widget.onSetProperty?.call('excel_columns', value);
  }

  void _revertColumns() =>
      _restore(_columns, widget.field?.excelColumns?.toString() ?? '');

  void _saveItemName() {
    final ordinal = widget.fieldOrdinal;
    final name = _item.text.trim();
    if (ordinal == null || name.isEmpty || name == widget.field?.name) return;
    widget.onRenameEnumItem?.call(name, ordinal);
  }

  void _revertItemName() => _restore(_item, widget.field?.name ?? '');

  /// 还原文本并把光标收到末尾，避免还原后停在越界位置。
  void _restore(TextEditingController controller, String text) {
    controller.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
  }

  /// 行内编辑行：可选的标签 + 输入框 + 「有改动才出现」的还原/保存动作，错误提示另起一行。
  ///
  /// 注释、枚举成员名、展开组数共用这一套排版与键位，属性区里不留第二种编辑习惯。
  Widget _inlineEdit({
    String? label,
    required String fieldKey,
    required TextEditingController controller,
    required bool dirty,
    required VoidCallback? onSave,
    required VoidCallback onRevert,
    required String revertKey,
    required String saveKey,
    required String saveTooltip,
    String? hintText,
    String? errorText,
    bool multiline = false,
    TextInputType? keyboardType,
  }) {
    final save = onSave;
    final enabled = !_locked && dirty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (label != null) ...[
          Text(label, style: _styleLabel),
          const SizedBox(height: ctGapXs),
        ],
        Row(
          // 动作贴首行：输入框变高时按钮不跟着往下漂。
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: CallbackShortcuts(
                bindings: {
                  // 多行里 Enter 归换行，保存得带修饰键；单行直接 Enter 保存。
                  if (enabled && save != null) ...{
                    if (multiline)
                      const SingleActivator(
                        LogicalKeyboardKey.enter,
                        control: true,
                      ): save,
                    if (multiline)
                      const SingleActivator(
                        LogicalKeyboardKey.enter,
                        meta: true,
                      ): save,
                    if (!multiline)
                      const SingleActivator(LogicalKeyboardKey.enter): save,
                  },
                  if (enabled)
                    const SingleActivator(LogicalKeyboardKey.escape): onRevert,
                },
                child: TextField(
                  key: ValueKey(fieldKey),
                  controller: controller,
                  enabled: !_locked,
                  minLines: 1,
                  maxLines: multiline ? 4 : 1,
                  keyboardType:
                      keyboardType ??
                      (multiline ? TextInputType.multiline : null),
                  textInputAction: multiline ? TextInputAction.newline : null,
                  inputFormatters: [
                    if (keyboardType == TextInputType.number)
                      FilteringTextInputFormatter.digitsOnly,
                  ],
                  style: ctMono.copyWith(fontSize: ctFontSm),
                  decoration: ctInputDecoration().copyWith(
                    hintText: hintText,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: ctGapSm,
                      vertical: 8,
                    ),
                  ),
                ),
              ),
            ),
            if (dirty) ...[
              const SizedBox(width: ctGapXs),
              _iconAction(
                key: revertKey,
                icon: Icons.close,
                tooltip: '还原（Esc）',
                onPressed: _locked ? null : onRevert,
              ),
              _iconAction(
                key: saveKey,
                icon: Icons.check,
                tooltip: saveTooltip,
                onPressed: _locked ? null : save,
              ),
            ],
          ],
        ),
        if (errorText != null)
          Padding(
            padding: const EdgeInsets.only(top: ctGapXs),
            child: Text(
              errorText,
              key: ValueKey('$fieldKey.error'),
              style: ctText(size: ctFontXs, color: ctDanger),
            ),
          ),
      ],
    );
  }

  /// 引用选择器本身：标签由卡片抬头给，这里只留控件。
  Widget _referenceControl(WorkbenchField field) => CtReferencePicker(
    value: field.constraints,
    targets: widget.referenceTargets,
    enabled: !_locked,
    keyPrefix: 'wb.fieldRef',
    onChanged: (value) => widget.onSetProperty?.call('ref', value),
  );

  Widget _problemBlock() {
    final problems = widget.problems;
    if (problems.isEmpty) return const SizedBox.shrink();
    return Container(
      key: const ValueKey('wb.fieldProblems'),
      margin: const EdgeInsets.fromLTRB(ctGapMd, 0, ctGapMd, ctGapSm),
      padding: const EdgeInsets.all(ctGapSm),
      decoration: BoxDecoration(
        color: ctDangerSoft,
        borderRadius: ctRadiusLgAll,
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

  /// 布尔行：标签在左、统一的 [CtCheckbox] 在右，禁用原因仅在需要时展开一行。
  Widget _toggleRow({
    required String key,
    required String label,
    required bool value,
    required ValueChanged<bool>? onChanged,
    String? disabledHint,
  }) {
    final lockHint = onChanged == null ? (disabledHint ?? '当前不可修改，稍后重试') : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: ctText(size: ctFontSm, color: ctInk),
              ),
            ),
            CtCheckbox(
              key: ValueKey(key),
              value: value,
              onChanged: onChanged,
              tooltip: lockHint == null ? label : null,
            ),
          ],
        ),
        if (lockHint != null)
          Padding(
            padding: const EdgeInsets.only(top: ctGapXs),
            child: Text(
              '当前不可修改：$lockHint',
              key: ValueKey('$key.disabledHint'),
              style: ctText(size: ctFontXs, color: ctWarn),
            ),
          ),
      ],
    );
  }

  Widget _note(String text) => Padding(
    padding: const EdgeInsets.fromLTRB(ctGapMd, ctGapXs, ctGapMd, 0),
    child: Text(
      text,
      style: ctText(size: ctFontXs, color: ctInk3),
    ),
  );

  /// 卡片里的只读行：固定标签列 + 值，内边距与分隔线由卡片给。
  Widget _row(
    String label,
    String value, {
    bool mono = false,
    bool multiline = false,
  }) {
    return Row(
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
    );
  }
}
