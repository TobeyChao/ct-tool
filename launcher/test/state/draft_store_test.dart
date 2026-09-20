import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:flutter_test/flutter_test.dart';

/// 用户目录草稿存储（native-flutter-workbench 任务 3.5）：
/// 原子落盘、按工作区隔离、基线冲突与损坏文件一律保留不猜。
void main() {
  late Directory root;
  late DraftStore store;
  const key = 'D:/game/A';
  const baseline = 'sha-aaa';

  setUp(() async {
    root = await Directory.systemTemp.createTemp('ct-draft-');
    store = DraftStore(rootOverride: root);
  });

  tearDown(() async {
    try {
      await root.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  });

  DraftEnvelope envelope({
    String workspaceKey = key,
    String base = baseline,
    int cursor = 2,
    List<SchemaCommand>? commands,
  }) => DraftEnvelope(
    formatVersion: DraftEnvelope.currentFormat,
    workspaceKey: workspaceKey,
    baseline: base,
    commands:
        commands ??
        const [
          SchemaCommand(kind: 'add_resource', payload: {'kind': 'table'}),
          SchemaCommand(kind: 'rename_field', payload: {'owner': 'table:Item'}),
        ],
    cursor: cursor,
    savedAt: DateTime(2026, 9, 19, 10, 30),
  );

  test('信封带全四要素：格式版本、工作区身份、基线、命令与游标', () async {
    await store.save(envelope());
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.restored);
    final found = loaded.envelope!;
    expect(found.formatVersion, DraftEnvelope.currentFormat);
    expect(found.workspaceKey, key);
    expect(found.baseline, baseline);
    expect(found.cursor, 2, reason: '撤销游标必须原样回来');
    expect(found.commands.map((c) => c.kind), ['add_resource', 'rename_field']);
    expect(found.savedAt, DateTime(2026, 9, 19, 10, 30));
  });

  test('按工作区隔离，且文件名跨进程稳定（自做哈希，不用 Object.hash）', () async {
    await store.save(envelope());
    await store.save(envelope(workspaceKey: 'D:/game/B'));
    final files = root.listSync(recursive: true).whereType<File>().toList();
    expect(files, hasLength(2), reason: '两个工作区两份文件');
    expect(
      DraftStore.fileName('D:/game/A'),
      DraftStore.fileName(r'D:\GAME\a'),
      reason: '路径分隔符与大小写不应造出第二份草稿',
    );
    expect(
      RegExp(r'^draft-[0-9a-f]{16}\.json$').hasMatch(DraftStore.fileName(key)),
      isTrue,
    );
    final again = await DraftStore(
      rootOverride: root,
    ).load(workspaceKey: key, baseline: baseline);
    expect(again.outcome, DraftOutcome.restored, reason: '重连同一目录要能找回自己的草稿');
  });

  test('落盘是原子的：不留临时文件，内容是合法 JSON', () async {
    await store.save(envelope());
    final leftovers = root
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.tmp'))
        .toList();
    expect(leftovers, isEmpty, reason: 'rename 之后不该留临时文件');
    final written = root.listSync(recursive: true).whereType<File>().single;
    expect(jsonDecode(written.readAsStringSync()), isA<Map<String, Object?>>());
  });

  test('基线不同只报冲突：草稿文件仍在磁盘上，也不被套用', () async {
    await store.save(envelope());
    final loaded = await store.load(workspaceKey: key, baseline: 'sha-changed');
    expect(loaded.outcome, DraftOutcome.conflict);
    expect(loaded.envelope, isNotNull, reason: '界面要能说明保留了什么');
    expect(loaded.reason, contains('基线已变'));
    final file = await store.fileFor(key);
    expect(file.existsSync(), isTrue, reason: '冲突不得删文件');
  });

  test('空草稿即删除文件；clear 之后再读是 none', () async {
    await store.save(envelope());
    await store.clear(key);
    expect((await store.fileFor(key)).existsSync(), isFalse);
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.none);
  });

  test('无法解析或格式不认识：判为 damaged 并可留档查看，不静默清空', () async {
    final file = await store.fileFor(key);
    await file.writeAsString('{ this is not json');
    var loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.damaged);
    expect(loaded.path, file.path);

    final kept = await store.preserve(key);
    expect(kept, isNotNull);
    expect(File(kept!).existsSync(), isTrue, reason: '留档必须还在，用户能自己看');
    expect(file.existsSync(), isFalse);

    await file.writeAsString(
      jsonEncode({
        'formatVersion': DraftEnvelope.currentFormat + 5,
        'workspaceKey': key,
        'baseline': baseline,
        'cursor': 0,
        'commands': <Object?>[],
      }),
    );
    loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.damaged);
    expect(loaded.reason, contains('格式版本'));
  });

  test('信封缺字段一律按不可靠处理，不猜成空草稿', () {
    for (final json in [
      <String, Object?>{
        'workspaceKey': key,
        'baseline': baseline,
        'cursor': 0,
        'commands': const [],
      },
      <String, Object?>{
        'formatVersion': 1,
        'baseline': baseline,
        'cursor': 0,
        'commands': const [],
      },
      <String, Object?>{
        'formatVersion': 1,
        'workspaceKey': key,
        'cursor': 0,
        'commands': const [],
      },
      <String, Object?>{
        'formatVersion': 1,
        'workspaceKey': key,
        'baseline': baseline,
        'commands': const [],
      },
      <String, Object?>{
        'formatVersion': 1,
        'workspaceKey': key,
        'baseline': baseline,
        'cursor': 0,
      },
    ]) {
      expect(
        () => DraftEnvelope.fromJson(json),
        throwsA(isA<DraftFormatException>()),
        reason: '$json 不该被当成可用草稿',
      );
    }
  });

  test('归属与工作区身份不一致的草稿判为 damaged（防止串档）', () async {
    await store.save(envelope(workspaceKey: 'D:/game/OTHER'));
    final file = await store.fileFor('D:/game/OTHER');
    final data = jsonDecode(file.readAsStringSync())! as Map<String, Object?>;
    data['workspaceKey'] = 'D:/game/TRAP';
    await file.writeAsString(jsonEncode(data));
    final loaded = await store.load(
      workspaceKey: 'D:/game/OTHER',
      baseline: baseline,
    );
    expect(loaded.outcome, DraftOutcome.damaged);
    expect(loaded.reason, contains('不一致'));
  });
}
