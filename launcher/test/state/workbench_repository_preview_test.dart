import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 预览分页（任务 5.2 的「分页预览」）：游标续页、追加语义、代次变化整页重查。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.nextRevision = 7});

  final List<Map<String, Object?>> requests = [];
  final int nextRevision;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-preview';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 7,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        return {
          'revision': 7,
          'schemaRevision': 'baseline-p',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.tablePreview:
        requests.add(Map<String, Object?>.from(params));
        final page = params['page']! as Map<String, Object?>;
        final cursor = page['cursor'] as String?;
        if (cursor == null) {
          return {
            'revision': 7,
            'columns': [
              {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
            ],
            'rows': [
              for (var i = 0; i < 50; i++) ['Id$i'],
            ],
            'nextCursor': 'c1',
          };
        }
        return {
          'revision': nextRevision,
          'columns': [
            {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
          ],
          'rows': [
            for (var i = 0; i < 30; i++) ['More$i'],
          ],
          'nextCursor': null,
        };
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

void main() {
  late _FakeGateway gateway;
  late WorkbenchRepository repo;

  Future<void> bind({int nextRevision = 7}) async {
    gateway = _FakeGateway(nextRevision: nextRevision);
    repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
  }

  tearDown(() => repo.dispose());

  test('首页带 nextCursor 时标记还有更多，续页是追加而不是替换', () async {
    await bind();
    await repo.loadPreview('Item');
    expect(repo.previewOf('Item')!.rows, hasLength(50));
    expect(repo.previewHasMore('Item'), isTrue);
    expect(repo.previewLoading('Item'), isFalse);

    await repo.loadMorePreview('Item');
    expect(repo.previewOf('Item')!.rows, hasLength(80));
    expect(repo.previewHasMore('Item'), isFalse);
    final sent = gateway.requests.last['page']! as Map<String, Object?>;
    expect(sent['cursor'], 'c1', reason: '续页必须带内核给的游标');
    expect(sent['limit'], WorkbenchRepository.previewPageLimit);
    expect(repo.resources.single.previewRows, hasLength(80));
    expect(repo.resources.single.previewHasMore, isFalse);
  });

  test('没有游标时续页不发请求；重复点击不并发', () async {
    await bind();
    await repo.loadPreview('Item');
    await repo.loadMorePreview('Item');
    final before = gateway.requests.length;
    await repo.loadMorePreview('Item');
    expect(gateway.requests.length, before, reason: '末页不该再打一次内核');
  });

  test('续页遇到快照代次变化：整页重查，不混两版行', () async {
    await bind(nextRevision: 8);
    await repo.loadPreview('Item');
    await repo.loadMorePreview('Item');
    final rows = repo.previewOf('Item')!.rows;
    expect(rows, hasLength(50), reason: '代次变了要重查首页，不能把两版拼在一起');
    expect(
      (gateway.requests.last['page']! as Map<String, Object?>)['cursor'],
      isNull,
      reason: '重查的是首页（不带游标），而不是继续用旧游标',
    );
  });
}
