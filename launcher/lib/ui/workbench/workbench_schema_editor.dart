import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../state/schema_draft.dart';
import '../../state/workbench_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import '../widgets/common.dart';
import '../widgets/type_picker.dart';
import 'workbench_draft_bar.dart' show confirmWorkbenchDiscard;
import 'workbench_models.dart';

/// 资源栏菜单和工作区空态共用的创建入口；只加入 Schema 草稿。
Future<void> createWorkbenchResource(
  BuildContext context, {
  required WorkbenchRepository repo,
  required String kind,
  ValueChanged<String?>? onResourceSelected,
}) async {
  if (repo.busy) return;
  if (repo.workspaceRoot.isEmpty) {
    showCtToast(context, '请先在设置中绑定配表工作区');
    return;
  }
  final title = switch (kind) {
    'table' => '新建 Table',
    'record' => '新建 Record',
    'enum' => '新建 Enum',
    _ => throw ArgumentError.value(kind, 'kind'),
  };
  final answer = await WorkbenchSchemaEditor._ask(context, title: title);
  if (answer == null ||
      !context.mounted ||
      repo.busy ||
      repo.workspaceRoot.isEmpty) {
    return;
  }
  switch (kind) {
    case 'table':
      repo.createTable(answer.name);
    case 'record':
      repo.createRecord(answer.name);
    case 'enum':
      repo.createEnum(answer.name);
  }
  onResourceSelected?.call(answer.name);
}

/// 资源与字段的草稿操作面板（native-flutter-workbench 任务 3.1）。
///
/// 只做两件事：把用户动作拼成内核词表里的命令入草稿，并用 `schema.candidate`
/// 让内核判定这批命令（客户端不自创校验规则）。保存动作在 3.4 接入。
class WorkbenchSchemaEditor extends StatelessWidget {
  const WorkbenchSchemaEditor({
    super.key,
    required this.repo,
    this.selected,
    this.onResourceSelected,
  });

