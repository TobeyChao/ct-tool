import 'dart:io';

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 用真实 `ct worker` 验证任务 3.1 的两个验收点：
/// 空工作区里能否创建 Table/Record/Enum，以及同一草稿内的类型相互引用。
/// 客户端不自行判断合法性——一切结论来自 `schema.candidate`。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({WorkbenchRepository repo, WorkerService worker, Directory ws})>
  openDraftWorkspace({List<String> schemas = const []}) async {
    final ws = await Directory.systemTemp.createTemp('ct-draft-');
    Directory('${ws.path}/config/schemas').createSync(recursive: true);
    File(
      '${ws.path}/config/global.yaml',
    ).writeAsStringSync('primary_lang: zh\n');
    for (final name in schemas) {
      File('${ws.path}/config/schemas/$name.yaml').writeAsStringSync(
        'table: $name\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n',
      );
    }
    final transport = await StdioWorkerTransport.start(
      executable: File(binary).absolute.path,
      workingDirectory: ws.path,
    );
    final worker = WorkerService(
      settings: SettingsStore()
        ..workspacePath = ws.path
        ..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    await worker.start();
    final repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(ws.path);
    return (repo: repo, worker: worker, ws: ws);
  }

  Future<void> closeAll(
    ({WorkbenchRepository repo, WorkerService worker, Directory ws}) context,
  ) async {
    await context.worker.stop();
    context.repo.dispose();
    try {
      await context.ws.delete(recursive: true);
    } on FileSystemException {
      // 句柄释放有延迟时交给系统临时目录回收
    }
  }

  test(
    '空工作区里创建三类资源：内核候选无阻塞问题',
    () async {
      if (!available) return;
      final opened = await openDraftWorkspace();
      expect(opened.worker.status, WorkerStatus.ready);
      expect(opened.repo.resources, isEmpty, reason: '空工作区应当没有任何资源');
      expect(opened.repo.schemaBaseline.length, 64, reason: '基线必须是 sha256');

      opened.repo.createTable('Hero');
      opened.repo.createRecord('Loot');
      opened.repo.createEnum('Rarity');
      expect(opened.repo.draftCount, 3);

      final candidate = await opened.repo.requestCandidate();
      expect(candidate, isNotNull, reason: opened.repo.draftError ?? '');
      expect(candidate!.problems, isEmpty, reason: '${candidate.problems}');
      expect(
        candidate.netDiff.added.map((ref) => ref.name).toList(),
        unorderedEquals(['Hero', 'Loot', 'Rarity']),
      );
      await closeAll(opened);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '同一草稿内的类型相互引用可被内核接受',
    () async {
      if (!available) return;
      final opened = await openDraftWorkspace();
      opened.repo.createRecord('Loot');
      opened.repo.createTable('Hero');
      // 引用的是「同批草稿里刚创建的 Record」，不是磁盘上的既有类型
      opened.repo.addField('table:Hero', 'Reward', 'Loot');

      final candidate = await opened.repo.requestCandidate();
      expect(candidate, isNotNull, reason: opened.repo.draftError ?? '');
      expect(candidate!.problems, isEmpty, reason: '${candidate.problems}');
      expect(
        opened.repo
            .resourceNamed('Hero')!
            .fields
            .any((field) => field.name == 'Reward' && field.type == 'Loot'),
        isTrue,
      );
      await closeAll(opened);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '未声明的类型由内核拒绝，客户端不自创校验',
    () async {
      if (!available) return;
      final opened = await openDraftWorkspace(schemas: ['Item']);
      opened.repo.addField('table:Item', 'Broken', 'NoSuchType');
      final candidate = await opened.repo.requestCandidate();
      final rejected =
          (candidate?.problems ?? const []).isNotEmpty ||
          opened.repo.draftError != null;
      expect(rejected, isTrue, reason: '内核必须拒绝未知类型：${candidate?.problems}');
      await closeAll(opened);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '改名命令走内核级联：引用方类型文本随之更新',
    () async {
      if (!available) return;
      final opened = await openDraftWorkspace(schemas: ['Item', 'Hero']);
      opened.repo.renameResource('Item', 'Gear');
      final candidate = await opened.repo.requestCandidate();
      expect(candidate, isNotNull, reason: opened.repo.draftError ?? '');
      expect(candidate!.problems, isEmpty, reason: '${candidate.problems}');
      expect(
        candidate.netDiff.changed.map((ref) => ref.name).toList(),
        contains('Gear'),
        reason: '${candidate.netDiff}',
      );
      await closeAll(opened);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );
}
