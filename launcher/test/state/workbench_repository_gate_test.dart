import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// 代次过滤与保存期冻结（native-flutter-workbench 任务 3.8）。
///
/// 三条硬约束：迟到的旧候选不能覆盖当前结论；保存进行中不许再编辑、也不许
/// 重复提交；保存成功后即使状态刷新失败也不得把草稿还回来或要求重存。
class _Gate implements KernelGateway {
  _Gate({this.netDiffChanged = true, this.failListAfterSave = false});

  final bool netDiffChanged;
  final bool failListAfterSave;
  final List<String> methods = [];
  Completer<Object?>? heldCandidate;
  final List<Map<String, Object?>> candidateParams = [];
  Completer<Object?>? heldSave;
  String baseline = 'base-1';
  int saves = 0;

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-gate';

  Map<String, Object?> _diff() => {
    'added': <Object?>[],
    'removed': <Object?>[],
    'changed': netDiffChanged
        ? const [
            {'kind': 'table', 'name': 'Item'},
          ]
        : const <Object?>[],
  };

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    methods.add(method);
    switch (method) {
      case Methods.workspaceOpen:
        return {
          'revision': 1,
          'status': 'ready',
          'recovery': {'needed': false, 'journals': <String>[]},
          'tables': 1,
          'records': 0,
          'enums': 0,
        };
      case Methods.resourcesList:
        if (failListAfterSave && saves > 0) {
          throw WorkerRequestException(
            ErrorBody(code: 'internal', message: '内核连接已断'),
          );
        }
        return {
          'revision': 1,
          'schemaRevision': baseline,
          'resources': [
            {
              'name': 'Item',
              'kind': 'table',
              'sourcePath': 'config/schemas/item.yaml',
            },
          ],
        };
      case Methods.workspaceRecover:
        return {
          'outcome': 'noop',
          'revision': 1,
          'detail': 'no recovery needed',
        };
      case Methods.schemaCandidate:
        final gen = params['draftGeneration']! as int;
        candidateParams.add(params);
        final gate = heldCandidate;
        heldCandidate = null;
        if (gate != null) await gate.future;
        return {
          'candidateHash': 'hash-$gen',
          'draftGeneration': gen,
          'netDiff': _diff(),
          'problems': const <Object?>[],
        };
      case Methods.schemaSave:
        // 与内核同语义：守卫值不符就拒绝，且一个文件都不写。
        if (params['schemaRevision'] != baseline) {
          throw WorkerRequestException(
            const ErrorBody(code: 'busy', message: '草稿基线已变，拒绝保存'),
          );
        }
        final gate = heldSave;
        if (gate != null) await gate.future;
        saves++;
        baseline = 'base-2';
        return {'schemaRevision': 'base-2'};
      default:
        throw StateError('未预期方法 $method');
    }
  }
}

