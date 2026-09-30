import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:ct_launcher/state/schema_draft.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

class _Gateway implements KernelGateway {
  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'persistence';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async => switch (method) {
    Methods.workspaceOpen => {
      'revision': 1,
      'status': 'ready',
      'recovery': {'needed': false, 'journals': <String>[]},
      'tables': 0,
      'records': 0,
      'enums': 0,
    },
    Methods.resourcesList => {
      'revision': 1,
      'schemaRevision': 'base',
      'resources': <Object?>[],
    },
    _ => throw StateError(method),
  };
}

class _ControlledStore extends DraftStore {
  final saves = <(DraftEnvelope, Completer<void>)>[];
  final clears = <Completer<void>>[];
  final operations = <String>[];
  Completer<DraftLoad>? nextLoad;

  @override
  Future<void> save(DraftEnvelope envelope) {
    final completion = Completer<void>();
    saves.add((envelope, completion));
    operations.add('save:${envelope.commands.length}');
    return completion.future;
  }

  @override
  Future<void> clear(String workspaceKey) {
    final completion = Completer<void>();
    clears.add(completion);
    operations.add('clear');
    return completion.future;
  }

  @override
  Future<DraftLoad> load({
    required String workspaceKey,
    required String baseline,
  }) {
    final blocked = nextLoad;
    nextLoad = null;
    return blocked?.future ?? Future.value(const DraftLoad(DraftOutcome.none));
  }
}

Future<void> _turn() async {
  await Future<void>.delayed(Duration.zero);
}

