import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';

/// 假传输：按脚本回应，用于确定性地验证握手/关联/门禁/关闭语义。
class _FakeTransport implements WorkerTransport {
  _FakeTransport({this.replyHello = true});

  final _inbound = StreamController<Message>.broadcast();
  final sent = <Message>[];
  final List<int> closed = [];
  Object? sendError;
  Object? closeError;
  Completer<void>? closeGate;
  final closeStarted = Completer<void>();
  final helloSent = Completer<void>();

  /// 回给客户端的 hello 版本；改小写测试不兼容分支。
  final bool replyHello;
  int helloVersion = kWorkerProtocolVersion;
  List<String> capabilities = const ['workspace', 'export', 'shutdown'];

  @override
  Stream<Message> get messages => _inbound.stream;

  @override
  void send(Message message) {
    if (sendError case final error?) throw error;
    sent.add(message);
    if (message is Hello && !helloSent.isCompleted) helloSent.complete();
    switch (message) {
      case Request(method: 'hello'):
        break;
      case final Request request:
        if (request.method == 'shutdown') {
          _respond(request.requestId, {'outcome': 'shutdown'});
        }
      case _:
        if (message is Hello && replyHello) {
          _inbound.add(
            Hello(
              protocolVersion: helloVersion,
              coreVersion: '0.0.0-fake',
              capabilities: capabilities,
            ),
          );
        }
    }
  }

  void respond(int requestId, Object? payload, {int seq = 1}) =>
      _respond(requestId, payload, seq: seq);

  void _respond(int requestId, Object? payload, {int seq = 1}) {
    _inbound.add(
      ResultMessage(
        requestId: requestId,
        workspaceId: 'ws-fake',
        seq: seq,
        payload: payload,
      ),
    );
  }

  void emit(Message message) => _inbound.add(message);

  void emitError(Object error) => _inbound.addError(error);

  Future<void> endMessages() => _inbound.close();

  int? lastRequestId() {
    for (final message in sent.reversed) {
      if (message is Request) return message.requestId;
    }
    return null;
  }

  @override
  Future<void> close() async {
    closed.add(1);
    if (!closeStarted.isCompleted) closeStarted.complete();
    if (closeError case final error?) {
      closeError = null;
      throw error;
    }
    await closeGate?.future;
    await _inbound.close();
  }

  bool get isClosed => closed.isNotEmpty;
}

SettingsStore _settings(String root) => SettingsStore()
  ..workspacePath = root
  // 用宿主可执行文件当「显式开发运行时」，只为了通过发现这一步；
  // 真正的传输由注入的假连接接管。
  ..runtimePath = Platform.resolvedExecutable;

Future<WorkerService> _ready(
  _FakeTransport transport, {
  String root = '/ws',
}) async {
  final service = WorkerService(
    settings: _settings(root),
    connect: () async => transport,
  );
  await service.start();
  return service;
}

