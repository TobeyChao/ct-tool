import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/validate_runner.dart';
import 'package:flutter_test/flutter_test.dart';

/// 只读校验运行器（任务 5.4 前置）：参数、并发保护与失败口径。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.reply, this.failure});

  final Object? reply;
  final ErrorBody? failure;
  final List<(String, Map<String, Object?>, String?)> calls = [];
  int inflight = 0;
  int maxInflight = 0;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-validate';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add((method, params, workspaceRoot));
    inflight += 1;
    if (inflight > maxInflight) maxInflight = inflight;
    await Future<void>.delayed(const Duration(milliseconds: 5));
    inflight -= 1;
    final failure = this.failure;
    if (failure != null) throw WorkerRequestException(failure);
    return reply;
  }
}

void main() {
  test('全库校验只发 validate，不带 table', () async {
    final gateway = _FakeGateway(
      reply: const {'ok': true, 'issues': <Object?>[]},
    );
    final runner = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
    final result = await runner.run();
    expect(result?.ok, isTrue);
    expect(gateway.calls.single.$1, Methods.validate);
    expect(gateway.calls.single.$2, isEmpty);
    expect(gateway.calls.single.$3, 'D:/ws');
    expect(runner.summaryLabel, contains('校验通过（全库，问题 0 个'));
    expect(runner.busy, isFalse, reason: '结束后必须解锁');
  });

  test('单表范围进参数，问题数与措辞都取自内核回包', () async {
    final gateway = _FakeGateway(
      reply: {
        'ok': false,
        'issues': [
          {'code': 'type', 'message': 'X 不是 int32', 'resource': 'Item'},
        ],
      },
    );
    final runner = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
    runner.scopeTable = 'Item';
    final result = await runner.run();
    expect(gateway.calls.single.$2, {'table': 'Item'});
    expect(result?.issues.single.message, 'X 不是 int32');
    expect(runner.summaryLabel, contains('校验未通过（表 Item，问题 1 个'));
  });

  test('并发保护：在跑时第二次调用不发请求', () async {
    final gateway = _FakeGateway(
      reply: const {'ok': true, 'issues': <Object?>[]},
    );
    final runner = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
    final first = runner.run();
    final second = runner.run();
    expect(await second, isNull, reason: '忙时不得并发第二个校验');
    await first;
    expect(gateway.calls, hasLength(1));
    expect(gateway.maxInflight, 1);
  });

  test('内核失败带出 code 与 message，且不得假装通过', () async {
    final gateway = _FakeGateway(
      failure: const ErrorBody(code: 'internal', message: '加载 Table 失败'),
    );
    final runner = ValidateRunner(worker: gateway, workspaceRoot: 'D:/ws');
    final result = await runner.run();
    expect(result, isNull);
    expect(runner.last, isNull);
    expect(runner.error, contains('加载 Table 失败'));
    expect(runner.summaryLabel, contains('internal'));
  });

  test('未绑定工作区时直接拒绝，不发请求', () async {
    final gateway = _FakeGateway(reply: const <String, Object?>{});
    final runner = ValidateRunner(worker: gateway, workspaceRoot: '');
    expect(await runner.run(), isNull);
    expect(gateway.calls, isEmpty);
  });
}
