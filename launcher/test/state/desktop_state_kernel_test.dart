import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:flutter_test/flutter_test.dart';

/// 桌面状态三张表直连真实 `ct worker`（任务 4.5/4.8）：导出后日志/历史/任务确实有内容，
/// 筛选可用、问题可分页、关闭通知后重连不复活。
void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  const skipReason = '未构建原生 ct 二进制（先 cargo build -p ct-cli）';

  Future<({Directory ws, WorkerService worker, DesktopStateRepository state})>
  open({Directory? reuse}) async {
    // reuse 用于「同一工作区、重新连接」的场景：历史是工作区账本，不能换目录。
    final ws = reuse ?? await Directory.systemTemp.createTemp('ct-desktop-');
    if (reuse == null) {
      final source = Directory('../native/fixtures/export_pipeline/workspace');
      await for (final entity in source.list(recursive: true)) {
        final relative = entity.path.substring(source.path.length + 1);
        final target = '${ws.path}/$relative';
        if (entity is Directory) {
          await Directory(target).create(recursive: true);
        } else if (entity is File) {
          await Directory(File(target).parent.path).create(recursive: true);
          await entity.copy(target);
        }
      }
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
    final state = DesktopStateRepository(worker: worker);
    // 与 app.dart 相同的接线：实时事件按工作区归属过滤后驱动刷新。
    worker.events.listen(state.onWorkerEvent);
    await state.bind(ws.path);
    return (ws: ws, worker: worker, state: state);
  }

  Future<void> close(
    ({Directory ws, WorkerService worker, DesktopStateRepository state}) ctx, {
    bool keepWorkspace = false,
  }) async {
    await ctx.worker.stop();
    ctx.state.dispose();
    if (keepWorkspace) return;
    try {
      await ctx.ws.delete(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  }

  test(
    '导出后日志/历史/任务三张表都有真实内容，筛选与问题分页可用',
    () async {
      if (!available) return;
      final ctx = await open();
      await ctx.worker.request(Methods.export, workspaceRoot: ctx.ws.path);
      // 等事件驱动的刷新落地
      for (var i = 0; i < 40 && ctx.worker.lastWorkspaceId == null; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      await ctx.state.refresh();

      expect(
        ctx.state.tasks.map((task) => task.method).toList(),
        contains(Methods.export),
        reason: 'tasks.list 必须记录这次导出',
      );
      final task = ctx.state.tasks.firstWhere(
        (t) => t.method == Methods.export,
      );
      expect(task.status, TaskStatus.success);
      expect(task.dismissed, isFalse);

      expect(ctx.state.history, isNotEmpty, reason: '桌面导出应写最近 5 条历史');
      final entry = ctx.state.history.first;
      expect(entry.result, 'success');
      expect(entry.tables, greaterThanOrEqualTo(1));
      expect(entry.scope, isNotEmpty);

      expect(ctx.state.logs, isNotEmpty, reason: '导出进度应进模块日志');
      expect(
        ctx.state.logs.any((log) => log.module == 'export'),
        isTrue,
        reason: '${ctx.state.logs.map((l) => l.module).toList()}',
      );
      await ctx.state.setLogFilter(module: 'export');
      expect(
        ctx.state.logs.every((log) => log.module == 'export'),
        isTrue,
        reason: '模块筛选必须由内核执行',
      );

      // 成功导出的问题列表应为空页，但分页契约仍回传代次
      await ctx.state.loadIssues(task.id);
      final page = ctx.state.issuesOf(task.id);
      expect(page, isNotNull);
      expect(page!.issues, isEmpty);
      expect(page.revision, greaterThan(0));

      await ctx.state.dismiss(task.id);
      expect(
        ctx.state.tasks.firstWhere((t) => t.id == task.id).dismissed,
        isTrue,
        reason: '关闭通知后必须记住状态',
      );
      await close(ctx);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 3)),
  );

  test(
    '重连后已关闭的通知不复活',
    () async {
      if (!available) return;
      final ctx = await open();
      await ctx.worker.request(Methods.export, workspaceRoot: ctx.ws.path);
      await ctx.state.refresh();
      final task = ctx.state.tasks.firstWhere(
        (t) => t.method == Methods.export,
      );
      await ctx.state.dismiss(task.id);
      await close(ctx, keepWorkspace: true);

      // 全新连接（新 session）+ 同一工作区：要么没有该任务，要么不再是未关闭状态
      final again = await open(reuse: ctx.ws);
      expect(
        again.state.tasks.any((t) => t.id == task.id && !t.dismissed),
        isFalse,
        reason: '已关闭的通知不得复活',
      );
      // 历史跨连接保留（内核账本，不是会话内存）
      expect(
        again.state.history.any((e) => e.result == 'success'),
        isTrue,
        reason: '导出历史必须跨重启保留',
      );
      expect(again.state.history.length, lessThanOrEqualTo(5));
      await close(again);
    },
    skip: available ? false : skipReason,
    timeout: const Timeout(Duration(minutes: 4)),
  );
}
