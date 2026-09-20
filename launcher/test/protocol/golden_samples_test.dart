// golden samples 契约测试：与 Rust 侧 tests/protocol/golden.rs 互为镜像，
// 保证 Dart 与 Rust 消费同一套样例。
import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

Directory _examplesDir() => Directory('../native/docs/protocol/examples');

List<File> _sampleFiles() {
  final files =
      _examplesDir()
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.ndjson'))
          .toList()
        ..sort((a, b) => a.path.compareTo(b.path));
  return files;
}

void main() {
  test('样例文件数量达到协议覆盖面要求', () {
    expect(_sampleFiles().length, greaterThanOrEqualTo(10));
  });

  test('每行样例都能解析为协议消息', () {
    var lines = 0;
    for (final file in _sampleFiles()) {
      final content = file.readAsStringSync();
      for (final (i, raw) in content.split('\n').indexed) {
        final line = raw.trim();
        if (line.isEmpty) continue;
        lines++;
        final Object? decoded;
        try {
          decoded = jsonDecode(line);
        } catch (e) {
          fail('${file.path}:${i + 1} 非法 JSON: $e');
        }
        try {
          Message.fromJson(decoded! as Map<String, Object?>);
        } catch (e) {
          fail('${file.path}:${i + 1} 不符合协议类型: $e');
        }
      }
    }
    expect(lines, greaterThanOrEqualTo(25));
  });

  test('样例覆盖全部消息类型', () {
    final seen = <String>{};
    for (final file in _sampleFiles()) {
      for (final raw in file.readAsStringSync().split('\n')) {
        final line = raw.trim();
        if (line.isEmpty) continue;
        seen.add((jsonDecode(line) as Map<String, Object?>)['type']! as String);
      }
    }
    for (final t in [
      'hello',
      'request',
      'progress',
      'log',
      'result',
      'error',
    ]) {
      expect(seen, contains(t), reason: '样例缺少 type=$t');
    }
  });

  test('信封消息序列化往返一致', () {
    for (final file in _sampleFiles()) {
      for (final raw in file.readAsStringSync().split('\n')) {
        final line = raw.trim();
        if (line.isEmpty) continue;
        final original = jsonDecode(line) as Map<String, Object?>;
        final message = Message.fromJson(original);
        expect(
          message.toJson(),
          equals(original),
          reason: '${file.path} 序列化往返不一致',
        );
      }
    }
  });

  test('关键样例的 DTO 解析', () {
    Map<String, Object?> payloadOf(String file) {
      final lines = File('../native/docs/protocol/examples/$file')
          .readAsStringSync()
          .split('\n')
          .where((l) => l.trim().isNotEmpty)
          .toList();
      final result =
          Message.fromJson(jsonDecode(lines.last) as Map<String, Object?>)
              as ResultMessage;
      return result.payload! as Map<String, Object?>;
    }

    final snapshot = WorkspaceSnapshot.fromJson(
      payloadOf('workspace_open.ndjson'),
    );
    expect(snapshot.status, WorkspaceStatus.ready);
    expect(snapshot.revision, 7);

    final candidate = SchemaCandidateResult.fromJson(
      payloadOf('schema_candidate.ndjson'),
    );
    expect(candidate.candidateHash, 'sha256:9f2c7a1b');
    expect(candidate.draftGeneration, 3);
    expect(candidate.netDiff.added.single.name, 'Item');

    final exportResult = ExportResult.fromJson(
      payloadOf('export_progress.ndjson'),
    );
    expect(exportResult.outcome, TaskOutcome.succeeded);
    expect(exportResult.cache?.hits, 48);
    expect(exportResult.stages.first.name, '解析校验');

    final preview = TablePreviewResult.fromJson(
      payloadOf('preview_bigint.ndjson'),
    );
    expect(preview.columns.first.typeExpr, 'uint64');
    expect(preview.nextCursor, 'row:2');

    final save = SchemaSaveResult.fromJson(payloadOf('schema_save.ndjson'));
    expect(save.schemaRevision, 'b' * 64);
  });
}