void main() {
  const root = 'D:/game/A';

  Future<WorkbenchRepository> opened(_Gate gate) async {
    final repo = WorkbenchRepository(worker: gate);
    await repo.switchWorkspace(root);
    repo.createTable('Hero');
    return repo;
  }

  test('候选请求各归自己的代次，迟到的旧响应不得覆盖当前 hash', () async {
    final gate = _Gate();
    final repo = await opened(gate);
    final stale = Completer<Object?>();
    gate.heldCandidate = stale;

    final first = repo.requestCandidate();
    final second = await repo.requestCandidate();
    final latestGeneration = gate.candidateParams.last['draftGeneration'];
    expect(second!.candidateHash, 'hash-$latestGeneration');
    expect(repo.candidate!.candidateHash, second.candidateHash);
    expect(repo.candidateBusy, isTrue, reason: '旧请求仍在途，不得提前解除忙碌');

    stale.complete(null);
    expect(await first, isNull);
    expect(repo.candidate!.candidateHash, second.candidateHash);
    expect(repo.candidateBusy, isFalse);
    expect(repo.schemaBaseline, 'base-1', reason: '刷新候选不得推进基线');
    repo.dispose();
  });

  for (final action in ['edit', 'undo', 'redo', 'undoTo', 'discard', 'clear']) {
    for (final failure in ['none', 'structured', 'generic']) {
      test(
        '$action invalidates pending candidate including $failure responses',
        () async {
          final gate = _Gate();
          final repo = await opened(gate);
          if (action == 'redo') repo.undoDraft();
          final held = Completer<Object?>();
          gate.heldCandidate = held;
          final pending = repo.requestCandidate();
          final sentGeneration =
              gate.candidateParams.last['draftGeneration']! as int;
          switch (action) {
            case 'edit':
              repo.createTable('Fresh');
            case 'undo':
              repo.undoDraft();
            case 'redo':
              repo.redoDraft();
            case 'undoTo':
              expect(repo.undoTo(0), isTrue);
            case 'discard':
              repo.discardDraft();
            case 'clear':
              expect(await repo.discardDraftAndPersist(), isTrue);
          }
          expect(repo.candidate, isNull);
          if (failure == 'none') {
            held.complete(null);
          } else if (failure == 'structured') {
            held.completeError(
              WorkerRequestException(
                const ErrorBody(
                  code: 'invalid',
                  message: 'stale rejection',
                  issues: [
                    Issue(
                      code: 'old',
                      message: 'old field issue',
                      resource: 'table:Hero/Id',
                    ),
                  ],
                ),
              ),
            );
          } else {
            held.completeError(StateError('stale failure'));
          }
          expect(await pending, isNull);
          expect(repo.candidate, isNull);
          expect(repo.candidateProblems, isEmpty);
          expect(repo.draftError, isNull);
          expect(repo.candidateBusy, isFalse);
          expect(repo.canSave, isFalse);
          final fresh = await repo.requestCandidate();
          expect(fresh, isNotNull);
          expect(
            gate.candidateParams.last['draftGeneration'],
            greaterThan(sentGeneration),
          );
          repo.dispose();
        },
      );
    }
  }

  for (final failOld in [false, true]) {
    test(
      'switch resets busy and old ${failOld ? 'error' : 'success'} cannot clear new busy',
      () async {
        final gate = _Gate();
        final repo = await opened(gate);
        final old = Completer<Object?>();
        gate.heldCandidate = old;
        final pendingOld = repo.requestCandidate();
        expect(repo.candidateBusy, isTrue);
        expect(await repo.switchWorkspace('D:/game/B'), isTrue);
        expect(repo.candidateBusy, isFalse);
        repo.createTable('Current');
        final current = Completer<Object?>();
        gate.heldCandidate = current;
        final pendingCurrent = repo.requestCandidate();
        if (failOld) {
          old.completeError(StateError('old workspace failure'));
        } else {
          old.complete(null);
        }
        expect(await pendingOld, isNull);
        expect(repo.candidateBusy, isTrue);
        expect(repo.draftError, isNull);
        expect(repo.candidate, isNull);
        current.complete(null);
        expect(await pendingCurrent, isNotNull);
        expect(repo.candidateBusy, isFalse);
        expect(repo.canSave, isTrue);
        repo.dispose();
      },
    );
  }

  test('stale error cannot replace a newer accepted candidate', () async {
    final gate = _Gate();
    final repo = await opened(gate);
    final held = Completer<Object?>();
    gate.heldCandidate = held;
    final pending = repo.requestCandidate();
    final current = await repo.requestCandidate();
    held.completeError(
      WorkerRequestException(
        const ErrorBody(code: 'invalid', message: 'old rejection'),
      ),
    );
    expect(await pending, isNull);
    expect(repo.candidate, same(current));
    expect(repo.draftError, isNull);
    expect(repo.candidateProblems, isEmpty);
    expect(repo.canSave, isTrue);
    repo.dispose();
  });

  test(
    'workspace hook runs after reset and before any load, including empty roots',
    () async {
      final gate = _Gate();
      final repo = await opened(gate);
      final queries = gate.methods.length;
      final release = Completer<void>();
      final switching = repo.switchWorkspace(
        'D:/game/B',
        beforeLoad: () async {
          expect(repo.workspaceRoot, 'D:/game/B');
          expect(repo.resources, isEmpty);
          expect(repo.commands, isEmpty);
          expect(gate.methods, hasLength(queries));
          await release.future;
        },
      );
      await pump();
      expect(gate.methods, hasLength(queries));
      release.complete();
      expect(await switching, isTrue);
      var emptied = false;
      final afterB = gate.methods.length;
      expect(
        await repo.switchWorkspace('', beforeLoad: () async => emptied = true),
        isTrue,
      );
      expect(emptied, isTrue);
      expect(gate.methods, hasLength(afterB));
      repo.dispose();
    },
  );

  test(
    'workspace hook failure retains empty destination and sends no old worker reads',
    () async {
      final gate = _Gate();
      final repo = await opened(gate);
      final queries = gate.methods.length;
      expect(
        await repo.switchWorkspace(
          'D:/game/B',
          beforeLoad: () async {
            throw StateError('startup failed');
          },
        ),
        isTrue,
      );
      expect(repo.workspaceRoot, 'D:/game/B');
      expect(repo.resources, isEmpty);
      expect(repo.loadError, contains('startup failed'));
      expect(gate.methods, hasLength(queries));
      repo.dispose();
    },
  );

  test('保存进行中冻结编辑：任何编辑入口都不改草稿并给出可见原因', () async {
    final gate = _Gate()..heldSave = Completer<Object?>();
    final repo = await opened(gate);
    final candidate = await repo.requestCandidate();
    expect(candidate, isNotNull);
    expect(repo.canSave, isTrue);

    final saving = repo.saveDraft();
    await pump();
    expect(repo.editingFrozen, isTrue);
    expect(repo.busy, isTrue);
    expect(await repo.switchWorkspace('D:/game/B'), isFalse);
    expect(repo.workspaceRoot, root);

    repo.createTable('Boss');
    repo.renameField('table:Item', 'Id', 'Nope');
    repo.undoDraft();
    repo.discardDraft();
    expect(repo.draftCount, 1, reason: '冻结期间的编辑必须被拒');
    expect(repo.cursor, 1, reason: '撤销也不能动游标');
    expect(repo.draftError, contains('冻结'));

    gate.heldSave!.complete(null);
    expect(await saving, isNotNull);
    expect(repo.editingFrozen, isFalse);
    repo.createTable('Later');
    expect(repo.draftCount, 1, reason: '提交结束后草稿已清空，可继续编辑');
    repo.dispose();
  });

  test('不能重复提交：保存进行中的第二次保存直接返回 null', () async {
    final gate = _Gate()..heldSave = Completer<Object?>();
    final repo = await opened(gate);
    await repo.requestCandidate();

    final first = repo.saveDraft();
    await pump();
    expect(await repo.saveDraft(), isNull, reason: '第二次提交不得再发请求');
    expect(gate.saves, 0);

    gate.heldSave!.complete(null);
    expect(await first, isNotNull);
    expect(gate.saves, 1);
    expect(gate.methods.where((m) => m == Methods.schemaSave), hasLength(1));
    repo.dispose();
  });

  test('保存成功后刷新失败：报状态暂不可用，不恢复草稿、不要求重存', () async {
    final gate = _Gate(failListAfterSave: true);
    final repo = await opened(gate);
    await repo.requestCandidate();

    final saved = await repo.saveDraft();
    expect(saved, isNotNull, reason: 'YAML 确实已提交');
    expect(repo.draftCount, 0, reason: '不得把已提交的草稿还回来');
    expect(repo.canSave, isFalse);
    expect(repo.saveError, isNull, reason: '不能把刷新失败报成保存失败');
    expect(repo.refreshError, contains('状态刷新失败'));
    expect(gate.saves, 1, reason: '不得要求用户重复保存');
    repo.dispose();
  });

  test(
    'flush waits in-flight YAML save before draft cleanup and exit',
    () async {
      final gate = _Gate()..heldSave = Completer<Object?>();
      final repo = await opened(gate);
      await repo.requestCandidate();
      final saving = repo.saveDraft();
      var settled = false;
      final flush = repo.flushDraft().then((value) {
        settled = true;
        return value;
      });
      await pump();
      expect(settled, isFalse);
      expect(repo.hasDraftHistory, isTrue);
      gate.heldSave!.complete(null);
      await saving;
      expect(await flush, isTrue);
      expect(repo.hasDraftHistory, isFalse);
      repo.dispose();
    },
  );

  test('净差异为零时禁用保存：空事务不该占用一次提交', () async {
    final gate = _Gate(netDiffChanged: false);
    final repo = await opened(gate);
    final candidate = await repo.requestCandidate();
    expect(candidate, isNotNull);
    expect(candidate!.netDiff.changed, isEmpty);
    expect(repo.canSave, isFalse);
    expect(await repo.saveDraft(), isNull);
    expect(gate.saves, 0);
    repo.dispose();
  });

  test('reload preserves baseline even when all commands are undone', () async {
    final gate = _Gate();
    final repo = await opened(gate);
    repo.undoDraft();
    expect(repo.hasDraft, isFalse);
    expect(repo.hasDraftHistory, isTrue);
    gate.baseline = 'external';
    expect(await repo.recover(), isNotNull);
    expect(repo.schemaBaseline, 'base-1');
    expect(repo.hasDraftConflict, isTrue);
    expect(repo.conflictingDraft!.cursor, 0);
    expect(repo.conflictingDraft!.commands, hasLength(1));
    repo.redoDraft();
    expect(repo.cursor, 0);
    expect(repo.draftError, contains('基线已变'));
    repo.dispose();
  });

  test('守卫失配被拒：保留原始基线并明确冲突，不能重算后覆盖外部修改', () async {
    final gate = _Gate();
    final repo = await opened(gate);
    await repo.requestCandidate();
    gate.baseline = 'base-external'; // 模拟外部改 YAML 后内核的失配拒绝
    expect(await repo.saveDraft(), isNull);
    expect(repo.draftCount, 1, reason: '被拒的保存必须留草稿');
    expect(repo.saveError, contains('基线已变'));
    expect(repo.canSave, isFalse, reason: '旧 hash 不许复用，必须重算候选');
    expect(repo.candidate, isNull);
    expect(repo.schemaBaseline, 'base-1', reason: '旧草稿不得自动换基线');
    expect(repo.hasDraftConflict, isTrue);
    expect(repo.conflictingDraft!.baseline, 'base-1');
    expect(await repo.requestCandidate(), isNull);
    expect(await repo.saveDraft(), isNull);
    expect(repo.draftPersisted, isTrue);
    expect(await repo.discardDraftAndPersist(), isTrue);
    expect(repo.schemaBaseline, 'base-external');
    expect(repo.editingFrozen, isFalse);
    repo.dispose();
  });
}

Future<void> pump() => Future<void>.delayed(Duration.zero);
