import 'dart:async';

import 'package:ct_launcher/services/exit_coordinator.dart';
import 'package:ct_launcher/services/exit_guard.dart';
import 'package:flutter_test/flutter_test.dart';

class ExitHarness {
  final events = <String>[];
  int freezeDepth = 0;
  Future<ExitDecision> Function() decide = () async => ExitDecision.exitNow;
  Future<bool> Function() flush = () async => true;
  Future<bool> Function() discard = () async => true;
  Future<ExitPersistenceDecision> Function() failure = () async =>
      ExitPersistenceDecision.stay;
  Future<void> Function() stop = () async {};

  late final coordinator = ExitCoordinator(
    freezeEditing: () {
      events.add('freeze');
      freezeDepth++;
    },
    unfreezeEditing: () {
      events.add('unfreeze');
      freezeDepth--;
    },
    decide: () {
      events.add('decide');
      expect(freezeDepth, greaterThan(0));
      return decide();
    },
    flushDraft: () {
      events.add('flush');
      expect(freezeDepth, greaterThan(0));
      return flush();
    },
    retryDraft: () async => events.add('retry'),
    discardDraft: () {
      events.add('discard');
      return discard();
    },
    onPersistenceFailure: () {
      events.add('failure');
      return failure();
    },
    stopWorker: () async {
      events.add('stop');
      await stop();
    },
  );
}

void main() {
  test(
    'window, settings, tray and lifecycle share one decision and flush',
    () async {
      final h = ExitHarness();
      final choice = Completer<ExitDecision>();
      final flushed = Completer<bool>();
      final flushStarted = Completer<void>();
      final workerStopped = Completer<void>();
      final stopStarted = Completer<void>();
      h.decide = () => choice.future;
      h.flush = () {
        flushStarted.complete();
        return flushed.future;
      };
      h.stop = () {
        stopStarted.complete();
        return workerStopped.future;
      };
      final window = h.coordinator.request();
      final lifecycle = h.coordinator.request();
      expect(identical(window, lifecycle), isTrue);
      expect(identical(window, h.coordinator.request()), isTrue);
      expect(identical(window, h.coordinator.request()), isTrue);
      expect(h.freezeDepth, 1);
      choice.complete(ExitDecision.exitNow);
      await flushStarted.future;
      expect(h.events, ['freeze', 'decide', 'flush']);
      flushed.complete(true);
      await stopStarted.future;
      expect(h.freezeDepth, 1);
      expect(h.events.last, 'stop');
      workerStopped.complete();
      expect(await window, ExitDecision.exitNow);
      expect(await lifecycle, ExitDecision.exitNow);
      expect(identical(window, h.coordinator.request()), isTrue);
      expect(
        h.freezeDepth,
        1,
        reason: 'frozen through platform/window closing',
      );
    },
  );

  test(
    'zero active commands still flush before worker and window close',
    () async {
      // The coordinator deliberately has no command-count predicate. This covers
      // redo-only history, pending clear and an empty draft with in-flight IO.
      final h = ExitHarness();
      final flushed = Completer<bool>();
      final flushStarted = Completer<void>();
      h.flush = () {
        flushStarted.complete();
        return flushed.future;
      };
      final close = () async {
        if (await h.coordinator.request() == ExitDecision.exitNow) {
          h.events.add('destroy');
        }
      }();
      await flushStarted.future;
      expect(h.events, ['freeze', 'decide', 'flush']);
      flushed.complete(true);
      await close;
      expect(h.events, ['freeze', 'decide', 'flush', 'stop', 'destroy']);
    },
  );

  for (final decision in [ExitDecision.stay, ExitDecision.hideToTray]) {
    test('$decision releases freeze without flushing or stopping', () async {
      final h = ExitHarness()..decide = () async => decision;
      expect(await h.coordinator.request(), decision);
      expect(h.events, ['freeze', 'decide', 'unfreeze']);
      expect(h.freezeDepth, 0);
      expect(h.coordinator.pending, isFalse);
      h.decide = () async => ExitDecision.exitNow;
      expect(await h.coordinator.request(), ExitDecision.exitNow);
      expect(h.events.where((e) => e == 'decide').length, 2);
    });
  }

  test(
    'failed flush leaves editing available and a later exit can retry',
    () async {
      final h = ExitHarness()..flush = () async => false;
      expect(await h.coordinator.request(), ExitDecision.stay);
      expect(h.events, ['freeze', 'decide', 'flush', 'failure', 'unfreeze']);
      expect(h.freezeDepth, 0);
      h.flush = () async => true;
      expect(await h.coordinator.request(), ExitDecision.exitNow);
      expect(h.events.where((e) => e == 'stop').length, 1);
    },
  );

  test('retry persists again and flushes before stopping', () async {
    final h = ExitHarness();
    var calls = 0;
    h.flush = () async => ++calls > 1;
    h.failure = () async => ExitPersistenceDecision.retry;
    expect(await h.coordinator.request(), ExitDecision.exitNow);
    expect(h.events, [
      'freeze',
      'decide',
      'flush',
      'failure',
      'retry',
      'flush',
      'stop',
    ]);
  });

  test('explicit discard must clear and flush before stopping', () async {
    final h = ExitHarness();
    var calls = 0;
    h.flush = () async => ++calls > 1;
    h.failure = () async => ExitPersistenceDecision.discard;
    expect(await h.coordinator.request(), ExitDecision.exitNow);
    expect(h.events, [
      'freeze',
      'decide',
      'flush',
      'failure',
      'discard',
      'flush',
      'stop',
    ]);
  });

  test('failed clear stays without stopping and releases freeze', () async {
    final h = ExitHarness();
    h.flush = () async => false;
    h.discard = () async => false;
    var choices = 0;
    h.failure = () async => ++choices == 1
        ? ExitPersistenceDecision.discard
        : ExitPersistenceDecision.stay;
    expect(await h.coordinator.request(), ExitDecision.stay);
    expect(h.events, [
      'freeze',
      'decide',
      'flush',
      'failure',
      'discard',
      'failure',
      'unfreeze',
    ]);
    expect(h.freezeDepth, 0);
  });

  test(
    'retry after failed discard retries clear, never resaves discarded data',
    () async {
      final h = ExitHarness();
      var flushes = 0;
      var clears = 0;
      var choices = 0;
      h.flush = () async => ++flushes > 1;
      h.discard = () async => ++clears > 1;
      h.failure = () async => ++choices == 1
          ? ExitPersistenceDecision.discard
          : ExitPersistenceDecision.retry;
      expect(await h.coordinator.request(), ExitDecision.exitNow);
      expect(h.events, [
        'freeze',
        'decide',
        'flush',
        'failure',
        'discard',
        'failure',
        'discard',
        'flush',
        'stop',
      ]);
    },
  );

  test(
    'persistence exception requires user choice and does not stop',
    () async {
      final h = ExitHarness()..flush = () async => throw StateError('disk');
      expect(await h.coordinator.request(), ExitDecision.stay);
      expect(h.events.contains('stop'), isFalse);
      expect(h.freezeDepth, 0);
    },
  );

  test('worker failure releases freeze and permits another attempt', () async {
    final h = ExitHarness()..stop = () async => throw StateError('worker');
    await expectLater(h.coordinator.request(), throwsStateError);
    expect(h.freezeDepth, 0);
    expect(h.coordinator.pending, isFalse);
    h.stop = () async {};
    expect(await h.coordinator.request(), ExitDecision.exitNow);
  });
}
