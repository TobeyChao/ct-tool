import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:flutter_test/flutter_test.dart';

class _Call {
  _Call(this.method, this.params, this.root);
  final String method;
  final Map<String, Object?> params;
  final String? root;
}

/// 假内核：按方法给出 payload 或结构化失败，并支持把请求挂在空中以模拟运行中。
class _FakeGateway implements KernelGateway {
  _FakeGateway();

  final List<_Call> calls = [];
  final Map<String, Object?> replies = {};
  final Map<String, ErrorBody> failures = {};
  final Map<String, Completer<Object?>> heldFor = {};

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-run';

  List<_Call> of(String method) =>
      calls.where((c) => c.method == method).toList();

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(_Call(method, params, workspaceRoot));
    final failure = failures[method];
    if (failure != null) throw WorkerRequestException(failure);
    final gate = heldFor[method];
    if (gate != null) return gate.future;
    return replies[method];
  }
}

Map<String, Object?> exportPayload({
  String outcome = 'succeeded',
  int tables = 3,
  int durationMs = 42,
  List<Object?> issues = const [],
}) => {
  'outcome': outcome,
  'tables': tables,
  'durationMs': durationMs,
  'stages': [
    {'name': 'parse', 'elapsedMs': 10},
    {'name': 'generate', 'elapsedMs': 32},
  ],
  'cache': {'hits': 5, 'misses': 2},
  'issues': issues,
};