  final WorkbenchRepository repo;
  final String? selected;
  final ValueChanged<String?>? onResourceSelected;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(ctGapMd, ctGapSm, ctGapMd, ctGapSm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _menu(
                context,
                keyName: 'wb.newMenu',
                label: '新建',
                tooltip: '新建资源（只入草稿，保存前不写文件）',
                enabled: !repo.busy,
                items: [
                  ('table', Icons.add, '表', 'wb.newTable'),
                  ('record', Icons.data_object, '记录', 'wb.newRecord'),
                  ('enum', Icons.category, '枚举', 'wb.newEnum'),
                ],
                onPick: (value) => _create(context, value),
              ),
            ],
          ),
          const SizedBox(height: ctGapSm),
          _draftRow(context),
          _candidateRow(),
        ],
      ),
    );
  }

  /// 收进菜单的动作项：keyName 挂在条目文字上，菜单打开后可被测试/键盘定位。
  Widget _menu(
    BuildContext context, {
    required String keyName,
    required String label,
    required String tooltip,
    required List<(String, IconData, String, String)> items,
    required void Function(String) onPick,
    bool enabled = true,
  }) => PopupMenuButton<String>(
    key: ValueKey(keyName),
    enabled: enabled,
    tooltip: tooltip,
    position: PopupMenuPosition.under,
    popUpAnimationStyle: ctMenuAnimationStyle,
    itemBuilder: (context) => [
      for (final (value, icon, text, itemKey) in items)
        PopupMenuItem<String>(
          value: value,
          child: Row(
            children: [
              Icon(icon, size: 15, color: ctPrimary),
              const SizedBox(width: ctGapSm),
              Text(
                text,
                key: ValueKey(itemKey),
                style: ctText(size: ctFontSm),
              ),
            ],
          ),
        ),
    ],
    onSelected: onPick,
    child: Container(
      padding: const EdgeInsets.symmetric(
        horizontal: ctGapSm + 2,
        vertical: ctGapSm,
      ),
      decoration: BoxDecoration(
        border: Border.all(color: enabled ? ctBorderStrong : ctBorder),
        borderRadius: ctRadiusSmAll,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.more_horiz, size: 15, color: enabled ? ctPrimary : ctInk3),
          const SizedBox(width: 4),
          Text(
            label,
            style: ctText(size: ctFontSm, color: enabled ? ctInk : ctInk3),
          ),
        ],
      ),
    ),
  );

  Widget _draftRow(BuildContext context) {
    final hasEditableState =
        repo.hasDraft ||
        repo.canUndo ||
        repo.canRedo ||
        repo.candidate != null ||
        repo.candidateBusy ||
        repo.refreshError != null;
    if (!hasEditableState) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              "草稿 ${repo.draftCount} 条",
              key: const ValueKey('wb.draftCount'),
              style: ctText(size: ctFontSm, color: ctInk2),
            ),
            const Spacer(),
            Flexible(
              child: Text(
                "落盘：${repo.draftPersistLabel}",
                key: const ValueKey('wb.draftPersistState'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: ctText(size: ctFontXs, color: ctInk3),
              ),
            ),
          ],
        ),
        if (repo.refreshError != null)
          Text(
            repo.refreshError!,
            key: const ValueKey('wb.refreshError'),
            style: ctText(size: ctFontXs, color: ctWarn),
          ),
        const SizedBox(height: 2),
        Wrap(
          spacing: 2,
          runSpacing: 2,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            _mini(
              'wb.undo',
              Icons.undo,
              '撤销',
              repo.canUndo && !repo.busy ? repo.undoDraft : null,
            ),
            _mini(
              'wb.redo',
              Icons.redo,
              '重做',
              repo.canRedo && !repo.busy ? repo.redoDraft : null,
            ),
            _mini(
              'wb.discard',
              Icons.layers_clear,
              '丢弃草稿',
              repo.hasDraft && !repo.busy
                  ? () => confirmWorkbenchDiscard(context, repo)
                  : null,
            ),
            const SizedBox(width: 4),
            TextButton(
              key: const ValueKey('wb.candidate'),
              style: TextButton.styleFrom(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 28),
              ),
              onPressed: repo.hasDraft && !repo.busy && !repo.candidateBusy
                  ? () => repo.requestCandidate()
                  : null,
              child: const Text('算候选', style: TextStyle(fontSize: ctFontSm)),
            ),
          ],
        ),
      ],
    );
  }

  /// 资源区宽度有限：图标按钮压到 28×28 并保留 tooltip。
  Widget _mini(
    String keyName,
    IconData icon,
    String tooltip,
    VoidCallback? onPressed,
  ) {
    return SizedBox(
      width: 30,
      height: 30,
      child: IconButton(
        key: Key(keyName),
        icon: Icon(icon, size: 15),
        tooltip: tooltip,
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
        visualDensity: VisualDensity.compact,
        onPressed: onPressed,
      ),
    );
  }

  Widget _candidateRow() {
    if (repo.draftError case final error?) {
      return Text(
        error,
        key: const ValueKey('wb.draftError'),
        style: ctText(size: ctFontSm, color: ctDanger),
      );
    }
    final candidate = repo.candidate;
    if (candidate == null) return const SizedBox.shrink();
    final diff = candidate.netDiff;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '净差异 新增${diff.added.length} 删除${diff.removed.length} '
          '改${diff.changed.length}',
          key: const ValueKey('wb.candidateSummary'),
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
        for (final problem in candidate.problems)
          Text(
            '✗ ${problem.resource == null ? '' : '${problem.resource}：'}${problem.message}',
            key: const ValueKey('wb.candidateProblem'),
            style: ctText(size: ctFontSm, color: ctDanger),
          ),
      ],
    );
  }

  /// 单/双输入框的轻量对话框；返回 null 表示取消。
  static Future<_PromptResult?> _ask(
    BuildContext context, {
    required String title,
    String initial = '',
    String? secondLabel,
    String secondInitial = '',
  }) async {
    final first = TextEditingController(text: initial);
    final second = TextEditingController(text: secondInitial);
    final result = await showDialog<Object?>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              key: const ValueKey('wb.nameField'),
              controller: first,
              autofocus: true,
              decoration: const InputDecoration(labelText: '名称'),
            ),
            if (secondLabel != null)
              TextField(
                key: const ValueKey('wb.secondField'),
                controller: second,
                decoration: InputDecoration(labelText: secondLabel),
              ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('wb.dialogConfirm'),
            onPressed: () => Navigator.pop(dialogContext, <String, String>{
              'first': first.text,
              'second': secondLabel == null ? '' : second.text,
            }),
            child: const Text('加入草稿'),
          ),
        ],
      ),
    );
    if (result is! Map) return null;
    final name = (result['first'] as String? ?? '').trim();
    if (name.isEmpty) return null;
    return _PromptResult(name, (result['second'] as String? ?? '').trim());
  }

  Future<void> _create(BuildContext context, String kind) =>
      createWorkbenchResource(
        context,
        repo: repo,
        kind: kind,
        onResourceSelected: onResourceSelected,
      );

  Future<void> _renameResource(BuildContext context) async {
    final from = selected;
    if (from == null) return;
    final answer = await _ask(context, title: '把 $from 改名为', initial: from);
    if (answer == null || answer.name == from) return;
    repo.renameResource(from, answer.name);
    onResourceSelected?.call(answer.name);
  }

  Future<void> _deleteResource(BuildContext context) async {
    final name = selected;
    if (name == null) return;
    final resource = repo.resourceNamed(name);
    if (resource == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        key: const ValueKey('wb.deleteResourcePrompt'),
        title: Text('删除资源 $name？'),
        content: const Text(
          '此操作先加入 Schema 草稿，不会立即改动工作区文件。'
          '保存草稿后才会删除对应的 YAML；可在保存前撤销。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          TextButton(
            key: const ValueKey('wb.deleteResourceConfirm'),
            style: TextButton.styleFrom(foregroundColor: ctDanger),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('加入删除草稿'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    repo.deleteResource(resourceId(_kindWire(resource.kind), name));
    onResourceSelected?.call(
      repo.resources.isEmpty ? null : repo.resources.first.name,
    );
  }

  Future<void> _addField(BuildContext context) async {
    final owner = selected;
    if (owner == null) return;
    final resource = repo.resourceNamed(owner);
    if (resource == null) return;
    final namedTypes = [
      for (final item in repo.resources)
        if (item.kind != WorkbenchResourceKind.table && item.name != owner)
          item.name,
    ];
    final answer = await _askAddField(
      context,
      owner: owner,
      namedTypes: namedTypes,
    );
    if (answer == null) return;
    repo.addField(
      resourceId(_kindWire(resource.kind), owner),
      answer.name,
      answer.type,
    );
  }

  Future<_AddFieldResult?> _askAddField(
    BuildContext context, {
    required String owner,
    required List<String> namedTypes,
  }) async {
    final name = TextEditingController();
    var type = 'int32';
    final result = await showDialog<_AddFieldResult>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: Text('给 $owner 加字段'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  key: const ValueKey('wb.nameField'),
                  controller: name,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: '字段名'),
                ),
                const SizedBox(height: ctGapLg),
                Text(
                  '类型',
                  style: ctText(size: ctFontSm, color: ctInk2),
                ),
                const SizedBox(height: ctGapXs),
                CtTypePicker(
                  value: type,
                  namedTypes: namedTypes,
                  keyPrefix: 'wb.addFieldType',
                  onChanged: (value) => setDialogState(() => type = value),
                ),
                const SizedBox(height: ctGapXs),
                Text(
                  namedTypes.isEmpty
                      ? '当前工作区没有 Record / Enum；只能选择标量类型。'
                      : '具名类型来自当前工作区资源清单。',
                  style: ctText(size: ctFontXs, color: ctInk3),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const ValueKey('wb.dialogConfirm'),
              onPressed: () => Navigator.pop(
                dialogContext,
                _AddFieldResult(name.text.trim(), type),
              ),
              child: const Text('加入草稿'),
            ),
          ],
        ),
      ),
    );
    // 类型选择器是嵌套路由；等退出动画结束后再释放输入控制器。
    Future<void>.delayed(const Duration(milliseconds: 300), name.dispose);
    if (result == null || result.name.isEmpty) return null;
    return result;
  }

  static String _kindWire(WorkbenchResourceKind kind) => switch (kind) {
    WorkbenchResourceKind.table => 'table',
    WorkbenchResourceKind.record => 'record',
    WorkbenchResourceKind.enumType => 'enum',
  };
}

