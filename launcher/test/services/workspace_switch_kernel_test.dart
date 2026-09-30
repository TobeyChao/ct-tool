import 'dart:io';

import 'package:ct_launcher/app.dart';
import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:ct_launcher/state/schema_draft.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ?? '../native/target/debug/ct';
  final available = File(binary).existsSync();
  late Directory temporary;
  late Directory a;
  late Directory b;
  late WorkerService worker;
  late WorkbenchRepository repository;
  late DraftStore store;

  Future<WorkerService> connected(String root) async {
    final transport = await StdioWorkerTransport.start(
      executable: File(binary).absolute.path,
      workingDirectory: root,
    );
    final service = WorkerService(
      settings: SettingsStore()..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    await service.start(workspaceRoot: root);
    return service;
  }

  void writeWorkspace(Directory directory, String name) {
    Directory('${directory.path}/config/schemas').createSync(recursive: true);
    Directory('${directory.path}/config/types').createSync(recursive: true);
    File(
      '${directory.path}/config/global.yaml',
    ).writeAsStringSync('primary_lang: zh\nsecondary_langs: []\n');
    File(
      '${directory.path}/config/types/${name.toLowerCase()}.yaml',
    ).writeAsStringSync('name: $name\nkind: enum\nvalues:\n  - name: Value1\n');
  }

  setUp(() async {
    if (!available) return;
    temporary = await Directory.systemTemp.createTemp('ct-workspace-switch-');
    a = Directory('${temporary.path}/A');
    b = Directory('${temporary.path}/B');
    writeWorkspace(a, 'OnlyA');
    writeWorkspace(b, 'OnlyB');
    store = DraftStore(rootOverride: Directory('${temporary.path}/storage'));
    worker = WorkerService(
      settings: SettingsStore()..runtimePath = File(binary).absolute.path,
    );
    repository = WorkbenchRepository(worker: worker, store: store);
    expect(
      await switchWorkerWorkspace(
        a.path,
        repository: repository,
        worker: worker,
      ),
      isTrue,
    );
  });

  tearDown(() async {
    if (!available) return;
    await repository.persistSettled;
    await worker.stop();
    repository.dispose();
    worker.dispose();
    await temporary.delete(recursive: true);
  });

  test(
    'A to B loads B resources and baseline before allowing schema writes',
    () async {
      final oldBaseline = repository.schemaBaseline;
      var detached = false;
      expect(
        await switchWorkerWorkspace(
          b.path,
          repository: repository,
          worker: worker,
          onConnecting: () async => detached = true,
        ),
        isTrue,
      );
      expect(detached, isTrue);
      expect(repository.workspaceRoot, b.path);
      expect(repository.resources.map((resource) => resource.name), ['OnlyB']);
      expect(repository.schemaBaseline, isNot(oldBaseline));
      repository.createEnum('CreatedInB');
      await repository.requestCandidate();
      expect(repository.candidateProblems, isEmpty);
      expect(repository.canSave, isTrue);
      expect(await repository.saveDraft(), isNotNull);
      expect(
        repository.resources.map((resource) => resource.name),
        containsAll(['OnlyB', 'CreatedInB']),
      );
      expect(
        File('${a.path}/config/types/createdinb.yaml').existsSync(),
        isFalse,
      );
      expect(
        File('${b.path}/config/types/createdinb.yaml').existsSync(),
        isTrue,
      );
    },
    skip: !available,
  );

  test('B recovery uses B baseline and retains outgoing A draft', () async {
    final bWorker = await connected(b.path);
    late String bBaseline;
    try {
      final listed =
          await bWorker.query(Methods.resourcesList, workspaceRoot: b.path)
              as Map<String, Object?>;
      bBaseline = listed['schemaRevision']! as String;
    } finally {
      await bWorker.stop();
      bWorker.dispose();
    }
    await store.save(
      DraftEnvelope(
        formatVersion: DraftEnvelope.currentFormat,
        workspaceKey: b.path,
        baseline: bBaseline,
        commands: [SchemaCommands.addEnum('RecoveredB')],
        cursor: 1,
        savedAt: DateTime.now(),
      ),
    );
    final aBaseline = repository.schemaBaseline;
    repository.createEnum('OutgoingA');
    expect(
      await switchWorkerWorkspace(
        b.path,
        repository: repository,
        worker: worker,
      ),
      isTrue,
    );
    expect(repository.schemaBaseline, bBaseline);
    expect(repository.hasDraftConflict, isFalse);
    expect(
      repository.resources.map((resource) => resource.name),
      containsAll(['OnlyB', 'RecoveredB']),
    );
    final outgoing = await store.load(
      workspaceKey: a.path,
      baseline: aBaseline,
    );
    expect(outgoing.outcome, DraftOutcome.restored);
    expect(
      (outgoing.envelope!.commands.single.payload['resource'] as Map)['name'],
      'OutgoingA',
    );
  }, skip: !available);

  test('failed B connection never loads A schema under B', () async {
    worker.settings.runtimePath = '${temporary.path}/missing-ct';
    expect(
      await switchWorkerWorkspace(
        b.path,
        repository: repository,
        worker: worker,
      ),
      isTrue,
    );
    expect(repository.workspaceRoot, b.path);
    expect(repository.resources, isEmpty);
    expect(repository.schemaBaseline, isEmpty);
    expect(repository.loadError, isNotNull);
    expect(worker.status, WorkerStatus.failed);
    expect(await repository.requestCandidate(), isNull);
    expect(repository.canSave, isFalse);
  }, skip: !available);

  test('unbinding closes old worker and clears schema view', () async {
    expect(
      await switchWorkerWorkspace('', repository: repository, worker: worker),
      isTrue,
    );
    expect(repository.workspaceRoot, isEmpty);
    expect(repository.resources, isEmpty);
    expect(worker.status, WorkerStatus.stopped);
  }, skip: !available);
}