void main() {
  group('worker 握手与写入口门禁', () {
    test('握手成功后记录版本/能力并放行写入口', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      expect(service.status, WorkerStatus.ready);
      expect(service.protocolVersion, kWorkerProtocolVersion);
      expect(service.coreVersion, '0.0.0-fake');
      expect(service.capabilities, contains('export'));
      expect(service.writeBlockReason(method: Methods.export), isNull);
      expect(
        service.writeBlockReason(method: 'deploy'),
        contains('能力缺失'),
        reason: '能力表里没有的方法必须禁用写入口',
      );
      await service.stop();
    });

    test('协议版本不兼容 → 写入口禁用且不报 ready', () async {
      final transport = _FakeTransport()..helloVersion = 99;
      final service = await _ready(transport);
      expect(service.status, isNot(WorkerStatus.ready));
      expect(service.protocolCompatible, isFalse);
      expect(service.writeBlockReason(method: Methods.export), isNotNull);
      expect(service.failureReason, contains('协议版本不兼容'));
      expect(transport.closed, hasLength(1));
      await service.stop();
      expect(transport.closed, hasLength(1));
      service.dispose();
    });

    test('worker 不回 hello → 超时后报失败，不谎称就绪', () async {
      final transport = _FakeTransport(replyHello: false);
      final service = WorkerService(
        settings: _settings('/ws'),
        connect: () async => transport,
        handshakeTimeout: const Duration(milliseconds: 30),
      );
      await service.start().timeout(const Duration(seconds: 2));
      expect(service.status, WorkerStatus.failed);
      expect(service.failureReason, contains('握手超时'));
      expect(transport.closed, hasLength(1));
      await service.stop();
      expect(transport.closed, hasLength(1));
      service.dispose();
    });

    for (final failure in ['connection error', 'stream error', 'EOF']) {
      test(
        '$failure during hello promptly closes the owned transport',
        () async {
          final transport = _FakeTransport(replyHello: false);
          final service = WorkerService(
            settings: _settings('/ws'),
            connect: () async => transport,
            // The test must finish long before this timeout.
            handshakeTimeout: const Duration(seconds: 30),
          );
          final starting = service.start();
          await transport.helloSent.future;
          switch (failure) {
            case 'connection error':
              transport.emit(
                ErrorMessage(
                  error: const ErrorBody(
                    code: 'bad-hello',
                    message: 'rejected',
                  ),
                ),
              );
            case 'stream error':
              transport.emitError(const FormatException('bad frame'));
            case 'EOF':
              await transport.endMessages();
          }
          await starting.timeout(const Duration(seconds: 2));
          expect(service.status, WorkerStatus.failed);
          expect(transport.closed, hasLength(1));
          await service.stop();
          expect(transport.closed, hasLength(1));
          service.dispose();
        },
      );
    }

    test('throwing hello send closes the attached transport', () async {
      final transport = _FakeTransport()..sendError = StateError('send failed');
      final service = await _ready(transport);
      expect(service.status, WorkerStatus.failed);
      expect(service.failureReason, contains('send failed'));
      expect(transport.closed, hasLength(1));
      await service.stop();
      expect(transport.closed, hasLength(1));
      service.dispose();
    });

    test(
      'failed handshake waits for close and concurrent stop shares teardown',
      () async {
        final transport = _FakeTransport()
          ..helloVersion = 99
          ..closeGate = Completer<void>();
        final service = WorkerService(
          settings: _settings('/ws'),
          connect: () async => transport,
        );
        var startFinished = false;
        var stopFinished = false;
        final starting = service.start().then((_) => startFinished = true);
        await transport.closeStarted.future;
        final stopping = service.stop().then((_) => stopFinished = true);
        await pumpEventQueue();
        expect(startFinished, isFalse);
        expect(stopFinished, isFalse);
        expect(transport.closed, hasLength(1));
        transport.closeGate!.complete();
        await Future.wait([starting, stopping]);
        expect(service.status, WorkerStatus.stopped);
        expect(transport.closed, hasLength(1));
        service.dispose();
      },
    );

    test('failed close retains ownership so stop can retry', () async {
      final transport = _FakeTransport()
        ..helloVersion = 99
        ..closeError = StateError('close failed');
      final service = await _ready(transport);
      expect(service.status, WorkerStatus.failed);
      expect(transport.closed, hasLength(1));
      expect(
        service.logs.any((log) => log.message.contains('close failed')),
        isTrue,
      );
      await service.stop();
      expect(transport.closed, hasLength(2));
      expect(service.status, WorkerStatus.stopped);
      service.dispose();
    });
  });

  group('live stdio failed-handshake cleanup', () {
    for (final failure in [
      'incompatible hello',
      'malformed frame',
      'silent worker',
    ]) {
      test(
        '$failure closes stdin, drains stdout and awaits EOF cleanup',
        () async {
          final root = await Directory.systemTemp.createTemp('ct-hello-close-');
          final marker = File('${root.path}/eof-cleanup');
          final reply = switch (failure) {
            'incompatible hello' => const NdjsonCodec().encodeLine(
              const Hello(
                protocolVersion: 99,
                coreVersion: 'fixture',
                capabilities: [],
              ),
            ),
            'malformed frame' => 'invalid JSON\n',
            _ => '',
          };
          late StdioWorkerTransport transport;
          final service = WorkerService(
            settings: _settings(root.path),
            handshakeTimeout: failure == 'silent worker'
                ? const Duration(milliseconds: 100)
                : const Duration(seconds: 15),
            connect: () async => transport = await StdioWorkerTransport.start(
              executable: '/bin/sh',
              arguments: [
                '-c',
                'IFS= read -r hello\n'
                    'printf "%s" "\$1"\n'
                    'while IFS= read -r line; do :; done\n'
                    // More output than a pipe buffer even after protocol decoding fails.
                    'dd if=/dev/zero bs=65536 count=8 2>/dev/null\n'
                    'sleep "\$3"\n'
                    'printf complete > "\$2"\n',
                'ct-handshake-fixture',
                reply,
                marker.path,
                failure == 'incompatible hello' ? '6' : '0.1',
              ],
            ),
          );
          try {
            await service.start().timeout(const Duration(seconds: 12));
            expect(service.status, WorkerStatus.failed);
            expect(
              service.failureReason,
              contains(switch (failure) {
                'incompatible hello' => '协议版本不兼容',
                'malformed frame' => '协议流异常',
                _ => '握手超时',
              }),
            );
            expect(
              await transport.exitCode.timeout(const Duration(seconds: 1)),
              0,
            );
            expect(await marker.readAsString(), 'complete');
            await service.stop();
            expect(service.status, WorkerStatus.stopped);
          } finally {
            await service.stop();
            service.dispose();
            await root.delete(recursive: true);
          }
        },
        skip: Platform.isWindows,
        timeout: const Timeout(Duration(seconds: 20)),
      );
    }
  });

  group('请求关联与终态', () {
    test('只读终态不进入广播流，避免刷新请求回环', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      final seen = <Message>[];
      final subscription = service.events.listen(seen.add);
      final pending = service.request(Methods.tasksList, params: const {});
      final id = _sentRequestIds(transport).last;

      transport.respond(id, {'tasks': <Object?>[]});

      expect(await pending, {'tasks': <Object?>[]});
      await Future<void>.delayed(Duration.zero);
      expect(seen, isEmpty);
      await subscription.cancel();
      await service.stop();
    });

    test('终态同时进入广播流，供桌面自动刷新任务和历史', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      final pending = service.request('export', params: const {});
      final id = _sentRequestIds(transport).last;
      final terminal = service.events.firstWhere(
        (message) => message is ResultMessage && message.requestId == id,
      );

      transport.respond(id, {'outcome': 'succeeded'});

      expect(await pending, {'outcome': 'succeeded'});
      expect(
        await terminal.timeout(const Duration(seconds: 1)),
        isA<ResultMessage>(),
      );
      await service.stop();
    });

    test('requestId 唯一、乱序终态各归其主', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);

      final first = service.query('workspace.open', params: const {});
      final second = service.query('workspace.status', params: const {});
      final ids = _sentRequestIds(transport);
      expect(ids.length, greaterThanOrEqualTo(2));
      expect(ids.toSet().length, ids.length, reason: 'requestId 不得重复');

      // 故意后发的先回。
      transport.respond(ids[1], {'revision': 7});
      transport.respond(ids[0], {'revision': 3});
      expect(await first, {'revision': 3});
      expect(await second, {'revision': 7});
      await service.stop();
    });

    test('失败终态抛结构化异常并带明细', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      final pending = service.request('export', params: const {});
      final id = _sentRequestIds(transport).last;
      transport.emit(
        ErrorMessage(
          requestId: id,
          workspaceId: 'ws-fake',
          seq: 2,
          error: const ErrorBody(
            code: 'recovery-needed',
            message: '存在未完成的发布',
            issues: [Issue(code: 'stale', message: '先恢复')],
          ),
        ),
      );
      Object? caught;
      try {
        await pending;
      } on WorkerRequestException catch (e) {
        caught = e;
      }
      final failure = caught! as WorkerRequestException;
      expect(failure.code, 'recovery-needed');
      expect(failure.message, contains('未完成的发布'));
      expect(failure.issues.single.code, 'stale');
      expect(failure.issues.single.fieldPath, isNull);
      await service.stop();
    });

    test('连接级 error（无 requestId）整体置失败并禁用写入', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      transport.emit(
        ErrorMessage(
          error: const ErrorBody(code: 'malformed-message', message: '坏帧'),
        ),
      );
      await pumpEventQueue();
      expect(service.status, WorkerStatus.failed);
      expect(service.writeBlockReason(method: Methods.export), isNotNull);
    });

    test('对端断开时挂起请求以 transport-closed 结束，不悬挂', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      final pending = service
          .request('validate', params: const {})
          .then<Object?>((_) => null)
          .catchError((Object e) => e);
      expect(_sentRequestIds(transport).last, greaterThan(0));
      await transport.close();
      final caught = await pending.timeout(const Duration(seconds: 2));
      expect(caught, isA<WorkerRequestException>());
      expect((caught! as WorkerRequestException).code, 'transport-closed');
      service.dispose();
    });
  });

  group('关闭与取消', () {
    test('重复 stop 共用一次 shutdown 与传输关闭', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      await Future.wait([service.stop(), service.stop()]);
      expect(
        transport.sent.whereType<Request>().where(
          (request) => request.method == Methods.shutdown,
        ),
        hasLength(1),
      );
      expect(transport.closed, hasLength(1));
      service.dispose();
    });

    test(
      'stop preserves accepted publishing terminal results until EOF',
      () async {
        final transport = _FakeTransport()..closeGate = Completer<void>();
        final service = await _ready(transport);
        var taskFinished = false;
        final publishing = service.request(Methods.export).then((result) {
          taskFinished = true;
          return result;
        });
        final requestId = _sentRequestIds(transport).last;
        final stopping = service.stop();
        await transport.closeStarted.future;
        await pumpEventQueue();
        expect(taskFinished, isFalse);
        transport.respond(requestId, {'outcome': 'succeeded'});
        expect(await publishing, {'outcome': 'succeeded'});
        transport.closeGate!.complete();
        await stopping;
        expect(service.status, WorkerStatus.stopped);
        service.dispose();
      },
    );

    test('启动中 stop 等待连接建立后安全关闭', () async {
      final transport = _FakeTransport();
      final connected = Completer<WorkerTransport>();
      final service = WorkerService(
        settings: _settings('/ws'),
        connect: () => connected.future,
      );
      final starting = service.start();
      final stopping = service.stop();
      connected.complete(transport);
      await Future.wait([starting, stopping]);
      expect(service.status, WorkerStatus.stopped);
      expect(transport.isClosed, isTrue);
      service.dispose();
    });

    test(
      'stdio EOF 后等待超过旧强杀时限的发布收尾',
      () async {
        final root = await Directory.systemTemp.createTemp('ct-worker-exit-');
        final marker = File('${root.path}/published');
        final transport = await StdioWorkerTransport.start(
          executable: '/bin/sh',
          arguments: [
            '-c',
            'while IFS= read -r line; do :; done\n'
                'sleep 6\n'
                'printf complete > "\$1"\n',
            'ct-graceful-exit',
            marker.path,
          ],
        );
        try {
          await transport.close();
          expect(await transport.exitCode, 0);
          expect(await marker.readAsString(), 'complete');
        } finally {
          await root.delete(recursive: true);
        }
      },
      skip: Platform.isWindows,
      timeout: const Timeout(Duration(seconds: 20)),
    );

    test('stop 先发 shutdown 再关传输', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      await service.stop();
      final methods = transport.sent
          .whereType<Request>()
          .map((r) => r.method)
          .toList();
      expect(methods, contains(Methods.shutdown));
      expect(transport.isClosed, isTrue);
      expect(service.status, WorkerStatus.stopped);
    });

    test('cancel 走独立请求并带上目标 requestId', () async {
      final transport = _FakeTransport();
      final service = await _ready(transport);
      final running = service.request('export', params: const {});
      final target = _sentRequestIds(transport).last;
      await service.cancel(target);
      final cancel = transport.sent.whereType<Request>().lastWhere(
        (r) => r.method == Methods.cancel,
      );
      expect(cancel.params['targetRequestId'], target);
      transport.respond(target, {'outcome': 'cancelled'});
      expect(await running, {'outcome': 'cancelled'});
      await service.stop();
    });
  });

  group('真实 worker 进程', () {
    final binary =
        Platform.environment['CT_WORKER_BIN'] ??
        (Platform.isWindows
            ? '../native/target/debug/ct.exe'
            : '../native/target/debug/ct');
    final available = File(binary).existsSync();
    final skipReason = available
        ? false
        : '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

    test(
      '握手 + workspace.open + 安全 shutdown，stderr 不混入协议',
      () async {
        final workspace = await _fixtureWorkspace();
        late StdioWorkerTransport transport;
        final service = WorkerService(
          settings: _settings(workspace.path),
          connect: () async => transport = await StdioWorkerTransport.start(
            executable: File(binary).absolute.path,
            workingDirectory: workspace.path,
          ),
        );
        await service.start();
        expect(
          service.status,
          WorkerStatus.ready,
          reason: service.failureReason ?? '',
        );
        expect(service.protocolVersion, kWorkerProtocolVersion);
        expect(service.capabilities, containsAll(['export', 'shutdown']));

        final opened = await service.query(
          Methods.workspaceOpen,
          workspaceRoot: workspace.path,
        );
        expect(opened, isA<Map<String, Object?>>());
        final openedMap = opened! as Map<String, Object?>;
        expect(openedMap['status'], 'ready');
        expect(openedMap['revision'], isNotNull);
        expect((openedMap['tables'] as num? ?? 0) >= 1, isTrue);

        await service.stop();
        // stderr 只进诊断缓冲，不会被当成协议消息。
        for (final line in transport.stderrLines) {
          expect(line.trim().startsWith('{"type":'), isFalse, reason: line);
        }
        await workspace.delete(recursive: true);
      },
      skip: skipReason,
      timeout: const Timeout(Duration(minutes: 2)),
    );

    test(
      "分页：同代次连续翻页，篡改令牌报 stale-page",
      () async {
        final workspace = await _fixtureWorkspace();
        final service = WorkerService(
          settings: _settings(workspace.path),
          connect: () async => StdioWorkerTransport.start(
            executable: File(binary).absolute.path,
            workingDirectory: workspace.path,
          ),
        );
        await service.start();
        expect(
          service.status,
          WorkerStatus.ready,
          reason: service.failureReason ?? '',
        );
        await service.query(
          Methods.workspaceOpen,
          workspaceRoot: workspace.path,
        );
        // 先制造足量模块日志（导出会写多行进度）。
        await service.request(
          Methods.export,
          workspaceRoot: workspace.path,
          timeout: const Duration(seconds: 120),
        );

        final page1 =
            await service.query(
                  Methods.logsList,
                  params: const {
                    'page': {'limit': 1},
                  },
                  workspaceRoot: workspace.path,
                )
                as Map<String, Object?>;
        final entries1 = (page1['entries'] as List)
            .cast<Map<String, Object?>>();
        expect(entries1.length, 1, reason: '单页应只回 1 条：$page1');
        final cursor = page1['nextCursor'];
        expect(cursor, isA<String>(), reason: '还有后续时应给出游标');
        final revision = page1['revision'];
        expect(revision, isA<int>());

        final page2 =
            await service.query(
                  Methods.logsList,
                  params: {
                    'page': {'limit': 1, 'cursor': cursor},
                  },
                  workspaceRoot: workspace.path,
                )
                as Map<String, Object?>;
        expect(page2['revision'], revision, reason: '同一次快照代次内翻页不得混代次');
        final entries2 = (page2['entries'] as List)
            .cast<Map<String, Object?>>();
        expect(
          entries2.first['message'] != entries1.first['message'],
          isTrue,
          reason: '第二页必须是不同的行',
        );

        Object? caught;
        try {
          await service.query(
            Methods.logsList,
            params: {
              'page': {'limit': 1, 'cursor': '${cursor}x'},
            },
            workspaceRoot: workspace.path,
          );
        } on WorkerRequestException catch (e) {
          caught = e;
        }
        expect(caught, isA<WorkerRequestException>(), reason: '篡改游标必须被拒');
        expect((caught! as WorkerRequestException).code, 'stale-page');
        await service.stop();
        await workspace.delete(recursive: true);
      },
      skip: skipReason,
      timeout: const Timeout(Duration(minutes: 3)),
    );
  });
}

/// 已发出的 requestId 序列（不含 hello）。
List<int> _sentRequestIds(_FakeTransport transport) =>
    transport.sent.whereType<Request>().map((r) => r.requestId).toList();

/// 复制一份最小工作区夹具（不碰真实 gd/）。
Future<Directory> _fixtureWorkspace() async {
  final dir = await Directory.systemTemp.createTemp('ct-dart-worker-');
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
