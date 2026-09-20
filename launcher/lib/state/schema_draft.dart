/// 草稿命令日志（native-flutter-workbench 任务 3.1 的服务端形状对齐层）。
///
/// 命令词表与 payload 形状由内核拥有：这里只负责按 `ct-domain::commands` 的
/// 线格式拼装的 JSON，并用 `cursor` 表达撤销游标（回放前缀）。客户端不自行校验语义，
/// 一切以 `schema.candidate` 的内核结论为准。
library;

import '../services/protocol/protocol.dart';

/// 资源 id 形态：`table:Item` / `record:DropRule` / `enum:Rarity`。
String resourceId(String kind, String name) => '$kind:$name';

/// 可撤销/重放的命令日志。
class CommandLog {
  CommandLog({List<SchemaCommand> commands = const []})
    : _commands = [...commands];

  final List<SchemaCommand> _commands;

  /// 撤销游标：指向「下一条待执行命令」的下标；等于长度时表示全部生效。
  int _cursor = 0;

  List<SchemaCommand> get commands => List.unmodifiable(_commands);

  int get cursor => _cursor;

  bool get isEmpty => _commands.isEmpty;

  int get length => _commands.length;

  /// 游标之后的命令被丢弃（新编辑会截断 redo 分支）。
  void append(SchemaCommand command) {
    if (_cursor < _commands.length) {
      _commands.removeRange(_cursor, _commands.length);
    }
    _commands.add(command);
    _cursor = _commands.length;
  }

  bool get canUndo => _cursor > 0;

  bool get canRedo => _cursor < _commands.length;

  void undo() {
    if (canUndo) _cursor--;
  }

  /// 逐步回退：把游标挪到第 `target` 步（0 表示全部未生效）。
  /// 只移动游标——命令与重做分支都保留，与内核「撤销只移动 cursor」的约定一致。
  bool undoTo(int target) {
    if (target < 0 || target > _commands.length) return false;
    if (target == _cursor) return false;
    _cursor = target;
    return true;
  }

  void redo() {
    if (canRedo) _cursor++;
  }

  void clear() {
    _commands.clear();
    _cursor = 0;
  }

  /// 从用户目录草稿恢复：原样承接命令与游标，不重放任何已撤销步骤。
  void restore(List<SchemaCommand> commands, int cursor) {
    _commands
      ..clear()
      ..addAll(commands);
    _cursor = cursor.clamp(0, _commands.length);
  }

  /// 送给 `schema.candidate` 的生效前缀（撤销后的视图）。
  List<SchemaCommand> get active =>
      _commands.take(_cursor).toList(growable: false);
}

/// 3.1 用到的命令工厂：一个入口一条命令，参数顺序与内核 str_arg 键名一致。
/// 草稿条目的可读标签：只用内核词表里已有的字段拼展示文本，
/// 不做任何业务判断（合法性始终由 `schema.candidate` 决定）。
String describeCommand(SchemaCommand command) {
  final p = command.payload;
  String s(Object? v) => (v ?? '').toString();
  final res = p['resource'] as Map<String, Object?>?;
  final field = p['field'] as Map<String, Object?>?;
  final kind = s(p['kind']);
  final resName = s(res?['table'] ?? res?['name']);
  final fieldName = s(field?['name']);
  final owner = s(p['owner']);
  final name = s(p['name']);
  final oldX = s(p['old']);
  final newX = s(p['new']);
  final toX = s(p['to']);
  final typeText = s(p['type_text']);
  final property = s(p['property']);
  final value = s(p['value']);
  final table = s(p['table']);
  final indexCount = (p['indexes'] as List<Object?>?)?.length ?? 0;
  final ordinal = s(p['originalOrdinal']);
  final enumOld = s(p['oldName']);
  final enumNew = s(p['newName']);
  return switch (command.kind) {
    'add_resource' => '新建 $kind $resName',
    'delete_resource' => '删除 $name',
    'rename_resource' => '改名 $oldX → $newX',
    'add_field' => '加字段 $owner + $fieldName',
    'delete_field' => '删字段 $owner.$name',
    'rename_field' => '改字段名 $owner.$oldX → $newX',
    'move_field' => '移动字段 $owner.$name → $toX',
    'set_type' => '改类型 $owner.$name : $typeText',
    'set_property' => '改属性 $owner.$name.$property = $value',
    'set_indexes' => '改索引 $table = $indexCount 条',
    'set_enum_values' => '枚举成员整体改写 $name',
    'rename_enum_item' => '枚举改名 $name[$ordinal] $enumOld → $enumNew',
    _ => command.kind,
  };
}