void main() {
  late _FakeGateway gateway;
  late ExportRunner runner;

  setUp(() {
    gateway = _FakeGateway();
    runner = ExportRunner(worker: gateway, workspaceRoot: 'E:/ws/gd');
  });

  tearDown(() {
    runner.dispose();
  });

  test('导出参数按内核契约拼装：table/lang 只带选中的，all 显式送', () async {
    gateway.replies[Methods.export] = exportPayload();
    runner
      ..table = 'Hero'
      ..lang = 'en'
      ..all = true;
    expect(runner.exportParams, {'table': 'Hero', 'lang': 'en', 'all': true});

    runner
      ..table = null
      ..lang = ''
      ..all = false;
    expect(runner.exportParams, {'all': false}, reason: '空过滤不应进参数');

    expect(await runner.startExport(), isTrue);
    expect(gateway.of(Methods.export), hasLength(1));
    expect(gateway.calls.single.root, 'E:/ws/gd');
    expect(runner.phase, RunnerPhase.succeeded);
    expect(runner.exportedTables, 3);
    expect(runner.durationMs, 42);
    expect(runner.stages.map((s) => s.name), ['parse', 'generate']);
    expect(runner.cache!.hits, 5);
    expect(runner.cache!.misses, 2);
  });

  test('导出不会顺带部署；独立部署是另一条 deploy 请求', () async {
    gateway.replies[Methods.export] = exportPayload();
    gateway.replies[Methods.deploy] = {'synced': 12, 'unchanged': false};

    await runner.startExport();
    expect(gateway.of(Methods.deploy), isEmpty, reason: '桌面导出不自动部署');

    await runner.startDeploy();
    final deploy = gateway.of(Methods.deploy);
    expect(deploy, hasLength(1));
    expect(deploy.single.params, {'forBuild': false});
    expect(runner.deploy!.synced, 12);
    expect(runner.last!.message, '已同步 12 个文件');
  });

  test('未配置部署时如实显示「未写入」', () async {
    gateway.replies[Methods.deploy] = {'synced': 0, 'unchanged': true};
    expect(await runner.startDeploy(), isTrue);
    expect(runner.last!.message, '目标已是最新，未写入');
  });

  test('progress/issue 事件按任务归属与 seq 单调汇入', () async {
    gateway.heldFor[Methods.export] = Completer<Object?>();
    unawaited(runner.startExport());
    await pump();

    runner.onEvent(
      ProgressEvent(
        requestId: 7,
        workspaceId: 'ws-run',
        seq: 1,
        stage: 'generate',
        done: 4,
        total: 10,
      ),
    );
    expect(runner.runningRequestId, 7);
    expect(runner.progress!.stage, 'generate');

    runner.onEvent(
      IssueEvent(
        requestId: 7,
        workspaceId: 'ws-run',
        seq: 2,
        issue: const Issue(code: 'type-mismatch', message: '字段类型不对'),
      ),
    );
    expect(runner.liveIssues, hasLength(1));

    // 别的请求、以及回退的 seq：都不进当前视图
    runner.onEvent(
      ProgressEvent(
        requestId: 8,
        workspaceId: 'ws-run',
        seq: 3,
        stage: 'other',
        done: 1,
        total: 1,
      ),
    );
    runner.onEvent(
      ProgressEvent(
        requestId: 7,
        workspaceId: 'ws-run',
        seq: 2,
        stage: 'stale',
        done: 9,
        total: 10,
      ),
    );
    expect(runner.progress!.stage, 'generate', reason: '乱序/异请求事件不得覆盖');
    expect(runner.liveIssues, hasLength(1));

    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await pump();
    expect(runner.running, isFalse);
  });

  test('取消只转达意图：带 targetRequestId，且不把成功改写成取消', () async {
    gateway.heldFor[Methods.export] = Completer<Object?>();
    gateway.replies[Methods.cancel] = 'cancelling';
    unawaited(runner.startExport());
    await pump();

    // 还没有任何事件 → 无 requestId，取消不发请求
    await runner.cancel();
    expect(gateway.of(Methods.cancel), isEmpty);

    runner.onEvent(
      ProgressEvent(
        requestId: 9,
        workspaceId: 'ws-run',
        seq: 1,
        stage: 'validate',
        done: 1,
        total: 3,
      ),
    );
    await runner.cancel();
    final cancel = gateway.of(Methods.cancel);
    expect(cancel, hasLength(1));
    expect(cancel.single.params, {'targetRequestId': 9});
    expect(runner.cancelState, 'cancelling');
    expect(runner.phase, RunnerPhase.running, reason: '取消只是意图，终态仍待内核');

    // 内核在取消意图之后仍返回成功终态（发布边界已过）：界面必须显示成功
    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await pump();
    expect(runner.phase, RunnerPhase.succeeded);
    expect(runner.last!.result!.outcome, TaskOutcome.succeeded);
    expect(gateway.of(Methods.export), hasLength(1));
  });

  test('取消已取消的终态如实显示为已取消', () async {
    gateway.replies[Methods.export] = exportPayload(outcome: 'cancelled');
    await runner.startExport();
    expect(runner.phase, RunnerPhase.cancelled);
    expect(runner.last!.result!.outcome, TaskOutcome.cancelled);
  });

  test('busy 不覆盖状态：回到原阶段并只给提示', () async {
    gateway.failures[Methods.export] = const ErrorBody(
      code: ProtocolErrorCodes.busy,
      message: '工作区被写任务占用',
    );
    expect(await runner.startExport(), isFalse);
    expect(runner.phase, RunnerPhase.idle);
    expect(runner.error, contains('内核忙等'));
    expect(runner.last, isNull, reason: '忙等不是失败，不写结果卡');

    // 已有上一次成功结果时，busy 也不得覆盖它
    gateway.failures.remove(Methods.export);
    gateway.replies[Methods.export] = exportPayload();
    await runner.startExport();
    final before = runner.last;
    gateway.failures[Methods.export] = const ErrorBody(
      code: ProtocolErrorCodes.busy,
      message: '占用',
    );
    expect(await runner.startExport(), isFalse);
    expect(runner.phase, RunnerPhase.succeeded);
    expect(runner.last, same(before));
  });

  test('内核结构化失败交出问题明细供定位', () async {
    gateway.failures[Methods.export] = const ErrorBody(
      code: ProtocolErrorCodes.recoveryNeeded,
      message: '需要先恢复',
      issues: [
        Issue(code: 'journal-pending', message: '有未完成事务', resource: 'Hero'),
      ],
    );
    expect(await runner.startExport(), isFalse);
    expect(runner.phase, RunnerPhase.failed);
    expect(runner.issues, hasLength(1));
    expect(runner.issues.single.resource, 'Hero');
    expect(runner.error, contains('recovery-needed'));
  });

  test('断连标为终态未知，且不自动重放写请求', () async {
    gateway.heldFor[Methods.export] = Completer<Object?>();
    unawaited(runner.startExport());
    await pump();
    runner.onEvent(
      ProgressEvent(
        requestId: 11,
        workspaceId: 'ws-run',
        seq: 1,
        stage: 'export',
        done: 1,
        total: 4,
      ),
    );

    runner.markDisconnected();
    expect(runner.phase, RunnerPhase.unknown);
    expect(runner.needsUserDecision, isTrue);
    expect(runner.progress, isNull);
    expect(runner.last!.message, contains('未自动重放'));

    // 迟到的终态不能改写 unknown，也不许补发写请求
    gateway.heldFor[Methods.export]!.complete(exportPayload());
    await pump();
    expect(runner.phase, RunnerPhase.unknown);
    expect(gateway.of(Methods.export), hasLength(1));

    // 用户重新决定后才允许再发
    gateway.heldFor.clear();
    await runner.startExport();
    expect(gateway.of(Methods.export), hasLength(2));
  });

  test('未在运行时收到事件一律丢弃', () async {
    runner.onEvent(
      ProgressEvent(
        requestId: 3,
        workspaceId: 'ws-run',
        seq: 1,
        stage: 'x',
        done: 1,
        total: 1,
      ),
    );
    expect(runner.progress, isNull);
    expect(runner.runningRequestId, isNull);
  });
}

Future<void> pump() => Future<void>.delayed(Duration.zero);
