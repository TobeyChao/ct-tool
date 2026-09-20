import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 字段类型/属性/索引编辑（任务 3.2）的客户端侧契约：
/// 回显一律取内核给的字段属性，命令形状与内核词表一致，问题按 location 归属过滤。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.problems = const []});

  final List<({String method, Map<String, Object?> params})> calls = [];
  final List<Issue> problems;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-editor';

  static const _columns = [
    {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
    {
      'name': 'Name',
      'typeExpr': 'string',
      'role': 'i18n',
      'i18n': true,
      'comment': '显示名',
    },
    {
      'name': 'Tags',
      'typeExpr': 'vector<string>',
      'excelColumns': 3,
      'comment': '标签组',
    },
    {'name': 'Rarity', 'typeExpr': 'Rarity', 'ref': 'Item.Id'},
  ];

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add((method: method, params: params));
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 4,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 1,
      },
      Methods.resourcesList => {
        'revision': 4,
        'schemaRevision': 'baseline-editor',
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
            'indexes': ['codename'],
          },
          {
            'name': 'Rarity',
            'kind': 'enum',
            'sourcePath': 'config/types/rarity.yaml',
          },
        ],
      },
      Methods.tablePreview => {
        'revision': 4,
        'columns': _columns,
        'rows': const <Object?>[],
      },
      Methods.schemaCandidate => {
        'candidateHash': 'hash-editor',
        'draftGeneration': params['draftGeneration'],
        'netDiff': {
          'added': <Object?>[],
          'removed': <Object?>[],
          'changed': const [
            {'kind': 'table', 'name': 'Item'},
          ],
        },
        'problems': problems.map((e) => e.toJson()).toList(),
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

void main() {
  const root = 'D:/game/A';

  Future<WorkbenchRepository> opened(_FakeGateway gateway) async {
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace(root);
    await repo.loadPreview('Item');
    return repo;
  }

  test('字段行与属性由内核预览列给出，缺席即未声明', () async {
    final repo = await opened(_FakeGateway());
    final item = repo.resourceNamed('Item')!;
    expect(item.fields.map((f) => f.name), ['Id', 'Name', 'Tags', 'Rarity']);

    final name = item.fields[1];
    expect(name.type, 'string');
    expect(name.description, '显示名');
    expect(name.localized, isTrue);
    expect(name.role, isEmpty, reason: 'i18n 由标志位表达，role 只留主键');

    final tags = item.fields[2];
    expect(tags.excelColumns, 3);
    expect(tags.serverOnly, isFalse, reason: '内核没写就是未声明');
    expect(item.fields[3].constraints, 'Item.Id', reason: 'ref 走约束列展示');
    expect(item.indexes, ['codename'], reason: '索引状态来自内核清单');
    repo.dispose();
  });

  test('类型/属性/顺序/索引/枚举成员命令形状与内核词表一致', () async {
    final repo = await opened(_FakeGateway());

    repo.setFieldType('table:Item', 'Name', 'int64');
    repo.setFieldProperty('table:Item', 'Name', 'server_only', true);
    repo.setFieldProperty('table:Item', 'Tags', 'excel_columns', null);
    repo.moveField('table:Item', 'Tags', 1);
    repo.setTableIndexes('table:Item', ['codename']);
    repo.renameEnumItem('enum:Rarity', 'Common', 'Normal', 0);

    expect(repo.commands.map((c) => c.kind).toList(), [
      'set_type',
      'set_property',
      'set_property',
      'move_field',
      'set_indexes',
      'rename_enum_item',
    ]);
    final type = repo.commands.first.payload;
    expect(type['owner'], 'table:Item');
    expect(type['type_text'], 'int64');

    final excel = repo.commands[2].payload;
    expect(excel['property'], 'excel_columns');
    expect(excel.containsKey('value'), isTrue, reason: 'null 也要显式送出表示移除');
    expect(excel['value'], isNull);

    final moved = repo.commands[3].payload;
    expect(moved['name'], 'Tags');
    expect(moved['to'], 1);

    final indexes = repo.commands[4].payload;
    expect(indexes['table'], 'table:Item');
    expect(indexes['indexes'], [
      {'kind': 'codename'},
    ]);

    final item = repo.commands[5].payload;
    expect(item['oldName'], 'Common');
    expect(item['newName'], 'Normal');
    expect(item['originalOrdinal'], 0);
    repo.dispose();
  });

  test('草稿投影把类型/属性/顺序/索引改动反映到清单', () async {
    final repo = await opened(_FakeGateway());
    expect(repo.resourceNamed('Item')!.fields[1].type, 'string');

    repo
      ..setFieldType('table:Item', 'Name', 'int64')
      ..setFieldProperty('table:Item', 'Name', 'i18n', false)
      ..setFieldProperty('table:Item', 'Rarity', 'ref', '')
      ..setFieldProperty('table:Item', 'Id', 'server_only', true)
      ..moveField('table:Item', 'Name', 2)
      ..setTableIndexes('table:Item', const []);

    final after = repo.resourceNamed('Item')!;
    expect(after.fields.map((f) => f.name), ['Id', 'Tags', 'Name', 'Rarity']);
    expect(after.fields.firstWhere((f) => f.name == 'Name').type, 'int64');
    expect(after.fields.firstWhere((f) => f.name == 'Name').localized, isFalse);
    expect(after.fields.firstWhere((f) => f.name == 'Id').serverOnly, isTrue);
    expect(
      after.fields.firstWhere((f) => f.name == 'Rarity').constraints,
      isEmpty,
      reason: '空串即移除 ref',
    );
    expect(after.indexes, isEmpty, reason: '覆盖式声明：空数组即移除');
    expect(after.dirty, isTrue);
    repo.dispose();
  });

  test('属性改动不丢其余信息，撤销后回到内核状态', () async {
    final repo = await opened(_FakeGateway());
    final original = repo.resourceNamed('Item')!.fields[2];

    repo.setFieldProperty('table:Item', 'Tags', 'comment', '标签');
    final changed = repo.resourceNamed('Item')!.fields[2];
    expect(changed.description, '标签');
    expect(changed.excelColumns, original.excelColumns, reason: '只改注释不应丢展开组数');
    expect(changed.type, original.type);

    repo.undoDraft();
    final back = repo.resourceNamed('Item')!.fields[2];
    expect(back.description, original.description);
    expect(repo.draftCount, 0);
    repo.dispose();
  });

  test('候选问题按 location 归属到资源与字段，原文不改写', () async {
    final gateway = _FakeGateway(
      problems: const [
        Issue(
          code: 'schema-issue',
          message: '字段 Name 不能同时标记 i18n 和 server_only',
          resource: 'table:Item/Name',
        ),
        Issue(
          code: 'schema-issue',
          message: '具名类型 NotHere 不存在',
          resource: 'table:Item/Rarity',
        ),
        Issue(
          code: 'schema-issue',
          message: '草稿基线已过期',
          resource: 'schemaRevision',
        ),
      ],
    );
    final repo = await opened(gateway);
    await repo.requestCandidate();
    expect(repo.problemsFor('table:Item'), hasLength(2), reason: '基线提示不属于具体资源');
    final forName = repo.problemsFor('table:Item', fieldName: 'Name');
    expect(forName, hasLength(1));
    expect(forName.single.message, contains('不能同时标记'));
    expect(repo.problemsFor('table:Item', fieldName: 'Id'), isEmpty);
    repo.dispose();
  });

  test('未算候选时没有问题可显示，界面不会凭空造警告', () async {
    final repo = await opened(_FakeGateway());
    expect(repo.candidate, isNull);
    expect(repo.problemsFor('table:Item'), isEmpty);
    repo.dispose();
  });
}