enum _ResourceMenuAction { open, addField, rename, copyId, copyPath, delete }

/// 资源树右键菜单：常用编辑动作与复制/删除入口。
Future<void> showWorkbenchResourceContextMenu(
  BuildContext context, {
  required WorkbenchRepository repo,
  required String resourceName,
  required Offset globalPosition,
  ValueChanged<String?>? onResourceSelected,
}) async {
  final resource = repo.resourceNamed(resourceName);
  if (resource == null) return;
  final overlay = Overlay.of(context).context.findRenderObject() as RenderBox;
  final action = await showMenu<_ResourceMenuAction>(
    context: context,
    position: RelativeRect.fromRect(
      Rect.fromPoints(globalPosition, globalPosition),
      Offset.zero & overlay.size,
    ),
    popUpAnimationStyle: ctMenuAnimationStyle,
    items: [
      const PopupMenuItem(
        key: ValueKey('wb.resourceMenu.open'),
        value: _ResourceMenuAction.open,
        height: 36,
        child: _ResourceMenuItem(Icons.edit_outlined, '打开'),
      ),
      PopupMenuItem(
        key: const ValueKey('wb.resourceMenu.addField'),
        value: _ResourceMenuAction.addField,
        enabled: !repo.busy,
        height: 36,
        child: const _ResourceMenuItem(Icons.playlist_add, '添加字段…'),
      ),
      PopupMenuItem(
        key: const ValueKey('wb.resourceMenu.rename'),
        value: _ResourceMenuAction.rename,
        enabled: !repo.busy,
        height: 36,
        child: const _ResourceMenuItem(Icons.drive_file_rename_outline, '重命名…'),
      ),
      const PopupMenuItem(
        key: ValueKey('wb.resourceMenu.copyId'),
        value: _ResourceMenuAction.copyId,
        height: 36,
        child: _ResourceMenuItem(Icons.tag, '复制资源 ID'),
      ),
      const PopupMenuItem(
        key: ValueKey('wb.resourceMenu.copyPath'),
        value: _ResourceMenuAction.copyPath,
        height: 36,
        child: _ResourceMenuItem(Icons.content_copy, '复制路径'),
      ),
      const PopupMenuDivider(),
      PopupMenuItem(
        key: const ValueKey('wb.resourceMenu.delete'),
        value: _ResourceMenuAction.delete,
        enabled: !repo.busy,
        height: 36,
        child: const _ResourceMenuItem(
          Icons.delete_outline,
          '删除资源…',
          danger: true,
        ),
      ),
    ],
  );
  if (action == null || !context.mounted) return;

  final editor = WorkbenchSchemaEditor(
    repo: repo,
    selected: resourceName,
    onResourceSelected: onResourceSelected,
  );
  switch (action) {
    case _ResourceMenuAction.open:
      onResourceSelected?.call(resourceName);
    case _ResourceMenuAction.addField:
      await editor._addField(context);
    case _ResourceMenuAction.rename:
      await editor._renameResource(context);
    case _ResourceMenuAction.copyId:
      await Clipboard.setData(
        ClipboardData(
          text: resourceId(
            WorkbenchSchemaEditor._kindWire(resource.kind),
            resourceName,
          ),
        ),
      );
      if (context.mounted) showCtToast(context, '已复制资源 ID');
    case _ResourceMenuAction.copyPath:
      await Clipboard.setData(ClipboardData(text: resource.path));
      if (context.mounted) showCtToast(context, '已复制路径');
    case _ResourceMenuAction.delete:
      await editor._deleteResource(context);
  }
}

class _ResourceMenuItem extends StatelessWidget {
  const _ResourceMenuItem(this.icon, this.label, {this.danger = false});

  final IconData icon;
  final String label;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final color = danger ? ctDanger : ctInk2;
    return Row(
      children: [
        Icon(icon, size: 15, color: color),
        const SizedBox(width: ctGapSm),
        Text(
          label,
          style: ctText(size: ctFontSm, color: color),
        ),
      ],
    );
  }
}

class _PromptResult {
  const _PromptResult(this.name, this.second);

  final String name;
  final String second;
}

class _AddFieldResult {
  const _AddFieldResult(this.name, this.type);

  final String name;
  final String type;
}
