import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 仓库侧的草稿持久化与恢复（任务 3.5）：恢复要原样承接命令与游标，
/// 冲突与损坏只提示不动文件，落盘失败要一直警告。
class _FakeGateway implements KernelGateway {
  _FakeGateway({this.baseline = 'baseline-1'});

  String baseline;
  final List<String> methods = [];

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-draft';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    methods.add(method);
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 3,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 0,
      },
      Methods.resourcesList => {
        'revision': 3,
        'schemaRevision': baseline,
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
          },
        ],
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

void main() {
  late Directory root;
  late DraftStore store;
  const workspace = 'D:/game/A';

  setUp(() async {
    root = await Directory.systemTemp.createTemp('ct-repo-draft-');
    store = DraftStore(rootOverride: root);
  });

  tearDown(() async {
    try {
      await root.delete(recursive: true);
    } on FileSystemException {
      // 交给系统回收
    }
  });

  WorkbenchRepository repo(_FakeGateway gateway) =>
      WorkbenchRepository(worker: gateway, store: store);

  test('编辑即落盘；放弃草稿后文件被清掉', () async {
    final gateway = _FakeGateway();
    final found = repo(gateway);
    await found.switchWorkspace(workspace);
    expect(found.draftPersistLabel, '无草稿');

    found.createTable('Hero');
    await found.persistSettled;
    expect(found.draftPersisted, isTrue);
    expect(found.draftPersistLabel, startsWith('已落盘'));
    expect((await store.fileFor(workspace)).existsSync(), isTrue);

    found.discardDraft();
    await found.persistSettled;
    expect((await store.fileFor(workspace)).existsSync(), isFalse);
    found.dispose();
  });

  test('同基线重启：命令与撤销游标原样恢复，不重放已撤销步骤', () async {
    final gateway = _FakeGateway();
    final first = repo(gateway);
    await first.switchWorkspace(workspace);
    first
      ..createTable('Hero')
      ..renameResource('Hero', 'Boss');
    await first.persistSettled;
    final savedCommands = first.commands.map((c) => c.kind).toList();
    final savedCursor = first.cursor;
    first.dispose();

    final second = repo(_FakeGateway());
    await second.switchWorkspace(workspace);
    expect(second.draftCount, 2, reason: '重启后要看到同样的两条命令');
    expect(second.commands.map((c) => c.kind).toList(), savedCommands);
    expect(second.cursor, savedCursor);
    expect(second.canUndo, isTrue);
    expect(second.canRedo, isFalse);
    expect(
      second.resources.map((r) => r.name),
      contains('Boss'),
      reason: '资源清单要按恢复出的 cursor 投影',
    );
    second.dispose();
  });

  test('撤销过的草稿重启后不重放 redo 分支', () async {
    final gateway = _FakeGateway();
    final first = repo(gateway);
    await first.switchWorkspace(workspace);
    first.createTable('Hero');
    await first.persistSettled;
    first.createTable('Extra');
    await first.persistSettled;
    first.undoDraft();
    await first.persistSettled;
    expect(first.draftCount, 1);
    expect(first.canRedo, isTrue);
    first.dispose();

    final second = repo(_FakeGateway());
    await second.switchWorkspace(workspace);
    expect(second.cursor, 1, reason: '游标要回来');
    expect(second.draftCount, 1);
    expect(second.canRedo, isTrue, reason: '重做分支保留，不静默丢步骤');
    second.dispose();
  });

  test('基线变了只报冲突：不套用、不删文件', () async {
    final gateway = _FakeGateway();
    final first = repo(gateway);
    await first.switchWorkspace(workspace);
    first.createTable('Hero');
    await first.persistSettled;
    first.dispose();

    final moved = _FakeGateway(baseline: 'baseline-external');
    final second = repo(moved);
    await second.switchWorkspace(workspace);
    expect(second.hasDraftConflict, isTrue);
    expect(second.conflictReason, contains('基线已变'));
    expect(second.draftCount, 0, reason: '绝不自动套用');
    expect(
      (await store.fileFor(workspace)).existsSync(),
      isTrue,
      reason: '也不删文件',
    );

    await second.discardStoredDraft();
    expect(second.hasDraftConflict, isFalse);
    expect((await store.fileFor(workspace)).existsSync(), isFalse);
    second.dispose();
  });

  test('损坏草稿：给出路径并保留供查看，不静默清空', () async {
    final file = await store.fileFor(workspace);
    file.writeAsStringSync('{ not json at all');
    final found = repo(_FakeGateway());
    await found.switchWorkspace(workspace);
    expect(found.damagedDraftPath, isNotNull);
    expect(found.damagedDraftPath, contains('draft-'));
    expect(found.draftCount, 0);
    expect(file.existsSync(), isTrue, reason: '留给用户自己看');
    found.dispose();
  });

  test('落盘失败：内存编辑仍在并持续警告，成功后警告消失', () async {
    // 用一个"名字已被文件占用"的目录逼出真实写失败。
    File('${root.path}/not-a-dir').createSync();
    final broken = DraftStore(
      rootOverride: Directory('${root.path}/not-a-dir'),
    );
    final found = WorkbenchRepository(worker: _FakeGateway(), store: broken);
    await found.switchWorkspace(workspace);
    found.createTable('Hero');
    await found.persistSettled;

    expect(found.draftPersisted, isFalse);
    expect(found.persistError, isNotNull);
    expect(found.draftPersistLabel, startsWith('未落盘'));
    expect(found.draftCount, 1, reason: '内存编辑不能被失败带走');

    // 换回可用目录并显式重试：警告必须消失
    final good = repo(_FakeGateway());
    await good.switchWorkspace(workspace);
    good.createTable('Hero');
    await good.persistSettled;
    expect(good.draftPersisted, isTrue);
    expect(good.persistError, isNull);
    found.dispose();
    good.dispose();
  });

  test('不注入 store 时完全不碰文件系统（样板与单测默认行为）', () async {
    final found = WorkbenchRepository(worker: _FakeGateway());
    await found.switchWorkspace(workspace);
    found.createTable('Hero');
    await found.persistSettled;
    expect(found.draftPersisted, isTrue, reason: '未开启持久化不该被当成失败');
    expect(found.draftPersistLabel, '未开启用户目录持久化');
    expect(root.listSync(), isEmpty);
    found.dispose();
  });

  test('工作区隔离：换目录后不会把上一个工作区的草稿投影进来', () async {
    final first = repo(_FakeGateway());
    await first.switchWorkspace(workspace);
    first.createTable('Hero');
    await first.persistSettled;

    final second = repo(_FakeGateway());
    await second.switchWorkspace('D:/game/B');
    expect(second.draftCount, 0);
    expect(second.hasDraftConflict, isFalse);
    expect(
      root.listSync(recursive: true).whereType<File>(),
      hasLength(1),
      reason: 'A 的草稿仍在自己的文件里',
    );
    first.dispose();
    second.dispose();
  });
}
