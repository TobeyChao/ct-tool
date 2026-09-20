import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:flutter_test/flutter_test.dart';

/// 原子草稿写入的故障矩阵（native-flutter-workbench 任务 3.9）。
///
/// 能构造的故障都构造：中断残留、半截文件、格式不认识、归属不符、目录不可用。
/// ENOSPC（磁盘满）无法在本机测试内可靠构造，它与"写失败"走同一条代码路径，
/// 由目录不可用一例覆盖，并在真机演练（任务 5.5）里补实测。
void main() {
  late Directory root;
  late DraftStore store;
  const key = 'D:/game/A';
  const baseline = 'base-1';

  setUp(() async {
    root = await Directory.systemTemp.createTemp('ct-draft-faults-');
    store = DraftStore(rootOverride: root);
  });

  tearDown(() async {
    try {
      root.deleteSync(recursive: true);
    } on FileSystemException {
      // 交给系统回收
    }
  });

  DraftEnvelope envelope({
    String base = baseline,
    int cursor = 1,
    String? name,
  }) => DraftEnvelope(
    formatVersion: DraftEnvelope.currentFormat,
    workspaceKey: key,
    baseline: base,
    commands: [
      SchemaCommand(
        kind: 'add_resource',
        payload: {
          'kind': 'table',
          'resource': {'table': name ?? 'Hero'},
        },
      ),
    ],
    cursor: cursor,
    savedAt: DateTime(2026, 9, 19, 6),
  );

  Future<File> draftFile() => store.fileFor(key);

  test('保存是原子的：不留临时件，重复保存以最后一次为准', () async {
    await store.save(envelope(name: 'First'));
    await store.save(envelope(name: 'Second'));
    final file = await draftFile();
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.restored);
    expect(loaded.envelope!.commands.single.payload['resource'], {
      'table': 'Second',
    });
    expect(File('${file.path}.tmp').existsSync(), isFalse);
    expect(
      root.listSync(recursive: true).whereType<File>().length,
      1,
      reason: '不该留下任何旁路文件',
    );
  });

  test('中断留下的 .tmp 被如实报告并清走，正式信封不受影响', () async {
    await store.save(envelope(name: 'Good'));
    final file = await draftFile();
    File('${file.path}.tmp').writeAsStringSync('{ half written garbage');

    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.restored);
    expect(loaded.leftoverTemp, isTrue, reason: '界面要能说明清理过残留');
    expect(loaded.envelope!.commands.single.payload['resource'], {
      'table': 'Good',
    });
    expect(File('${file.path}.tmp').existsSync(), isFalse);
  });

  test('只有 .tmp、没有正式信封时绝不把半截内容当草稿', () async {
    final file = await draftFile();
    file.parent.createSync(recursive: true);
    File(
      '${file.path}.tmp',
    ).writeAsStringSync('{"formatVersion":1,"commands":[');
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.none);
    expect(loaded.leftoverTemp, isTrue);
    expect(file.existsSync(), isFalse);
  });

  test('正式信封被写坏：判为不可靠、保留文件并给出路径', () async {
    await store.save(envelope());
    final file = await draftFile();
    file.writeAsStringSync('{"formatVersion":1,"workspaceKey":'); // 截断
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.damaged);
    expect(loaded.path, file.path);
    expect(file.existsSync(), isTrue, reason: '保留原始材料供查看');

    final kept = await store.preserve(key);
    expect(kept, isNotNull);
    expect(File(kept!).existsSync(), isTrue);
  });

  test('旧格式/更高版本一律不当作可用草稿', () async {
    final file = await draftFile();
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      '{"formatVersion":99,"workspaceKey":"$key","baseline":"$baseline",'
      '"cursor":0,"commands":[]}',
    );
    final loaded = await store.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.damaged);
    expect(loaded.reason, contains('格式版本'));
  });

  test('目录不可用（权限类失败）：save 抛错、load 返回 none 而不崩', () async {
    final blocked = File('${root.path}/blocked');
    blocked.createSync();
    final stuck = DraftStore(rootOverride: Directory(blocked.path));
    expect(() => stuck.save(envelope()), throwsA(isA<Object>()));
    final loaded = await stuck.load(workspaceKey: key, baseline: baseline);
    expect(loaded.outcome, DraftOutcome.none);
  });

  test('清空草稿即删除文件；再次读取是 none（不残留待恢复材料）', () async {
    await store.save(envelope());
    await store.clear(key);
    expect((await draftFile()).existsSync(), isFalse);
    expect(
      (await store.load(workspaceKey: key, baseline: baseline)).outcome,
      DraftOutcome.none,
    );
    await store.clear(key); // 幂等
  });
}
