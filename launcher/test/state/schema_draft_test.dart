/// 草稿命令日志与命令词表拼装（native-flutter-workbench 任务 3.1）。
library;

import 'package:ct_launcher/state/schema_draft.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('命令 payload 形状（与内核 str_arg 键名逐一对齐）', () {
    test('add_resource：Table 用 table/primary/fields', () {
      final command = SchemaCommands.addTable('Hero');
      expect(command.kind, 'add_resource');
      expect(command.payload['kind'], 'table');
      final resource = command.payload['resource']! as Map<String, Object?>;
      expect(resource['table'], 'Hero');
      expect(resource['primary'], 'Id');
      expect(resource['fields'], [
        {'name': 'Id', 'type': 'int32'},
      ]);
      // Table 不接受 name（内核会直接拒绝）
      expect(resource.containsKey('name'), isFalse);
    });

    test('add_resource：Record 与 Enum 用 name', () {
      final record = SchemaCommands.addRecord('LootRule');
      expect(record.payload['kind'], 'record');
      final recordDoc = record.payload['resource']! as Map<String, Object?>;
      expect(recordDoc['name'], 'LootRule');
      expect(recordDoc['fields'], isA<List<Object?>>());

      final enumType = SchemaCommands.addEnum('Rarity');
      expect(enumType.payload['kind'], 'enum');
      final enumDoc = enumType.payload['resource']! as Map<String, Object?>;
      expect(enumDoc['name'], 'Rarity');
      expect(enumDoc['values'], isA<List<Object?>>());
    });

    test('改名/删除/字段的键名', () {
      expect(SchemaCommands.renameResource('Rarity', 'Quality').payload, {
        'old': 'Rarity',
        'new': 'Quality',
      });
      expect(SchemaCommands.deleteResource('table:Item').payload, {
        'name': 'table:Item',
      });
      final add = SchemaCommands.addField('table:Item', 'Price', 'int32');
      expect(add.kind, 'add_field');
      expect(add.payload['owner'], 'table:Item');
      expect(add.payload['field'], {'name': 'Price', 'type': 'int32'});
      expect(
        SchemaCommands.addField(
          'table:Item',
          'Title',
          'string',
          i18n: true,
          ref: 'table:Hero.Id',
        ).payload['field'],
        {
          'name': 'Title',
          'type': 'string',
          'i18n': true,
          'ref': 'table:Hero.Id',
        },
      );
      expect(SchemaCommands.renameField('record:Loot', 'a', 'b').payload, {
        'owner': 'record:Loot',
        'old': 'a',
        'new': 'b',
      });
      expect(SchemaCommands.deleteField('record:Loot', 'a').payload, {
        'owner': 'record:Loot',
        'name': 'a',
      });
      expect(
        SchemaCommands.setProperty(
          'table:Item',
          'Price',
          'comment',
          '价格',
        ).payload,
        {
          'owner': 'table:Item',
          'name': 'Price',
          'property': 'comment',
          'value': '价格',
        },
      );
      expect(
        SchemaCommands.setEnumValues('Rarity', ['Common', 'Rare']).payload,
        {
          'name': 'Rarity',
          'values': [
            {'name': 'Common'},
            {'name': 'Rare'},
          ],
        },
      );
    });

    test('resourceId 拼出内核 id 形态', () {
      expect(resourceId('table', 'Item'), 'table:Item');
      expect(resourceId('enum', 'Rarity'), 'enum:Rarity');
    });
  });

  group('CommandLog 游标语义', () {
    test('append 推进游标，undo/redo 只移动游标不丢命令', () {
      final log = CommandLog();
      log.append(SchemaCommands.addTable('A'));
      log.append(SchemaCommands.addRecord('B'));
      expect(log.length, 2);
      expect(log.cursor, 2);
      expect(log.active.length, 2);

      log.undo();
      expect(log.cursor, 1);
      expect(log.active.map((c) => c.payload['kind']), ['table']);
      expect(log.length, 2, reason: '撤销保留命令以便重做');
      expect(log.canRedo, isTrue);

      log.redo();
      expect(log.cursor, 2);
      expect(log.active.length, 2);
      expect(log.canRedo, isFalse);
    });

    test('撤销后新编辑截断 redo 分支', () {
      final log = CommandLog();
      log.append(SchemaCommands.addTable('A'));
      log.append(SchemaCommands.addTable('B'));
      log.undo();
      log.append(SchemaCommands.addTable('C'));
      expect(log.length, 2);
      expect(
        log.commands.map((c) => (c.payload['resource']! as Map)['table']),
        ['A', 'C'],
      );
      expect(log.canRedo, isFalse);
    });

    test('clear 归零游标与命令', () {
      final log = CommandLog();
      log.append(SchemaCommands.addEnum('E'));
      log.clear();
      expect(log.isEmpty, isTrue);
      expect(log.cursor, 0);
      expect(log.canUndo, isFalse);
    });
  });
}
