// 同源契约夹具测试（rust-native-core 任务 6.11）：
// Rust 侧用真实 worker 执行 native/fixtures/protocol/wire-cases.json，
// 这里逐帧解码同一批消息，保证 Dart 客户端看到的就是内核实际送出的形状。
import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

File get _fixture => File('../native/fixtures/protocol/wire-cases.json');

Map<String, Object?> get document =>
    jsonDecode(_fixture.readAsStringSync())! as Map<String, Object?>;

List<Map<String, Object?>> get cases =>
    (document['cases']! as List).cast<Map<String, Object?>>();

/// 占位符 → 具体值（与 Rust 侧的占位符规则同源）。
Object? fill(Object? value) {
  if (value is Map) {
    if (value.containsKey(r'$from')) return 'cursor:2';
    return <String, Object?>{
      for (final e in value.entries) e.key! as String: fill(e.value),
    };
  }
  if (value is List) return value.map(fill).toList();
  if (value is String) {
    return switch (value) {
      '<n>' => 3,
      '<id>' => 'e07a0be98dc3b2ef',
      '<message>' => '契约诊断文本',
      '<sha256>' => 'b' * 64,
      '<schemaRevision>' => 'a' * 64,
      '<any>' => 'cursor:2',
      _ => value,
    };
  }
  return value;
}

List<Map<String, Object?>> framesOf(Map<String, Object?> case_, String dir) =>
    (case_['frames']! as List)
        .cast<Map<String, Object?>>()
        .where((f) => f['dir'] == dir)
        .toList();

Map<String, Object?> withEnvelope(Map<String, Object?> frame) {
  final request = fill(frame)! as Map<String, Object?>;
  return {
    'type': 'request',
    'requestId': request['requestId']! as int,
    'method': request['method']! as String,
    'workspaceRoot': r'E:\ct\contract-workspace',
    'params': request['params'] ?? const <String, Object?>{},
  };
}

/// 出站期望 → 完整线格式消息（补齐未声明的信封字段）。
Map<String, Object?> outbound(Map<String, Object?> expected) {
  final type = expected['type']! as String;
  final filled = fill(expected)! as Map<String, Object?>;
  if (type == 'error') {
    return {
      'type': 'error',
      if (filled['requestId'] != null) 'requestId': filled['requestId'],
      if (filled['workspaceId'] != null) 'workspaceId': filled['workspaceId'],
      if (filled['seq'] != null) 'seq': filled['seq'],
      'error': filled['error']!,
    };
  }
  return {
    'type': type,
    'requestId': filled['requestId'] ?? 1,
    'workspaceId': filled['workspaceId'] ?? 'e07a0be98dc3b2ef',
    'seq': filled['seq'] ?? 3,
    'payload': filled['payload'] ?? const <String, Object?>{},
  };
}

