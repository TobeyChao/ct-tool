import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/exit_coordinator.dart';
import 'package:ct_launcher/services/exit_guard.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/services/window_options.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:window_manager/window_manager.dart';

// Run twice in separate macOS host processes, preserving only a temporary store.
// Both paths are mandatory: this test never falls back to the real gd workspace.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const rootPath = String.fromEnvironment('CT_DRAFT_TEST_ROOT');
  const binary = String.fromEnvironment('CT_WORKER_BIN');
  const phase = String.fromEnvironment('CT_RESTART_PHASE');

  testWidgets('native draft survives immediate preserved exit and app restart', (
    tester,
  ) async {
    expect(rootPath, isNotEmpty);
    expect(binary, isNotEmpty);
    expect(['write', 'restore'], contains(phase));
    final root = Directory(rootPath);
    final workspace = Directory('$rootPath/workspace');
    expect(File('$rootPath/TEST-FIXTURE').existsSync(), isTrue);
    expect(File(binary).existsSync(), isTrue);
    final settings = SettingsStore()
      ..workspacePath = workspace.path
      ..runtimePath = binary;
    final transport = await StdioWorkerTransport.start(
      executable: binary,
      workingDirectory: workspace.path,
    );
    final worker = WorkerService(
      settings: settings,
      connect: () async => transport,
    );
    final repo = WorkbenchRepository(
      worker: worker,
      store: DraftStore(rootOverride: root),
    );
    var stopped = false;
    try {
      await worker.start();
      expect(
        worker.status,
        WorkerStatus.ready,
        reason: worker.failureReason ?? '',
      );
      expect(await repo.switchWorkspace(workspace.path), isTrue);
      await windowManager.ensureInitialized();
      await windowManager.waitUntilReadyToShow(
        desktopWindowOptions(),
        () async {
          await windowManager.show();
          await windowManager.focus();
        },
      );
      await tester.pumpWidget(
        MaterialApp(
          theme: buildCtTheme(),
          home: WorkbenchScreen(
            data: repo,
            refresh: repo,
            draft: repo,
            workspaceKey: 'restart-fixture',
            showDesktopTitleBar: true,
            bannerLabel: '原生内核已连接 · 退出恢复验收',
          ),
        ),
      );
      await tester.pumpAndSettle();
      if (phase == 'write') {
        repo.createTable('RestartHero');
        repo.renameResource('RestartHero', 'RestartBoss');
        repo.undoDraft();
        // No wait between the final edit and the real exit coordinator request.
        final coordinator = ExitCoordinator(
          freezeEditing: repo.freezeDraftEditing,
          unfreezeEditing: repo.unfreezeDraftEditing,
          decide: () async => ExitDecision.exitNow,
          flushDraft: repo.flushDraft,
          retryDraft: repo.persistDraft,
          discardDraft: repo.discardDraftAndPersist,
          onPersistenceFailure: () async => ExitPersistenceDecision.stay,
          stopWorker: () async {
            expect(repo.draftPersisted, isTrue);
            expect(
              (await repo.store!.load(
                workspaceKey: repo.draftKey,
                baseline: repo.schemaBaseline,
              )).envelope!.cursor,
              1,
            );
            await worker.stop();
            stopped = true;
          },
        );
        expect(await coordinator.request(), ExitDecision.exitNow);
      } else {
        expect(repo.commands, hasLength(2));
        expect(repo.cursor, 1);
        expect(repo.canRedo, isTrue);
        expect(repo.resources.map((r) => r.name), contains('RestartHero'));
        expect(
          repo.resources.map((r) => r.name),
          isNot(contains('RestartBoss')),
        );
        expect(repo.draftPersisted, isTrue);
        await worker.stop();
        stopped = true;
      }
      expect(await transport.exitCode, 0);
      await File('$rootPath/$phase.json').writeAsString(
        jsonEncode({
          'phase': phase,
          'appPid': pid,
          'commands': repo.commands.map((c) => c.toJson()).toList(),
          'cursor': repo.cursor,
          'redo': repo.canRedo,
          'resources': repo.resources.map((r) => r.name).toList(),
          'persisted': repo.draftPersisted,
          'workerExitCode': await transport.exitCode,
        }),
        flush: true,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
    } finally {
      await repo.persistSettled;
      if (!stopped) await worker.stop();
      repo.dispose();
      worker.dispose();
    }
  });
}
