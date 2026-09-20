import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 异常退出后的发布事务恢复（native-flutter-workbench 任务 4.7）。
///
/// 结论一律来自内核：workspace.open 报 recovery-needed 就必须露出恢复入口；
/// recovered / noop / blocked 三种结局原样交给界面，客户端不猜成败。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.outcome = 'recovered', this.error});

  final List<({String method, Map<String, Object?> params})> calls = [];

  /// 快照是否仍报有未完成事务（恢复成功后内核会清掉）。
  bool pending = true;
  final String outcome;

  /// 非空时 workspace.recover 直接返回结构化错误。
  final String? error;

  bool recoveredOnce = false;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-rec';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add((method: method, params: params));
    switch (method) {
      case Methods.workspaceOpen:
        final need = pending && !recoveredOnce;
        return {
          'revision': 9,
          'status': need ? 'recovery_needed' : 'ready',
          'recovery': {
            'needed': need,
            'journals': need ? ['publish-1.json'] : <String>[],
          },
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        return {
          'revision': 9,
          'schemaRevision': 'baseline-rec',
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.workspaceRecover:
        if (error != null) {
          throw WorkerRequestException(
            ErrorBody(code: error!, message: '恢复材料不足'),
          );
        }
        if (outcome == 'recovered') recoveredOnce = true;
        return {
          'outcome': outcome,
          if (outcome != 'blocked') 'revision': 10,
          'detail': outcome == 'blocked' ? '缺少旧文件备份' : '已还原 3 个文件',
        };
      default:
        throw StateError('未预期的调用：$method');
    }
  }
}

void main() {
  const root = 'D:/game/A';

  test('快照报 recovery-needed 时给出入口，恢复成功后横幅条件消失', () async {
    final gw = _FakeGateway();
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(root);

    expect(repo.recoveryNeeded, isTrue);
    expect(repo.recoveryJournals, ['publish-1.json']);
    expect(repo.loadError, isNull);

    final result = await repo.recover();
    expect(result, isNotNull);
    expect(result!.outcome, RecoverOutcome.recovered);
    expect(repo.recoveryNote, 'recovered：已还原 3 个文件');
    expect(repo.recoveryNeeded, isFalse, reason: '恢复后必须重读快照');
    expect(repo.resources, hasLength(1), reason: '恢复后要重读清单');
    expect(gw.calls.map((c) => c.method).toList(), [
      Methods.workspaceOpen,
      Methods.resourcesList,
      Methods.workspaceRecover,
      Methods.workspaceOpen,
      Methods.resourcesList,
    ]);
    repo.dispose();
  });

  test('noop 不谎报恢复：入口按内核快照保留', () async {
    final gw = _FakeGateway(outcome: 'noop');
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(root);
    final result = await repo.recover();
    expect(result!.outcome, RecoverOutcome.noop);
    expect(repo.recoveryNeeded, isTrue, reason: '内核没清理事务就不能当作已恢复');
    repo.dispose();
  });

  test('blocked 原样交出内核说明，不掩盖失败', () async {
    final gw = _FakeGateway(outcome: 'blocked');
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(root);

    final result = await repo.recover();
    expect(result!.outcome, RecoverOutcome.blocked);
    expect(result.revision, isNull);
    expect(repo.recoveryNote, 'blocked：缺少旧文件备份');
    expect(repo.recoveryNeeded, isTrue);
    repo.dispose();
  });

  test('恢复请求被内核拒绝时给出错误码并保留现场', () async {
    final gw = _FakeGateway(error: ProtocolErrorCodes.busy);
    final repo = WorkbenchRepository(worker: gw);
    await repo.switchWorkspace(root);
    expect(await repo.recover(), isNull);
    expect(repo.loadError, contains('busy'));
    expect(repo.recoveryNeeded, isTrue);
    repo.dispose();
  });
}
