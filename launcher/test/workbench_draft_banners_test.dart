import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 草稿持久化横幅（任务 3.5 界面侧）。
///
/// 真文件系统读写全部放在 setUp 里：testWidgets 的测试体内等真实 IO 会卡住，
/// 所以仓库在工作区目录建好后就完成 switchWorkspace/restore。
class _FakeGateway implements KernelGateway {
  _FakeGateway(this.baseline);

  final String baseline;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-banner';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 5,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 0,
      },
      Methods.resourcesList => {
        'revision': 5,
        'schemaRevision': baseline,
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
          },
        ],
      },
      Methods.tablePreview => {
        'revision': 5,
        'columns': const [
          {'name': 'Id', 'typeExpr': 'int32', 'role': 'primary'},
        ],
        'rows': const <Object?>[],
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }
}

void main() {
  const currentBaseline = 'baseline-1';
  const conflictWorkspace = 'D:/game/conflict';
  const restoreWorkspace = 'D:/game/restore';
  const damagedWorkspace = 'D:/game/damaged';
  const brokenWorkspace = 'D:/game/broken';

  late Directory root;
  late DraftStore store;
  late WorkbenchRepository conflictRepo;
  late WorkbenchRepository restoreRepo;
  late WorkbenchRepository damagedRepo;
  late WorkbenchRepository brokenRepo;

  Future<void> seed(
    DraftStore sink, {
    required String workspaceKey,
    required String base,
    int cursor = 1,
    bool raw = false,
  }) async {
    final file = await sink.fileFor(workspaceKey);
    if (raw) {
      await file.writeAsString('{ this is not json');
      return;
    }
    await sink.save(
      DraftEnvelope(
        formatVersion: DraftEnvelope.currentFormat,
        workspaceKey: workspaceKey,
        baseline: base,
        commands: const [
          SchemaCommand(
            kind: 'add_resource',
            payload: {
              'kind': 'table',
              'resource': {
                'table': 'Hero',
                'primary': 'Id',
                'fields': [
                  {'name': 'Id', 'type': 'int32'},
                ],
              },
            },
          ),
        ],
        cursor: cursor,
        savedAt: DateTime(2026, 9, 19, 8, 5),
      ),
    );
  }

  setUp(() async {
    root = await Directory.systemTemp.createTemp('ct-banner-');
    store = DraftStore(rootOverride: root);
    await seed(store, workspaceKey: conflictWorkspace, base: 'baseline-old');
    await seed(store, workspaceKey: restoreWorkspace, base: currentBaseline);
    await seed(
      store,
      workspaceKey: damagedWorkspace,
      base: currentBaseline,
      raw: true,
    );
    // 目录名被一个文件占住：落盘必然失败。
    File('${root.path}/blocked').createSync();

    conflictRepo = WorkbenchRepository(
      worker: _FakeGateway(currentBaseline),
      store: store,
    );
    restoreRepo = WorkbenchRepository(
      worker: _FakeGateway(currentBaseline),
      store: store,
    );
    damagedRepo = WorkbenchRepository(
      worker: _FakeGateway(currentBaseline),
      store: store,
    );
    brokenRepo = WorkbenchRepository(
      worker: _FakeGateway(currentBaseline),
      store: DraftStore(rootOverride: Directory('${root.path}/blocked')),
    );
    await conflictRepo.switchWorkspace(conflictWorkspace);
    await restoreRepo.switchWorkspace(restoreWorkspace);
    await damagedRepo.switchWorkspace(damagedWorkspace);
    await brokenRepo.switchWorkspace(brokenWorkspace);
    brokenRepo.createTable('Fellow');
    await brokenRepo.persistSettled;
  });

  tearDown(() async {
    conflictRepo.dispose();
    restoreRepo.dispose();
    damagedRepo.dispose();
    brokenRepo.dispose();
    try {
      await root.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  });

  Future<SettingsStore> openOverview(
    WidgetTester tester,
    WorkbenchRepository repo,
  ) async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsStore();
    await settings.load();
    tester.view.physicalSize = const Size(1500, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    addTearDown(settings.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: repo,
          refresh: Listenable.merge([repo, settings]),
          draft: repo,
          settings: settings,
        ),
      ),
    );
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    await tester.tap(find.byIcon(Icons.dashboard_outlined));
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    return settings;
  }

  testWidgets('基线冲突只提示并允许显式丢弃，不自动套用', (tester) async {
    expect(conflictRepo.hasDraftConflict, isTrue);
    expect(conflictRepo.draftCount, 0, reason: '提示不等于套用');
    await openOverview(tester, conflictRepo);
    expect(find.byKey(const ValueKey('wb.draftConflict')), findsOneWidget);
    expect(find.textContaining('基线已变'), findsOneWidget);

    conflictRepo.discardStoredDraft();
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(find.byKey(const ValueKey('wb.draftConflict')), findsNothing);
    expect(conflictRepo.hasDraftConflict, isFalse);
  });

  testWidgets('损坏草稿给出路径并保留供查看', (tester) async {
    expect(damagedRepo.damagedDraftPath, isNotNull);
    expect(damagedRepo.draftCount, 0);
    await openOverview(tester, damagedRepo);
    expect(find.byKey(const ValueKey('wb.draftDamaged')), findsOneWidget);
    expect(find.textContaining('格式不认识'), findsOneWidget);
  });

  testWidgets('同基线重启自动恢复命令与游标，不出现冲突提示', (tester) async {
    expect(restoreRepo.draftCount, 1);
    expect(restoreRepo.cursor, 1);
    expect(restoreRepo.hasDraftConflict, isFalse);
    await openOverview(tester, restoreRepo);
    expect(find.byKey(const ValueKey('wb.draftConflict')), findsNothing);
    expect(restoreRepo.resourceNamed('Hero'), isNotNull);
    await tester.tap(find.byIcon(Icons.table_chart_outlined).first);
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(
      find.byKey(const ValueKey('wb.draftPersistState')),
      findsOneWidget,
      reason: "编辑面板要显示落盘状态",
    );
    expect(find.textContaining('落盘：已落盘'), findsOneWidget);
  });

  testWidgets('落盘失败持续警告，内存编辑仍在', (tester) async {
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(brokenRepo.draftCount, 1, reason: '写失败不能带走内存编辑');
    expect(brokenRepo.draftPersisted, isFalse);
    await openOverview(tester, brokenRepo);
    expect(find.byKey(const ValueKey('wb.draftNotPersisted')), findsOneWidget);
    expect(find.textContaining('草稿尚未落盘'), findsOneWidget);
  });

  testWidgets('旧浏览器草稿提示只说一次，确认状态跨重启保留', (tester) async {
    final settings = await openOverview(tester, restoreRepo);
    expect(find.byKey(const ValueKey('wb.legacyDraftNotice')), findsOneWidget);
    expect(find.textContaining('IndexedDB'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('wb.legacyDraftAck')));
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 20));
    }
    expect(find.byKey(const ValueKey('wb.legacyDraftNotice')), findsNothing);

    final again = SettingsStore();
    await again.load();
    expect(again.legacyDraftNoticeSeen, isTrue);
    again.dispose();
    expect(settings.legacyDraftNoticeSeen, isTrue);
  });
}
