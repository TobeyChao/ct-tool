import 'package:flutter/material.dart';

import '../../state/schema_draft.dart';
import '../../state/workbench_repository.dart';
import '../../theme.dart';
import '../tokens.dart';
import 'workbench_models.dart';

/// 资源与字段的草稿操作面板（native-flutter-workbench 任务 3.1）。
///
/// 只做两件事：把用户动作拼成内核词表里的命令入草稿，并用 `schema.candidate`
/// 让内核判定这批命令（客户端不自创校验规则）。保存动作在 3.4 接入。
class WorkbenchSchemaEditor extends StatelessWidget {
  const WorkbenchSchemaEditor({super.key, required this.repo, this.selected});

  final WorkbenchRepository repo;
  final String? selected;

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
                items: [
                  ('table', Icons.add, '表', 'wb.newTable'),
                  ('record', Icons.data_object, '记录', 'wb.newRecord'),
                  ('enum', Icons.category, '枚举', 'wb.newEnum'),
                ],
                onPick: (value) => _create(context, value),
              ),
              const SizedBox(width: ctGapSm),
              _menu(
                context,
                keyName: 'wb.resourceMenu',
                label: selected == null ? '选中资源后可用' : '选中资源',
                tooltip: '对当前选中资源做什么（改名 / 删除 / 加字段）',
                enabled: selected != null,
                items: [
                  (
                    'rename',
                    Icons.drive_file_rename_outline,
                    '改名',
                    'wb.renameResource',
                  ),
                  ('delete', Icons.delete_outline, '删除', 'wb.deleteResource'),
                  ('field', Icons.playlist_add, '加字段', 'wb.addField'),
                ],
                onPick: (value) {
                  switch (value) {
                    case 'rename':
                      _renameResource(context);
                    case 'delete':
                      _deleteResource(context);
                    default:
                      _addField(context);
                  }
                },
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          "草稿 ${repo.draftCount} 条",
          key: const ValueKey('wb.draftCount'),
          style: ctText(size: ctFontSm, color: ctInk2),
        ),
        Text(
          "落盘：${repo.draftPersistLabel}",
          key: const ValueKey('wb.draftPersistState'),
          style: ctText(size: ctFontXs, color: ctInk3),
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
              repo.canUndo ? repo.undoDraft : null,
            ),
            _mini(
              'wb.redo',
              Icons.redo,
              '重做',
              repo.canRedo ? repo.redoDraft : null,
            ),
            _mini(
              'wb.discard',
              Icons.layers_clear,
              '丢弃草稿',
              repo.hasDraft ? repo.discardDraft : null,
            ),
            const SizedBox(width: 4),
            TextButton(
              key: const ValueKey('wb.candidate'),
              style: TextButton.styleFrom(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                minimumSize: const Size(0, 28),
              ),
              onPressed: repo.hasDraft && !repo.busy
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
  Future<_PromptResult?> _ask(
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

  Future<void> _create(BuildContext context, String kind) async {
    final title = switch (kind) {
      'table' => '新建 Table',
      'record' => '新建 Record',
      _ => '新建 Enum',
    };
    final answer = await _ask(context, title: title);
    if (answer == null) return;
    switch (kind) {
      case 'table':
        repo.createTable(answer.name);
      case 'record':
        repo.createRecord(answer.name);
      default:
        repo.createEnum(answer.name);
    }
  }

  Future<void> _renameResource(BuildContext context) async {
    final from = selected;
    if (from == null) return;
    final answer = await _ask(context, title: '把 $from 改名为', initial: from);
    if (answer == null || answer.name == from) return;
    repo.renameResource(from, answer.name);
  }

  Future<void> _deleteResource(BuildContext context) async {
    final name = selected;
    if (name == null) return;
    final resource = repo.resourceNamed(name);
    if (resource == null) return;
    repo.deleteResource(resourceId(_kindWire(resource.kind), name));
  }

  Future<void> _addField(BuildContext context) async {
    final owner = selected;
    if (owner == null) return;
    final resource = repo.resourceNamed(owner);
    if (resource == null) return;
    final answer = await _ask(
      context,
      title: '给 $owner 加字段',
      secondLabel: '类型（int32 / string / 具名类型…）',
      secondInitial: 'int32',
    );
    if (answer == null) return;
    repo.addField(
      resourceId(_kindWire(resource.kind), owner),
      answer.name,
      answer.second.isEmpty ? 'int32' : answer.second,
    );
  }

  static String _kindWire(WorkbenchResourceKind kind) => switch (kind) {
    WorkbenchResourceKind.table => 'table',
    WorkbenchResourceKind.record => 'record',
    WorkbenchResourceKind.enumType => 'enum',
  };
}

class _PromptResult {
  const _PromptResult(this.name, this.second);

  final String name;
  final String second;
}
