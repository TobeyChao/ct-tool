/// 真实内核工作台的只读数据仓库（native-flutter-workbench 任务 2.3）。
///
/// 重点是竞态：切换工作区后，旧工作区的迟到回包与事件都不得进入当前视图。
library;

import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'dart:io';

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/ui/workbench/workbench_models.dart';
import 'package:flutter_test/flutter_test.dart';

class _Call {
  _Call(this.method, this.params, this.root);
  final String method;
  final Map<String, Object?> params;
  final String root;
}

class _FakeGateway implements KernelGateway {
  /// method@root → 应答（抛异常表示失败）。
  _FakeGateway(this.replies, this.workspaceIds);

  final Map<String, Object? Function(_Call call)> replies;
  final Map<String, String> workspaceIds;
  final List<_Call> calls = [];

  /// 非空时，命中该工作区的请求会挂起等放行（用于制造竞态）。
  String? holdRoot;
  final Map<String, Completer<void>> _gates = {};
  int notifyCount = 0;

  @override
  WorkerStatus status = WorkerStatus.ready;

  @override
  String? failureReason;

  @override
  String? lastWorkspaceId;

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    final call = _Call(method, params, workspaceRoot ?? '');
    calls.add(call);
    if (holdRoot != null && call.root == holdRoot) {
      final gate = _gates.putIfAbsent(call.root, Completer<void>.new);
      await gate.future;
    }
    lastWorkspaceId = workspaceIds[call.root];
    final handler = replies['$method@${call.root}'];
    if (handler == null) throw StateError('未预期的调用：$method@${call.root}');
    return handler(call);
  }

  void release(String root) => _gates[root]?.complete();
}

Map<String, Object?> _snapshot({
  required int revision,
  int tables = 1,
  int records = 0,
  int enums = 0,
}) => {
  'revision': revision,
  'status': 'ready',
  'recovery': {'needed': false, 'journals': <String>[]},
  'tables': tables,
  'records': records,
  'enums': enums,
};

Map<String, Object?> _resources(List<List<Object?>> entries) => {
  'revision': 1,
  'resources': entries
      .map((e) => {'name': e[0], 'kind': e[1], 'sourcePath': e[2]})
      .toList(),
};

