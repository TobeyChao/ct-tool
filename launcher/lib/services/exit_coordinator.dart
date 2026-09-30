import 'dart:async';

import 'exit_guard.dart';

/// One exit attempt shared by window, settings, tray and platform lifecycle.
///
/// The caller adapts the result to window destruction or AppExitResponse. Draft
/// editing stays frozen after success until the process closes.
class ExitCoordinator {
  ExitCoordinator({
    required this.freezeEditing,
    required this.unfreezeEditing,
    required this.decide,
    required this.flushDraft,
    required this.retryDraft,
    required this.discardDraft,
    required this.onPersistenceFailure,
    required this.stopWorker,
  });

  final void Function() freezeEditing;
  final void Function() unfreezeEditing;
  final Future<ExitDecision> Function() decide;
  final Future<bool> Function() flushDraft;
  final Future<void> Function() retryDraft;
  final Future<bool> Function() discardDraft;
  final Future<ExitPersistenceDecision> Function() onPersistenceFailure;
  final Future<void> Function() stopWorker;

  Future<ExitDecision>? _attempt;

  bool get pending => _attempt != null;

  Future<ExitDecision> request() {
    final pending = _attempt;
    if (pending != null) return pending;
    final result = Completer<ExitDecision>();
    _attempt = result.future;
    unawaited(_run(result));
    return result.future;
  }

  Future<void> _run(Completer<ExitDecision> result) async {
    var frozen = false;
    var exiting = false;
    try {
      freezeEditing();
      frozen = true;
      final decision = await decide();
      if (decision != ExitDecision.exitNow) {
        result.complete(decision);
        return;
      }

      // No command-count shortcut: redo history and pending clears also matter.
      var persisted = await _succeeded(flushDraft);
      var discarding = false;
      while (!persisted) {
        switch (await onPersistenceFailure()) {
          case ExitPersistenceDecision.stay:
            result.complete(ExitDecision.stay);
            return;
          case ExitPersistenceDecision.retry:
            if (discarding) {
              persisted = await _succeeded(discardDraft);
            } else {
              persisted = await _succeeded(() async {
                await retryDraft();
                return flushDraft();
              });
            }
          case ExitPersistenceDecision.discard:
            discarding = true;
            persisted = await _succeeded(discardDraft);
        }
        if (persisted && discarding) {
          persisted = await _succeeded(flushDraft);
        }
      }
      await stopWorker();
      exiting = true;
      result.complete(ExitDecision.exitNow);
    } catch (error, stack) {
      result.completeError(error, stack);
    } finally {
      if (!exiting) {
        _attempt = null;
        if (frozen) unfreezeEditing();
      }
    }
  }

  // A throwing persistence operation is a failure, never permission to exit.
  Future<bool> _succeeded(Future<bool> Function() operation) async {
    try {
      return await operation();
    } catch (_) {
      return false;
    }
  }
}
