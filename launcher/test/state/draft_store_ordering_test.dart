import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/state/draft_store.dart';
import 'package:flutter_test/flutter_test.dart';

const _key = 'D:/game/A';
const _baseline = 'base-1';

DraftEnvelope _envelope(String name, {String key = _key}) => DraftEnvelope(
  formatVersion: 1,
  workspaceKey: key,
  baseline: _baseline,
  commands: [
    SchemaCommand(
      kind: 'add_resource',
      payload: {
        'resource': {'table': name},
      },
    ),
    const SchemaCommand(kind: 'rename_field', payload: {'field': 'hp'}),
  ],
  cursor: 1,
  savedAt: DateTime(2026, 9, 30),
);

class _Gate {
  final entered = Completer<void>();
  final released = Completer<void>();

  Future<void> pause() async {
    entered.complete();
    await released.future;
  }

  void release() {
    if (!released.isCompleted) released.complete();
  }
}

class _Access extends DraftFileAccess {
  final events = <String>[];
  _Gate? writeGate;
  _Gate? renameGate;
  _Gate? deleteGate;
  String? failNext;

  void _fail(String operation, File file) {
    if (failNext != operation) return;
    failNext = null;
    throw FileSystemException('injected $operation failure', file.path);
  }

  @override
  Future<void> write(File file, String contents) async {
    events.add(
      'write:${jsonDecode(contents)['commands'][0]['payload']['resource']['table']}',
    );
    final gate = writeGate;
    writeGate = null;
    if (gate != null) await gate.pause();
    _fail('write', file);
    await super.write(file, contents);
  }

  @override
  Future<void> rename(File file, String target) async {
    events.add('rename');
    final gate = renameGate;
    renameGate = null;
    if (gate != null) await gate.pause();
    _fail('rename', file);
    await super.rename(file, target);
  }

  @override
  Future<void> delete(File file) async {
    events.add(file.path.endsWith('.tmp') ? 'delete-temp' : 'delete');
    final gate = deleteGate;
    deleteGate = null;
    if (gate != null) await gate.pause();
    _fail('delete', file);
    await super.delete(file);
  }

  @override
  Future<String> read(File file) async {
    events.add('read');
    return super.read(file);
  }
}

class _DirectoryStore extends DraftStore {
  _DirectoryStore(this.target, {super.fileAccess, this.resolutionGate});

  final Directory target;
  final _Gate? resolutionGate;

  @override
  Future<Directory> directory() async {
    if (resolutionGate != null) await resolutionGate!.pause();
    return target;
  }
}

class _UnavailableDirectoryStore extends DraftStore {
  _UnavailableDirectoryStore(this.gate);

  final _Gate gate;

  @override
  Future<Directory> directory() async {
    await gate.pause();
    throw const FileSystemException('injected directory failure');
  }
}

// Attach an error observer immediately, including while a task is blocked.
Future<Object?> _observed<T>(Future<T> operation) =>
    operation.then<Object?>((value) => value, onError: (Object error) => error);

// All identities in these tests are pre-created directories. A single event
// turn lets already-requested operations register without relying on I/O sleeps.
Future<void> _turn() => Future<void>(() {});