void main() {
  test('夹具与当前协议主版本同源，场景齐全', () {
    expect(document['protocolVersion'], 1);
    final names = cases.map((c) => c['name']! as String).toList();
    for (final required in [
      'hello_mismatch',
      'duplicate_request_id',
      'stale_page_after_input_change',
      'reconnect_reuses_ids_without_replay',
      'big_integer_roundtrip',
      'candidate_generation_echo',
      'shutdown_flow',
    ]) {
      expect(names, contains(required), reason: '缺少契约场景 $required');
    }
  });

  test('入站帧都能编码为协议消息并往返一致', () {
    for (final case_ in cases) {
      for (final frame in framesOf(case_, 'in')) {
        if (frame['hello'] != null) {
          final version = frame['hello'] == 'v1' ? 1 : frame['hello']! as int;
          final message = Hello(
            protocolVersion: version,
            coreVersion: 'dart-fixture',
            capabilities: const ['workspace'],
          );
          final line = const NdjsonCodec().encodeLine(message);
          final back = const NdjsonCodec().decodeLine(line);
          expect(back, isA<Hello>());
          expect((back as Hello).protocolVersion, version);
          continue;
        }
        if (frame['change'] != null) continue;
        final json = withEnvelope(frame['request']! as Map<String, Object?>);
        final request = Request.fromJson(json);
        expect(request.toJson(), json);
        expect(
          Methods.all,
          contains(request.method),
          reason: '${request.method} 不在方法词表',
        );
        expect(request.requestId, greaterThanOrEqualTo(0));
      }
    }
  });

  test('出站帧都解码为声明的消息类型，错误码在词表内', () {
    final codes = <String>{};
    for (final case_ in cases) {
      for (final frame in framesOf(case_, 'out')) {
        final expected = frame['expected']! as Map<String, Object?>;
        final message = Message.fromJson(outbound(expected));
        switch (expected['type']! as String) {
          case 'hello':
            expect(message, isA<Hello>());
          case 'result':
            final result = message as ResultMessage;
            expect(result.seq, greaterThan(0));
            expect(result.workspaceId, isNotEmpty);
          case 'error':
            final error = message as ErrorMessage;
            codes.add(error.error.code);
            final want = expected['error']! as Map<String, Object?>;
            expect(error.error.code, want['code']);
            // 连接级错误必须整体缺席信封字段（客户端无法归属请求）
            if (expected['requestId'] == null) {
              expect(error.requestId, isNull);
              expect(error.seq, isNull);
              expect(error.workspaceId, isNull);
            }
          default:
            fail('夹具出现未约定类型 ${expected['type']}');
        }
      }
    }
    expect(
      codes,
      containsAll(<String>[
        ProtocolErrorCodes.protocolMismatch,
        ProtocolErrorCodes.duplicateRequestId,
        ProtocolErrorCodes.stalePage,
      ]),
    );
  });

  test('大整数标签在 Dart 侧精确还原', () {
    final case_ = cases.firstWhere((c) => c['name'] == 'big_integer_roundtrip');
    final inbound = framesOf(
      case_,
      'in',
    ).map((f) => f['request']).whereType<Map<String, Object?>>().first;
    final params = (inbound['params']! as Map<String, Object?>)
        .cast<String, Object?>();
    expect(params['draftGeneration'], {r'$int': '9007199254740993'});
    final decoded = decodeBigInts(params)! as Map<String, Object?>;
    final restored = decoded['draftGeneration']! as int;
    expect(restored, 9007199254740993);
    expect(
      restored.compareTo(maxSafeInteger) > 0,
      isTrue,
      reason: '该值必须超出 JSON number 安全范围',
    );
    final outboundFrame = framesOf(
      case_,
      'out',
    ).map((f) => f['expected']).whereType<Map<String, Object?>>().first;
    final payload = (outboundFrame['payload']! as Map<String, Object?>)
        .cast<String, Object?>();
    final echoed = decodeBigInts(payload)! as Map<String, Object?>;
    expect(echoed['draftGeneration'], 9007199254740993);
    expect(encodeBigInts(echoed), payload);
  });

  test('候选代次与分页场景声明客户端需要的判据', () {
    final echo = cases.firstWhere(
      (c) => c['name'] == 'candidate_generation_echo',
    );
    final generations = framesOf(echo, 'in')
        .map((f) => f['request'])
        .whereType<Map<String, Object?>>()
        .map((r) => (r['params']! as Map<String, Object?>)['draftGeneration'])
        .toList();
    expect(generations, [5, 7], reason: '必须给出两代候选，客户端按回显丢弃迟到响应');
    final stale = cases.firstWhere(
      (c) => c['name'] == 'stale_page_after_input_change',
    );
    final expectedTypes = framesOf(
      stale,
      'out',
    ).map((f) => (f['expected']! as Map<String, Object?>)['type']).toList();
    expect(expectedTypes, ['result', 'error', 'result'], reason: '变化后旧令牌必须失败');
  });
}
