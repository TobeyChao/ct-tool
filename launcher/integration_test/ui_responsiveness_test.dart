import 'dart:io';

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 任务 5.2：profile / release 模式下测「大字段表 + 分页预览 + 持续日志」的帧时间。
///
/// 跑法（需要真实内核与真实窗口，因此不放普通 test/ 里）：
///   cd native && cargo build -p ct-cli --release
///   cd launcher && CT_WORKER_BIN=/absolute/path/to/release/ct flutter drive \
///     --driver=test_driver/integration_test.dart \
///     --target=integration_test/ui_responsiveness_test.dart -d macos --profile
/// 结论落 `test/evidence/responsiveness-<模式>-<平台>.md`（含每阶段帧数、p50/p95/max）。
void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  binding.framePolicy = LiveTestWidgetsFlutterBindingFramePolicy.fullyLive;

  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      const String.fromEnvironment('CT_WORKER_BIN');
  final available = binary.isNotEmpty && File(binary).existsSync();

  late Directory ws;
  late WorkerService worker;
  late WorkbenchRepository repo;
  late ExportRunner runner;
  late TranslationRepository translations;
  late DesktopStateRepository desktop;
  final frames = <FrameTiming>[];

  void collect(List<FrameTiming> timings) => frames.addAll(timings);

  setUpAll(() async {
    if (!available) return;
    ws = await Directory.systemTemp.createTemp('ct-perf-');
    final source = Directory('../native/target/bench/bench-m');
    if (!source.existsSync()) {
      throw StateError(
        '缺少 M 档夹具：cargo run -p ct-xtask -- bench-fixtures --sizes m',
      );
    }
    await for (final entity in source.list(recursive: true)) {
      final relative = entity.path.substring(source.path.length + 1);
      if (relative.startsWith('output') || relative.startsWith('.ct')) continue;
      final target = '${ws.path}/$relative';
      if (entity is Directory) {
        await Directory(target).create(recursive: true);
      } else if (entity is File) {
        await Directory(File(target).parent.path).create(recursive: true);
        await entity.copy(target);
      }
    }
    final transport = await StdioWorkerTransport.start(
      executable: File(binary).absolute.path,
      workingDirectory: ws.path,
    );
    worker = WorkerService(
      settings: SettingsStore()
        ..workspacePath = ws.path
        ..runtimePath = File(binary).absolute.path,
      connect: () async => transport,
    );
    // 必须显式传 root：drive 跑时 SharedPreferences.setMockInitialValues 是空操作，
    // SettingsStore 会退到 _inferDefaults() 猜中的**真实 gd/**，那等于让 worker 打开真实工作区。
    await worker.start(workspaceRoot: ws.path);
    repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(ws.path);
    runner = ExportRunner(worker: worker, workspaceRoot: ws.path);
    translations = TranslationRepository(worker: worker);
    await translations.bind(ws.path);
    desktop = DesktopStateRepository(worker: worker);
    await desktop.bind(ws.path);
  });

  tearDownAll(() async {
    if (!available) return;
    await worker.stop();
    repo.dispose();
    runner.dispose();
    translations.dispose();
    desktop.dispose();
    try {
      ws.deleteSync(recursive: true);
    } on FileSystemException {
      // 交给系统临时目录回收
    }
  });

  testWidgets('大字段表 / 分页预览 / 持续日志的帧时间', (tester) async {
    // drive 环境下这行不生效，因此下面所有仓库对象都显式带 ws.path，绝不依赖偏好推断。
    SharedPreferences.setMockInitialValues({'workspace_path': ws.path});
    final settings = SettingsStore();
    await settings.load();
    WidgetsBinding.instance.addTimingsCallback(collect);

    debugPrint('profile: mount workbench');
    await tester.pumpWidget(
      MaterialApp(
        theme: buildCtTheme(),
        home: WorkbenchScreen(
          data: repo,
          refresh: repo,
          draft: repo,
          runner: runner,
          translations: translations,
          desktop: desktop,
          settings: settings,
          workspaceKey: 'perf',
          bannerLabel: 'profile 帧时间测量',
        ),
      ),
    );
    debugPrint('profile: widget pumped');
    await tester.pump(const Duration(milliseconds: 300));
    debugPrint('profile: mounted');

    final tables = repo.resources
        .where((r) => r.name != 'Item')
        .map((r) => r.name)
        .toList();
    expect(tables, isNotEmpty, reason: 'M 档夹具应有 50 张表');
    final target = tables.first;

    final phases = <String, FrameStats>{};
    Future<void> phase(String name, Future<void> Function() body) async {
      debugPrint('profile: start $name');
      frames.clear();
      await body();
      debugPrint('profile: actions done $name');
      await tester.pump(const Duration(milliseconds: 300));
      phases[name] = FrameStats.of(frames);
    }

    // 阶段一：大字段表——选表、滚动字段表与清单
    await phase('大字段表', () async {
      await tester.tap(find.text(target).first);
      await tester.pumpAndSettle();
      for (var i = 0; i < 6; i++) {
        final list = find.byType(ListView);
        if (list.evaluate().isNotEmpty) {
          await tester.drag(list.first, const Offset(0, -260));
        }
        await tester.pump();
      }
    });

    // 阶段二：分页预览——每点一次都要过内核游标 + 解码 + 追加重建
    await phase('分页预览', () async {
      await tester.tap(find.byKey(const ValueKey('wb.openPreview')));
      await tester.pumpAndSettle();
      for (var i = 0; i < 5; i++) {
        final more = find.byKey(const ValueKey('wb.previewMore'));
        if (more.evaluate().isEmpty) break;
        await tester.tap(more);
        await tester.pumpAndSettle();
      }
    });

    // 阶段三：持续日志——反复拉 logs.list 并在日志列表里滚动
    await phase('持续日志', () async {
      await tester.tap(find.byKey(const ValueKey('wb.navTap.日志')));
      await tester.pumpAndSettle();
      for (var i = 0; i < 8; i++) {
        await tester.runAsync(() => desktop.refresh());
        await tester.pump();
        // 历史页的可滚动区取决于当前页签：有就滚，没有就只测刷新重建。
        final scrollable = find.byType(Scrollable);
        if (scrollable.evaluate().isNotEmpty) {
          await tester.drag(scrollable.last, const Offset(0, -200));
        }
        await tester.pump();
      }
    });

    WidgetsBinding.instance.removeTimingsCallback(collect);

    final mode = kProfileMode
        ? 'profile'
        : kReleaseMode
        ? 'release'
        : 'debug';
    final lines = <String>[
      '# 桌面 UI 帧时间（任务 5.2，$mode 模式，${Platform.operatingSystem}）',
      '',
      '- 夹具：M 档（50 表 × 2000 行 × 20 列），真实 `ct worker`（`$binary`）',
      '- 口径：`WidgetsBinding.addTimingsCallback` 采到的逐帧 build/raster 时长',
      '- 预览行数：${repo.previewOf(target)?.rows.length ?? 0}',
      '- 60Hz 参考：`totalSpan` p95 应 <16.7ms；下表 p95/max 单位均为毫秒',
      '',
      '| 阶段 | 帧数 | build p50/p95/max (ms) | raster p50/p95/max (ms) | totalSpan p50/p95/max (ms) |',
      '|---|---|---|---|---|',
      for (final e in phases.entries)
        '| ${e.key} | ${e.value.count} | ${e.value.buildLine} | ${e.value.rasterLine} | ${e.value.spanLine} |',
      '',
    ];
    final out = File(
      'test/evidence/responsiveness-$mode-${Platform.operatingSystem}.md',
    );
    out.parent.createSync(recursive: true);
    out.writeAsStringSync(lines.join('\n'));

    for (final entry in phases.entries) {
      final s = entry.value;
      expect(s.count, greaterThan(10), reason: '${entry.key} 帧样本太少，测不准');
      expect(
        s.p95Build,
        lessThan(8.0),
        reason: '${entry.key} build p95=${s.p95Build}ms：一帧的构建不该吃掉半个 60Hz 预算',
      );
      expect(
        s.maxBuild,
        lessThan(34),
        reason: '${entry.key} 最差构建帧 ${s.maxBuild}ms：长尾也要修，不能只看 p95',
      );
      expect(
        s.p95Raster,
        lessThan(33.4),
        reason:
            '${entry.key} raster p95=${s.p95Raster}ms 超 2 帧预算，'
            '说明有业务工作在阻塞 UI（详见 ${out.path}）',
      );
      expect(
        s.maxRaster,
        lessThan(100),
        reason: '${entry.key} 最差帧 ${s.maxRaster}ms：单帧长尾也要修',
      );
    }
  }, skip: !available);
}