void main() {
  late Directory root;
  late Directory drafts;
  late _Access access;
  late DraftStore store;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('ct-draft-ordering-');
    drafts = await Directory('${root.path}/drafts').create();
    access = _Access();
    store = _DirectoryStore(drafts, fileAccess: access);
  });

  tearDown(() async {
    await root.delete(recursive: true);
  });

  test(
    'same target across stores queues complete saves in call order',
    () async {
      final gate = _Gate();
      access.renameGate = gate;
      final first = _observed(store.save(_envelope('First')));
      await gate.entered.future;
      final other = _DirectoryStore(drafts, fileAccess: access);
      final second = _observed(other.save(_envelope('Second')));
      try {
        await _turn();
        expect(access.events.where((e) => e.startsWith('write:')), [
          'write:First',
        ]);
      } finally {
        gate.release();
        final results = await Future.wait([first, second]);
        expect(results, [null, null]);
      }
      final loaded = await store.load(workspaceKey: _key, baseline: _baseline);
      expect(loaded.envelope!.toJson(), _envelope('Second').toJson());
      expect(
        File('${drafts.path}/${DraftStore.fileName(_key)}.tmp').existsSync(),
        isFalse,
      );
    },
  );

  test('save then clear cannot resurrect a discarded draft', () async {
    final gate = _Gate();
    access.renameGate = gate;
    final save = _observed(store.save(_envelope('First')));
    await gate.entered.future;
    var cleared = false;
    final clear = _observed(store.clear(_key).then((_) => cleared = true));
    try {
      await _turn();
      expect(cleared, isFalse, reason: 'clear must wait for the older save');
    } finally {
      gate.release();
      await Future.wait([save, clear]);
    }
    expect((await store.fileFor(_key)).existsSync(), isFalse);
  });

  test('load waits for publication and never deletes an active temp', () async {
    final gate = _Gate();
    access.renameGate = gate;
    final save = _observed(store.save(_envelope('First')));
    await gate.entered.future;
    final load = _observed(store.load(workspaceKey: _key, baseline: _baseline));
    try {
      await _turn();
      expect(access.events, isNot(contains('delete-temp')));
      expect(
        File('${drafts.path}/${DraftStore.fileName(_key)}.tmp').existsSync(),
        isTrue,
      );
    } finally {
      gate.release();
      expect(await save, isNull);
    }
    final loaded = await load;
    expect(loaded, isA<DraftLoad>());
    expect((loaded! as DraftLoad).outcome, DraftOutcome.restored);
    expect((loaded as DraftLoad).leftoverTemp, isFalse);
  });

  test('preserve waits for save and archives its completed envelope', () async {
    final gate = _Gate();
    access.renameGate = gate;
    final save = _observed(store.save(_envelope('First')));
    await gate.entered.future;
    var completed = false;
    final preserve = _observed(
      store.preserve(_key).then((path) {
        completed = true;
        return path;
      }),
    );
    try {
      await _turn();
      expect(completed, isFalse);
    } finally {
      gate.release();
      expect(await save, isNull);
    }
    final path = await preserve;
    expect(path, isA<String>());
    expect(
      jsonDecode(File(path! as String).readAsStringSync()),
      _envelope('First').toJson(),
    );
    expect((await store.fileFor(_key)).existsSync(), isFalse);
  });

  test('directory resolution order cannot reorder public calls', () async {
    final gate = _Gate();
    final delayed = _DirectoryStore(
      drafts,
      fileAccess: access,
      resolutionGate: gate,
    );
    final first = _observed(delayed.save(_envelope('First')));
    await gate.entered.future;
    final second = _observed(store.save(_envelope('Second')));
    try {
      await _turn();
      expect(
        access.events,
        isEmpty,
        reason: 'earlier unresolved target must register first',
      );
    } finally {
      gate.release();
      expect(await Future.wait([first, second]), [null, null]);
    }
    final loaded = await store.load(workspaceKey: _key, baseline: _baseline);
    expect(loaded.envelope!.toJson(), _envelope('Second').toJson());
  });

  test('save captures nested payload and command list at the call', () async {
    final gate = _Gate();
    final delayed = _DirectoryStore(
      drafts,
      fileAccess: access,
      resolutionGate: gate,
    );
    final envelope = _envelope('Original');
    final save = _observed(delayed.save(envelope));
    await gate.entered.future;
    (envelope.commands.first.payload['resource']!
            as Map<String, Object?>)['table'] =
        'Mutated';
    envelope.commands.removeLast();
    gate.release();
    expect(await save, isNull);
    final loaded = await store.load(workspaceKey: _key, baseline: _baseline);
    expect(loaded.envelope!.toJson(), _envelope('Original').toJson());
  });

  for (final loading in [false, true]) {
    test(
      'directory failure releases admission for later save (load=$loading)',
      () async {
        final gate = _Gate();
        final unavailable = _UnavailableDirectoryStore(gate);
        final failed = _observed(
          loading
              ? unavailable.load(workspaceKey: _key, baseline: _baseline)
              : unavailable.save(_envelope('Unavailable')),
        );
        await gate.entered.future;
        final retry = _observed(store.save(_envelope('Retry')));
        try {
          await _turn();
          expect(access.events, isEmpty);
        } finally {
          gate.release();
          final outcome = await failed;
          if (loading) {
            expect(outcome, isA<DraftLoad>());
            expect((outcome! as DraftLoad).outcome, DraftOutcome.none);
            expect(
              (outcome as DraftLoad).reason,
              contains('injected directory failure'),
            );
          } else {
            expect(outcome, isA<FileSystemException>());
          }
          expect(await retry, isNull);
        }
        expect(
          (await store.load(
            workspaceKey: _key,
            baseline: _baseline,
          )).envelope!.toJson(),
          _envelope('Retry').toJson(),
        );
      },
    );
  }

  for (final operation in ['write', 'rename', 'delete']) {
    test(
      '$operation failure reaches caller while queued retry succeeds',
      () async {
        if (operation == 'delete') await store.save(_envelope('Existing'));
        final gate = _Gate();
        if (operation == 'write') access.writeGate = gate;
        if (operation == 'rename') access.renameGate = gate;
        if (operation == 'delete') access.deleteGate = gate;
        access.failNext = operation;
        final failed = _observed(
          operation == 'delete'
              ? store.clear(_key)
              : store.save(_envelope('Failed')),
        );
        await gate.entered.future;
        final retry = _observed(store.save(_envelope('Retry')));
        try {
          await _turn();
          expect(access.events, isNot(contains('write:Retry')));
        } finally {
          gate.release();
          final error = await failed;
          expect(error, isA<FileSystemException>());
          expect(
            (error! as FileSystemException).message,
            'injected $operation failure',
          );
          expect(await retry, isNull);
        }
        final loaded = await store.load(
          workspaceKey: _key,
          baseline: _baseline,
        );
        expect(loaded.envelope!.toJson(), _envelope('Retry').toJson());
        expect(
          File('${drafts.path}/${DraftStore.fileName(_key)}.tmp').existsSync(),
          isFalse,
        );
        // Exercise fresh admission after the failed chain has fully drained.
        await store.clear(_key);
        await _DirectoryStore(
          drafts,
          fileAccess: access,
        ).save(_envelope('Fresh'));
        expect(
          (await store.load(
            workspaceKey: _key,
            baseline: _baseline,
          )).envelope!.toJson(),
          _envelope('Fresh').toJson(),
        );
      },
    );
  }

  test('different files run while another publication is blocked', () async {
    final gate = _Gate();
    access.renameGate = gate;
    final first = _observed(store.save(_envelope('Blocked')));
    await gate.entered.future;
    try {
      await store.save(_envelope('Independent', key: 'D:/game/B'));
      final loaded = await store.load(
        workspaceKey: 'D:/game/B',
        baseline: _baseline,
      );
      expect(
        loaded.envelope!.toJson(),
        _envelope('Independent', key: 'D:/game/B').toJson(),
      );
      expect(gate.released.isCompleted, isFalse);
    } finally {
      gate.release();
      expect(await first, isNull);
    }
  });

  test(
    'same filename in different real directories runs in parallel',
    () async {
      final otherDirectory = await Directory(
        '${root.path}/independent',
      ).create();
      final other = _DirectoryStore(otherDirectory, fileAccess: access);
      final gate = _Gate();
      access.renameGate = gate;
      final first = _observed(store.save(_envelope('Blocked')));
      await gate.entered.future;
      try {
        await other.save(_envelope('Independent'));
        expect(
          (await other.load(
            workspaceKey: _key,
            baseline: _baseline,
          )).envelope!.toJson(),
          _envelope('Independent').toJson(),
        );
        expect(gate.released.isCompleted, isFalse);
      } finally {
        gate.release();
        expect(await first, isNull);
      }
    },
  );

  test('symlink aliases share the same real file queue', () async {
    final alias = await Link('${root.path}/alias').create(drafts.path);
    final other = _DirectoryStore(Directory(alias.path), fileAccess: access);
    final gate = _Gate();
    access.renameGate = gate;
    final first = _observed(store.save(_envelope('First')));
    await gate.entered.future;
    final second = _observed(other.save(_envelope('Second')));
    try {
      await _turn();
      expect(access.events, isNot(contains('write:Second')));
    } finally {
      gate.release();
      expect(await Future.wait([first, second]), [null, null]);
    }
    expect(
      (await store.load(
        workspaceKey: _key,
        baseline: _baseline,
      )).envelope!.toJson(),
      _envelope('Second').toJson(),
    );
  });

  test(
    'requests added to an active tail survive earlier tail cleanup',
    () async {
      final firstGate = _Gate();
      final secondGate = _Gate();
      access.renameGate = firstGate;
      final first = _observed(store.save(_envelope('First')));
      await firstGate.entered.future;
      final second = _observed(store.save(_envelope('Second')));
      access.renameGate = secondGate;
      firstGate.release();
      expect(await first, isNull);
      await secondGate.entered.future;
      final third = _observed(
        _DirectoryStore(drafts, fileAccess: access).save(_envelope('Third')),
      );
      final clear = _observed(store.clear(_key));
      try {
        await _turn();
        expect(access.events, isNot(contains('write:Third')));
      } finally {
        secondGate.release();
        expect(await Future.wait([second, third, clear]), [null, null, null]);
      }
      expect((await store.fileFor(_key)).existsSync(), isFalse);
      await store.save(_envelope('AfterDrain'));
      expect(
        (await store.load(
          workspaceKey: _key,
          baseline: _baseline,
        )).envelope!.toJson(),
        _envelope('AfterDrain').toJson(),
      );
    },
  );

  test(
    'failed preserve retains file and does not poison later operations',
    () async {
      await store.save(_envelope('Original'));
      access.failNext = 'rename';
      final preserve = _observed(store.preserve(_key));
      final next = _observed(store.save(_envelope('Next')));
      expect(await preserve, isA<FileSystemException>());
      expect(await next, isNull);
      expect(
        (await store.load(
          workspaceKey: _key,
          baseline: _baseline,
        )).envelope!.toJson(),
        _envelope('Next').toJson(),
      );
    },
  );

  test(
    'legacy temp deletion failure still reports and restores formal file',
    () async {
      await store.save(_envelope('Good'));
      final file = await store.fileFor(_key);
      final tmp = File('${file.path}.tmp')..writeAsStringSync('interrupted');
      access.failNext = 'delete';
      final loaded = await store.load(workspaceKey: _key, baseline: _baseline);
      expect(loaded.leftoverTemp, isTrue);
      expect(loaded.envelope!.toJson(), _envelope('Good').toJson());
      expect(tmp.existsSync(), isTrue);
      await store.save(_envelope('Recovered'));
      expect(tmp.existsSync(), isFalse);
    },
  );
}