Map<String, Object?> _preview({
  required int revision,
  required List<List<Object?>> rows,
}) => {
  'revision': revision,
  'columns': [
    {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
    {'name': 'Name', 'typeExpr': 'string', 'role': null},
  ],
  'rows': rows,
  'nextCursor': null,
};

void main() {
  const aRoot = 'D:/game/A';
  const bRoot = 'D:/game/B';

  _FakeGateway gateway({
    Map<String, Object?> Function(_Call)? previewA,
    bool failOpenA = false,
  }) {
    return _FakeGateway(
      {
        'workspace.open@$aRoot': (call) => failOpenA
            ? throw StateError('schema 解析失败')
            : _snapshot(revision: 7, tables: 1, enums: 1),
        'resources.list@$aRoot': (call) => _resources([
          ['Item', 'table', 'config/schemas/item.yaml'],
          ['Rarity', 'enum', 'config/types/rarity.yaml'],
        ]),
        'table.preview@$aRoot':
            previewA ??
            (call) => _preview(
              revision: 7,
              rows: [
                [1001, '铁剑', null],
                [1002, BigInt.from(9 << 40), null],
              ],
            ),
        'workspace.open@$bRoot': (call) => _snapshot(revision: 12, tables: 2),
        'resources.list@$bRoot': (call) => _resources([
          ['Quest', 'table', 'config/schemas/quest.yaml'],
          ['Buff', 'table', 'config/schemas/buff.yaml'],
          ['DropRule', 'record', 'config/types/drop_rule.yaml'],
        ]),
        'table.preview@$bRoot': (call) => _preview(
          revision: 12,
          rows: [
            [1, 'daily', null],
          ],
        ),
      },
      {aRoot: 'ws-aaaa', bRoot: 'ws-bbbb'},
    );
  }

  test('切换工作区：总览与资源列表都来自内核回包', () async {
    final gw = gateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(aRoot);

    expect(repo.loadError, isNull);
    expect(repo.schemaRevision, 7);
    expect(repo.workspaceName, 'A');
    expect(repo.workspacePath, aRoot);
    expect(repo.sampleData, isFalse);
    expect(gw.calls.map((c) => c.method).toList(), [
      Methods.workspaceOpen,
      Methods.resourcesList,
    ]);
    expect(repo.resources.map((r) => r.name).toList(), ['Item', 'Rarity']);
    expect(repo.resources.first.kind, WorkbenchResourceKind.table);
    expect(repo.resources.last.kind, WorkbenchResourceKind.enumType);
    expect(repo.resources.first.path, 'config/schemas/item.yaml');
    repo.dispose();
  });

  test('只读预览按需拉取、可复用，并把大整数还原成十进制文本', () async {
    final gw = gateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(aRoot);
    expect(repo.resources.first.previewRows, isEmpty);

    await repo.loadPreview('Item');
    final item = repo.resources.first;
    expect(item.previewColumns, ['Id', 'Name']);
    expect(item.previewRows.length, 2);
    expect(item.previewRows[1][1], (BigInt.from(9 << 40)).toString());
    expect(item.fields.first.role, 'primary');
    expect(item.fields[1].type, 'string');

    final before = gw.calls.length;
    await repo.loadPreview('Item');
    expect(gw.calls.length, before, reason: '同一张表不得重复请求预览');
    repo.dispose();
  });

  test('旧工作区的迟到回包不得进入当前视图', () async {
    final gw = gateway()..holdRoot = aRoot;
    final repo = WorkbenchRepository(worker: gw);
    var repaints = 0;
    repo.addListener(() => repaints++);

    final first = repo.switchWorkspace(aRoot);
    await repo.switchWorkspace(bRoot);
    expect(repo.resources.map((r) => r.name).toList(), [
      'Quest',
      'Buff',
      'DropRule',
    ]);
    expect(repo.schemaRevision, 12);
    final seenAfterB = repaints;

    gw.release(aRoot);
    await first;
    await Future<void>.delayed(Duration.zero);

    expect(repo.resources.map((r) => r.name).toList(), [
      'Quest',
      'Buff',
      'DropRule',
    ], reason: 'A 的回包必须被代次守卫丢弃');
    expect(repo.schemaRevision, 12);
    expect(repo.workspaceId, 'ws-bbbb');
    expect(repaints, seenAfterB, reason: '丢弃的回包不应触发重绘');
    expect(repo.generation, 2);
    repo.dispose();
  });

  test('旧工作区事件被丢弃，当前工作区事件才请求重绘', () async {
    final gw = gateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(bRoot);
    var repaints = 0;
    repo.addListener(() => repaints++);

    repo.onWorkerEvent(
      const LogEvent(
        requestId: 1,
        workspaceId: 'ws-aaaa',
        seq: 1,
        module: 'export',
        level: 'info',
        message: '旧工作区的日志',
      ),
    );
    expect(repaints, 0);
    expect(repo.acceptsEvent('ws-aaaa'), isFalse);
    expect(repo.acceptsEvent('ws-bbbb'), isTrue);

    repo.onWorkerEvent(
      const ProgressEvent(
        requestId: 2,
        workspaceId: 'ws-bbbb',
        seq: 2,
        stage: 'json',
        done: 1,
        total: 5,
      ),
    );
    expect(repaints, 1);
    repo.dispose();
  });

  test('打开失败与预览失败只报当前工作区的错误', () async {
    final gw = gateway(failOpenA: true);
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(aRoot);
    expect(repo.loadError, contains('读取工作区失败'));
    expect(repo.resources, isEmpty);
    expect(repo.busy, isFalse);

    // 让打开先成功，再让预览失败：错误必须归到当前工作区的当前请求上。
    gw.replies['workspace.open@$aRoot'] = (call) =>
        _snapshot(revision: 7, tables: 1, enums: 1);
    gw.replies['table.preview@$aRoot'] = (call) => throw StateError('表不存在');
    await repo.switchWorkspace(aRoot);
    expect(repo.resources.map((r) => r.name).toList(), contains('Item'));
    await repo.loadPreview('Item');
    expect(repo.previewError, contains('预览 Item 失败'));
    expect(repo.loadError, isNot(contains('预览')), reason: '预览失败不得覆盖工作区级别的原因');
    repo.dispose();
  });

  group('草稿投影与候选（任务 3.1）', () {
    _FakeGateway draftGateway({Object? Function(_Call)? candidate}) {
      final gw = _FakeGateway(
        {
          'workspace.open@/draft': (_) => _snapshot(revision: 4, tables: 1),
          'resources.list@/draft': (_) => {
            'revision': 4,
            'schemaRevision': 'baseline-sha',
            'resources': [
              {
                'name': 'Item',
                'kind': 'table',
                'sourcePath': 'config/schemas/item.yaml',
              },
            ],
          },
          'schema.candidate@/draft':
              candidate ??
              (call) => {
                'candidateHash': 'hash-1',
                'draftGeneration': call.params['draftGeneration'],
                'netDiff': {
                  'added': [
                    {'kind': 'table', 'name': 'Hero'},
                  ],
                  'removed': <Object?>[],
                  'changed': <Object?>[],
                },
                'problems': <Object?>[],
              },
        },
        {'/draft': 'ws-draft'},
      );
      return gw;
    }

    Future<WorkbenchRepository> ready({_FakeGateway? gw}) async {
      final repo = WorkbenchRepository(worker: gw ?? draftGateway());
      await repo.switchWorkspace('/draft');
      return repo;
    }

    test('清单带回落盘基线，草稿命令进入清单并可撤销重做', () async {
      final repo = await ready();
      expect(repo.schemaBaseline, 'baseline-sha');
      expect(repo.resources.map((r) => r.name).toList(), ['Item']);

      repo.createTable('Hero');
      expect(repo.draftCount, 1);
      expect(repo.hasDraft, isTrue);
      var hero = repo.resources.last;
      expect(hero.name, 'Hero');
      expect(hero.kind, WorkbenchResourceKind.table);
      expect(hero.dirty, isTrue, reason: '草稿资源必须显式标未保存');
      expect(hero.path, contains('草稿'));
      expect(hero.fields.map((f) => f.name), ['Id']);

      repo.undoDraft();
      expect(repo.resources.map((r) => r.name).toList(), ['Item']);
      expect(repo.canRedo, isTrue);
      repo.redoDraft();
      expect(repo.resources.map((r) => r.name).toList(), ['Item', 'Hero']);
      hero = repo.resources.last;
      expect(hero.dirty, isTrue);
      repo.dispose();
    });

    test('改名与删除只作用于投影，来源路径随名字保留', () async {
      final repo = await ready();
      repo.renameResource('Item', 'Gear');
      expect(repo.resources.single.name, 'Gear');
      expect(repo.resources.single.path, 'config/schemas/item.yaml');
      expect(repo.resources.single.dirty, isTrue);

      repo.discardDraft();
      expect(repo.resources.single.name, 'Item');

      repo.deleteResource('table:Item');
      expect(repo.resources, isEmpty);
      repo.dispose();
    });

    test('字段命令作用于投影（加/改名/删）', () async {
      final repo = await ready();
      repo.createRecord('Loot');
      repo.addField('record:Loot', 'Rate', 'float');
      var loot = repo.resources.last;
      expect(loot.fields.last.name, 'Rate');
      expect(loot.fields.last.type, 'float');

      repo.renameField('record:Loot', 'Rate', 'Chance');
      loot = repo.resources.last;
      expect(loot.fields.any((f) => f.name == 'Chance'), isTrue);
      expect(loot.fields.any((f) => f.name == 'Rate'), isFalse);

      repo.deleteField('record:Loot', 'Chance');
      loot = repo.resources.last;
      expect(loot.fields.map((f) => f.name), isNot(contains('Chance')));
      repo.dispose();
    });

    test('候选请求带全守卫参数，结果可被界面读取', () async {
      final gw = draftGateway();
      final repo = await ready(gw: gw);
      repo.createTable('Hero');
      final result = await repo.requestCandidate();
      expect(result, isNotNull);
      expect(result!.candidateHash, 'hash-1');
      expect(result.netDiff.added.single.name, 'Hero');
      expect(result.problems, isEmpty);
      expect(repo.candidate, isNotNull);

      final call = gw.calls.lastWhere(
        (c) => c.method == Methods.schemaCandidate,
      );
      expect(call.params['schemaRevision'], 'baseline-sha');
      expect(call.params['cursor'], '1');
      expect(call.params['draftGeneration'], result.draftGeneration);
      expect(result.draftGeneration, greaterThan(0));
      final commands = call.params['commands']! as List<Object?>;
      expect(commands.single! as Map<String, Object?>, {
        'kind': 'add_resource',
        'payload': {
          'kind': 'table',
          'resource': {
            'table': 'Hero',
            'primary': 'Id',
            'fields': [
              {'name': 'Id', 'type': 'int32'},
            ],
          },
        },
      });
      repo.dispose();
    });

    test('游标随撤销进候选请求：撤销后的前缀才是生效命令', () async {
      final gw = draftGateway();
      final repo = await ready(gw: gw);
      repo.createTable('A');
      repo.createEnum('E');
      repo.undoDraft();
      await repo.requestCandidate();
      final call = gw.calls.lastWhere(
        (c) => c.method == Methods.schemaCandidate,
      );
      expect(call.params['cursor'], '1');
      final commands = call.params['commands']! as List<Object?>;
      expect(commands.length, 2, reason: '仍发送全量命令，由游标截取生效前缀');
      expect(
        (commands.first! as Map<String, Object?>)['payload'],
        isNot(isNull),
      );
      repo.dispose();
    });

    test('旧候选回声不得覆盖当前结论', () async {
      final gw = draftGateway(
        candidate: (call) => {
          'candidateHash': 'stale-hash',
          'draftGeneration': 999,
          'netDiff': {
            'added': <Object?>[],
            'removed': <Object?>[],
            'changed': <Object?>[],
          },
        },
      );
      final repo = await ready(gw: gw);
      repo.createTable('Hero');
      final result = await repo.requestCandidate();
      expect(result, isNull, reason: '回声代次不匹配时必须忽略');
      expect(repo.candidate, isNull);
      repo.dispose();
    });

    test('候选被内核拒绝时把错误码交给界面', () async {
      final gw = draftGateway(
        candidate: (call) => throw WorkerRequestException(
          const ErrorBody(code: 'stale-page', message: '基线已变化，请重算候选'),
        ),
      );
      final repo = await ready(gw: gw);
      repo.createTable('Hero');
      final result = await repo.requestCandidate();
      expect(result, isNull);
      expect(repo.draftError, contains('stale-page'));
      expect(repo.draftError, contains('基线已变化'));
      repo.dispose();
    });

    test('切换工作区即丢弃草稿，避免跨工作区串命令', () async {
      final gw = _FakeGateway(
        {
          ...draftGateway().replies,
          'workspace.open@/other': (_) => _snapshot(revision: 9, tables: 0),
          'resources.list@/other': (_) => {
            'revision': 9,
            'schemaRevision': 'other-baseline',
            'resources': <Object?>[],
          },
        },
        {'/draft': 'ws-draft', '/other': 'ws-other'},
      );
      final repo = WorkbenchRepository(worker: gw);
      await repo.switchWorkspace('/draft');
      repo.createTable('Hero');
      expect(repo.draftCount, 1);
      await repo.switchWorkspace('/other');
      expect(repo.draftCount, 0);
      expect(repo.resources, isEmpty);
      expect(repo.schemaBaseline, 'other-baseline');
      repo.dispose();
    });
  });

  test('真实 ct worker：仓库读到的资源与预览来自内核', () async {
    final binary =
        Platform.environment['CT_WORKER_BIN'] ??
        (Platform.isWindows
            ? '../native/target/debug/ct.exe'
            : '../native/target/debug/ct');
    if (!File(binary).existsSync()) {
      return; // 未构建原生二进制时由 worker_service_test 统一说明
    }
    final workspace = await _copyFixture();
    final transport = await StdioWorkerTransport.start(
      executable: File(binary).absolute.path,
      workingDirectory: workspace.path,
    );
    final worker = WorkerService(
      settings: SettingsStore()
        ..workspacePath = workspace.path
        ..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    await worker.start();
    expect(
      worker.status,
      WorkerStatus.ready,
      reason: worker.failureReason ?? '',
    );

    final repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(workspace.path);
    expect(repo.loadError, isNull, reason: repo.loadError ?? '');
    expect(
      repo.resources.map((r) => r.name).toList(),
      containsAll(<String>['Item', 'Rarity']),
    );
    final item = repo.resources.firstWhere((r) => r.name == 'Item');
    expect(item.kind, WorkbenchResourceKind.table);
    expect(item.path, isNotEmpty);

    await repo.loadPreview('Item');
    final previewed = repo.resources.firstWhere((r) => r.name == 'Item');
    expect(previewed.previewColumns, contains('Id'));
    expect(previewed.previewRows.length, 2);

    await worker.stop();
    repo.dispose();
    await workspace.delete(recursive: true);
  }, timeout: const Timeout(Duration(minutes: 2)));

  test('未就绪时不请求预览', () async {
    final gw = gateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.loadPreview('Item');
    expect(gw.calls, isEmpty);
    repo.dispose();
  });
}

/// 复制导出流水线夹具到临时目录（绝不使用真实 gd/）。
Future<Directory> _copyFixture() async {
  final dir = await Directory.systemTemp.createTemp('ct-repo-fixture-');
  final source = Directory('../native/fixtures/export_pipeline/workspace');
  await for (final entity in source.list(recursive: true)) {
    final relative = entity.path.substring(source.path.length + 1);
    final target = '${dir.path}/$relative';
    if (entity is Directory) {
      await Directory(target).create(recursive: true);
    } else if (entity is File) {
      await Directory(File(target).parent.path).create(recursive: true);
      await entity.copy(target);
    }
  }
  return dir;
}