/// 一组帧时长的分位统计（毫秒）。
class FrameStats {
  FrameStats._(
    this.count,
    this.p50Build,
    this.p95Build,
    this.maxBuild,
    this.p50Raster,
    this.p95Raster,
    this.maxRaster,
    this.p50Span,
    this.p95Span,
    this.maxSpan,
  );

  final int count;
  final double p50Build;
  final double p95Build;
  final double maxBuild;
  final double p50Raster;
  final double p95Raster;
  final double maxRaster;
  final double p50Span;
  final double p95Span;
  final double maxSpan;

  static double _pct(List<double> sorted, double p) {
    if (sorted.isEmpty) return 0;
    final index = ((sorted.length - 1) * p).round();
    return sorted[index];
  }

  factory FrameStats.of(List<FrameTiming> timings) {
    final build =
        timings.map((t) => t.buildDuration.inMicroseconds / 1000).toList()
          ..sort();
    final raster =
        timings.map((t) => t.rasterDuration.inMicroseconds / 1000).toList()
          ..sort();
    final span = timings.map((t) => t.totalSpan.inMicroseconds / 1000).toList()
      ..sort();
    return FrameStats._(
      timings.length,
      _pct(build, 0.5),
      _pct(build, 0.95),
      build.isEmpty ? 0 : build.last,
      _pct(raster, 0.5),
      _pct(raster, 0.95),
      raster.isEmpty ? 0 : raster.last,
      _pct(span, 0.5),
      _pct(span, 0.95),
      span.isEmpty ? 0 : span.last,
    );
  }

  String get buildLine => '$p50Build / $p95Build / $maxBuild';
  String get rasterLine => '$p50Raster / $p95Raster / $maxRaster';
  String get spanLine => '$p50Span / $p95Span / $maxSpan';
}