void main() {
  test('latest snapshot remains pending while earlier save finishes', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    repo.createTable('Hero');
    repo.renameResource('Hero', 'Boss');
    expect(repo.draftPersisted, isFalse);
    store.saves.first.$2.complete();
    await _turn();
    expect(repo.draftPersisted, isFalse);
    store.saves.last.$2.complete();
    await repo.persistSettled;
    expect(repo.draftPersisted, isTrue);
    expect(store.saves.last.$1.commands, hasLength(2));
    repo.dispose();
  });

  test(
    'persistSettled waits every operation even if last completes first',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      repo.createTable('Hero');
      repo.renameResource('Hero', 'Boss');
      var settled = false;
      final waiting = repo.persistSettled.then((_) => settled = true);
      store.saves.last.$2.complete();
      await _turn();
      expect(settled, isFalse);
      store.saves.first.$2.complete();
      await waiting;
      repo.dispose();
    },
  );

  test('persistSettled includes requests registered while awaiting', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    repo.createTable('Hero');
    var settled = false;
    final waiting = repo.persistSettled.then((_) => settled = true);
    repo.renameResource('Hero', 'Boss');
    store.saves.first.$2.complete();
    await _turn();
    expect(settled, isFalse);
    store.saves.last.$2.complete();
    await waiting;
    repo.dispose();
  });

  test('late restore cannot replace edits made after load started', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    final load = Completer<DraftLoad>();
    store.nextLoad = load;
    final restoring = repo.restoreDraft();
    repo.createTable('Fresh');
    load.complete(
      DraftLoad(
        DraftOutcome.restored,
        envelope: DraftEnvelope(
          formatVersion: 1,
          workspaceKey: '/workspace/A',
          baseline: 'base',
          commands: [SchemaCommands.addTable('Old')],
          cursor: 1,
          savedAt: DateTime(2026),
        ),
      ),
    );
    await restoring;
    expect(repo.resources.map((r) => r.name), contains('Fresh'));
    expect(repo.resources.map((r) => r.name), isNot(contains('Old')));
    store.saves.single.$2.complete();
    await repo.persistSettled;
    repo.dispose();
  });

  test('discard failure preserves conflict identity and reason', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    final load = Completer<DraftLoad>();
    store.nextLoad = load;
    final restoring = repo.restoreDraft();
    load.complete(
      DraftLoad(
        DraftOutcome.conflict,
        reason: 'changed',
        envelope: DraftEnvelope(
          formatVersion: 1,
          workspaceKey: '/workspace/A',
          baseline: 'old-base',
          commands: [SchemaCommands.addTable('Old')],
          cursor: 1,
          savedAt: DateTime(2026),
        ),
      ),
    );
    await restoring;
    final discarding = repo.discardStoredDraft();
    store.clears.single.completeError(StateError('disk full'));
    await discarding;
    expect(repo.hasDraftConflict, isTrue);
    expect(repo.conflictReason, 'changed');
    expect(repo.persistError, contains('disk full'));
    repo.dispose();
  });
  test('switch waits pending save and retains A after failure', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    repo.createTable('Fresh');
    final switching = repo.switchWorkspace('/workspace/B');
    expect(repo.editingFrozen, isTrue);
    repo.createTable('Blocked');
    expect(repo.commands, hasLength(1));
    store.saves.single.$2.completeError(StateError('disk full'));
    expect(await switching, isFalse);
    expect(repo.workspaceRoot, '/workspace/A');
    expect(repo.resources.map((r) => r.name), contains('Fresh'));
    expect(repo.editingFrozen, isFalse);
    final retry = repo.persistDraft();
    store.saves.last.$2.complete();
    await retry;
    expect(await repo.switchWorkspace('/workspace/B'), isTrue);
    expect(repo.workspaceRoot, '/workspace/B');
    repo.dispose();
  });

  test(
    'freeze blocks edits and switch, but unconditional flush keeps redo',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      repo.createTable('Fresh');
      repo.undoDraft();
      expect(repo.draftCount, 0);
      expect(repo.hasDraftHistory, isTrue);
      repo.freezeDraftEditing();
      expect(await repo.switchWorkspace('/workspace/B'), isFalse);
      repo.createTable('Blocked');
      final flush = repo.flushDraft();
      for (final save in store.saves) {
        save.$2.complete();
      }
      expect(await flush, isTrue);
      expect(store.saves.last.$1.cursor, 0);
      expect(store.saves.last.$1.commands, hasLength(1));
      repo.unfreezeDraftEditing();
      repo.dispose();
    },
  );

  test(
    'pending save and load complete after dispose without notification',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      repo.createTable('Fresh');
      final load = Completer<DraftLoad>();
      store.nextLoad = load;
      final restoring = repo.restoreDraft();
      repo.dispose();
      store.saves.single.$2.complete();
      load.complete(
        const DraftLoad(DraftOutcome.damaged, reason: 'late', path: '/old'),
      );
      await repo.persistSettled;
      expect(await restoring, DraftOutcome.none);
      expect(repo.damagedDraftPath, isNull);
    },
  );

  test('A restore arriving after switch cannot replace B state', () async {
    final store = _ControlledStore();
    final repo = WorkbenchRepository(worker: _Gateway(), store: store);
    await repo.switchWorkspace('/workspace/A');
    final load = Completer<DraftLoad>();
    store.nextLoad = load;
    final restoring = repo.restoreDraft();
    await repo.switchWorkspace('/workspace/B');
    load.complete(
      DraftLoad(
        DraftOutcome.restored,
        envelope: DraftEnvelope(
          formatVersion: 1,
          workspaceKey: '/workspace/A',
          baseline: 'base',
          commands: [SchemaCommands.addTable('Old')],
          cursor: 1,
          savedAt: DateTime(2026),
        ),
      ),
    );
    expect(await restoring, DraftOutcome.none);
    expect(repo.workspaceRoot, '/workspace/B');
    expect(repo.commands, isEmpty);
    repo.dispose();
  });

  test(
    'discard preserves memory until clear succeeds and retry releases it',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      repo.createTable('Fresh');
      store.saves.single.$2.complete();
      await repo.persistSettled;
      repo.freezeDraftEditing();
      final discard = repo.discardDraftAndPersist();
      expect(repo.hasDraftHistory, isTrue);
      store.clears.single.completeError(StateError('clear failed'));
      expect(await discard, isFalse);
      expect(repo.hasDraftHistory, isTrue);
      final retry = repo.discardDraftAndPersist();
      store.clears.last.complete();
      expect(await retry, isTrue);
      expect(repo.hasDraftHistory, isFalse);
      expect(repo.persistError, isNull);
      repo.unfreezeDraftEditing();
      repo.dispose();
    },
  );
  test(
    'listener edit preserves save admission order and flush tracking',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      var nested = false;
      var settled = false;
      Future<void>? flush;
      repo.addListener(() {
        if (!nested && !repo.draftPersisted) {
          nested = true;
          repo.renameResource('Hero', 'Boss');
          flush = repo.persistSettled.then((_) => settled = true);
        }
      });
      repo.createTable('Hero');
      expect(store.operations, ['save:1', 'save:2']);
      store.saves.first.$2.complete();
      await _turn();
      expect(settled, isFalse);
      store.saves.last.$2.complete();
      await flush;
      expect(repo.draftPersisted, isTrue);
      repo.dispose();
    },
  );

  test(
    'listener edit follows admitted clear and is not deleted by it',
    () async {
      final store = _ControlledStore();
      final repo = WorkbenchRepository(worker: _Gateway(), store: store);
      await repo.switchWorkspace('/workspace/A');
      repo.createTable('Hero');
      store.saves.single.$2.complete();
      await repo.persistSettled;
      var nested = false;
      repo.addListener(() {
        if (!nested && !repo.draftPersisted) {
          nested = true;
          repo.renameResource('Hero', 'Boss');
        }
      });
      final discarded = repo.discardDraftAndPersist();
      expect(store.operations, ['save:1', 'clear', 'save:2']);
      store.clears.single.complete();
      expect(await discarded, isFalse, reason: 'new edit superseded discard');
      expect(repo.hasDraftHistory, isTrue);
      store.saves.last.$2.complete();
      await repo.persistSettled;
      expect(repo.draftPersisted, isTrue);
      expect(repo.resources.map((r) => r.name), contains('Boss'));
      repo.dispose();
    },
  );
}