abstract final class SchemaCommands {
  static SchemaCommand addTable(String name, {String primary = 'Id'}) =>
      SchemaCommand(
        kind: 'add_resource',
        payload: {
          'kind': 'table',
          'resource': {
            'table': name,
            'primary': primary,
            'fields': [
              {'name': primary, 'type': 'int32'},
            ],
          },
        },
      );

  static SchemaCommand addRecord(String name) => SchemaCommand(
    kind: 'add_resource',
    payload: {
      'kind': 'record',
      'resource': {
        'name': name,
        'fields': [
          {'name': 'Value', 'type': 'int32'},
        ],
      },
    },
  );

  static SchemaCommand addEnum(String name) => SchemaCommand(
    kind: 'add_resource',
    payload: {
      'kind': 'enum',
      'resource': {
        'name': name,
        'values': [
          {'name': 'Value1'},
        ],
      },
    },
  );

  static SchemaCommand renameResource(String from, String to) =>
      SchemaCommand(kind: 'rename_resource', payload: {'old': from, 'new': to});

  static SchemaCommand deleteResource(String id) =>
      SchemaCommand(kind: 'delete_resource', payload: {'name': id});

  static SchemaCommand addField(
    String owner,
    String name,
    String type, {
    bool i18n = false,
    String? ref,
  }) => SchemaCommand(
    kind: 'add_field',
    payload: {
      'owner': owner,
      'field': {
        'name': name,
        'type': type,
        if (i18n) 'i18n': true,
        if (ref != null && ref.isNotEmpty) 'ref': ref,
      },
    },
  );

  static SchemaCommand renameField(String owner, String from, String to) =>
      SchemaCommand(
        kind: 'rename_field',
        payload: {'owner': owner, 'old': from, 'new': to},
      );

  static SchemaCommand deleteField(String owner, String name) => SchemaCommand(
    kind: 'delete_field',
    payload: {'owner': owner, 'name': name},
  );

  static SchemaCommand setProperty(
    String owner,
    String field,
    String property,
    Object? value,
  ) => SchemaCommand(
    kind: 'set_property',
    payload: {
      'owner': owner,
      'name': field,
      'property': property,
      'value': value,
    },
  );

  static SchemaCommand setEnumValues(String name, List<String> values) =>
      SchemaCommand(
        kind: 'set_enum_values',
        payload: {
          'name': name,
          'values': values.map((v) => {'name': v}).toList(),
        },
      );

  /// 改字段类型：类型表达式由内核解析，非法类型在候选里以问题返回。
  static SchemaCommand setType(String owner, String name, String typeText) =>
      SchemaCommand(
        kind: 'set_type',
        payload: {'owner': owner, 'name': name, 'type_text': typeText},
      );

  /// 调整字段顺序（内核 move_field 的 to 是目标下标）。
  static SchemaCommand moveField(String owner, String name, int to) =>
      SchemaCommand(
        kind: 'move_field',
        payload: {'owner': owner, 'name': name, 'to': to},
      );

  /// 声明表级查询索引：整表覆盖式（kinds 为空即移除全部声明）。
  ///
  /// `table` 必须是内核资源 id（`table:Item`）：候选合并索引时按 resource_id 查表。
  static SchemaCommand setIndexes(String tableId, List<String> kinds) =>
      SchemaCommand(
        kind: 'set_indexes',
        payload: {
          'table': tableId,
          'indexes': [
            for (final kind in kinds) {'kind': kind},
          ],
        },
      );

  /// 枚举成员改名：必须带上内核给的 originalOrdinal，位置错位就直接拒绝。
  static SchemaCommand renameEnumItem(
    String name,
    String oldName,
    String newName,
    int originalOrdinal,
  ) => SchemaCommand(
    kind: 'rename_enum_item',
    payload: {
      'name': name,
      'oldName': oldName,
      'newName': newName,
      'originalOrdinal': originalOrdinal,
    },
  );
}
