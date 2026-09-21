import 'dart:io';
import 'dart:ui' as ui;

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/protocol/protocol.dart'
    show DeployResult, ExportResult, TaskOutcome;
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/desktop_state.dart';
import 'package:ct_launcher/state/export_runner.dart';
import 'package:ct_launcher/state/template_service.dart';
import 'package:ct_launcher/state/translation_repository.dart';
import 'package:ct_launcher/state/validate_runner.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/widgets/common.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show RenderRepaintBoundary;
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 桌面全链截图证据（native-flutter-workbench 任务 5.4）：
/// 每一步都由**真实 `ct worker`** 驱动，界面只做渲染；截图落在 `test/evidence/`，
/// 同一步在页面上真正可见的文字（含中文）另存 `test/evidence/chain-text-log.md`，
/// 因为 flutter_tester 没有 CJK 字体，PNG 里的中文会是占位方块（与 1.4 矩阵同样的限制）。

/// 真实 worker 走的是 IO：动作与等待必须放在 `runAsync` 里，否则 fake-async 区域
/// 里的 future 永远不完成（上一版「导出成功」是假通过，这版用断言钉住）。
Future<void> act(
  WidgetTester tester,
  Future<void> Function() body, {
  bool Function()? done,
}) async {
  await tester.runAsync(() async {
    await body();
    for (var i = 0; i < 600; i++) {
      if (done == null || done()) break;
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }
  });
  await settle(tester, rounds: 20);
}

Future<void> settle(WidgetTester tester, {int rounds = 400}) async {
  for (var i = 0; i < rounds; i++) {
    await tester.pump(const Duration(milliseconds: 25));
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
  }
}

void main() {
  final binary =
      Platform.environment['CT_WORKER_BIN'] ??
      (Platform.isWindows
          ? '../native/target/debug/ct.exe'
          : '../native/target/debug/ct');
  final available = File(binary).existsSync();
  // 未构建二进制时整组用例 skip（testWidgets 的 skip 只收 bool，理由写在文件名与注释里）。

  late Directory ws;
  late Directory unity;
  late WorkerService worker;
  late WorkbenchRepository repo;
  late ExportRunner runner;
  late ValidateRunner validate;
  late TemplateService template;
  late TranslationRepository translations;
  late DesktopStateRepository desktop;
  final textLog = <String>[];

  Future<void> copyFixture() async {
    ws = await Directory.systemTemp.createTemp('ct-shots-');
    unity = await Directory.systemTemp.createTemp('ct-shots-unity-');
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
    // 打开部署目标：独立部署要真的把文件送进 Unity 工程目录。
    final cfg = File('${ws.path}/config/global.yaml');
    cfg.writeAsStringSync(
      '${cfg.readAsStringSync()}\n'
      'deploy:\n'
      '  enabled: true\n'
      '  unity_project: ${unity.path.replaceAll(Platform.pathSeparator, '/')}\n'
      '  targets:\n'
      '    - {source: output/binary, dest: Assets/Content/Config}\n'
      '    - {source: output/generated/csharp, dest: Assets/Scripts/Config/Gen}\n',
    );
  }

  /// 每一步同时记下**内核侧真实状态**，截图不是摆拍：候选/校验/导出部署/翻译各自说话。
  String kernelFacts() {
    final cand = repo.candidate;
    final summary = runner.last;
    return '草稿 ${repo.draftCount} 步'
        ' · 候选 ${cand == null ? '未计算' : '${cand.candidateHash.characters.take(8).join()}… '
                  '+${cand.netDiff.added.length}/~${cand.netDiff.changed.length}/-'
                  '${cand.netDiff.removed.length} 问题 ${cand.problems.length}'}'
        ' · 校验「${validate.summaryLabel}」'
        ' · 运行相位 ${runner.phase.name}'
        '${summary?.result == null ? '' : ' 导出表 ${summary!.result!.tables} 耗时 ${summary.result!.durationMs}ms 阶段 ${summary.result!.stages.length}'}'
        '${summary?.deploy == null ? '' : ' 部署同步 ${summary!.deploy!.synced} 个'}'
        ' · 翻译忙碌 ${translations.busy}'
        ' · 模板忙碌 ${template.busy}';
  }

  /// 截图直接落到 `test/evidence/`，不做像素比对：导出/部署面板里带真实耗时，
  /// 逐像素断言会把「数字变了」误报成界面坏了（5.4 要的是证据，不是 golden 回归）。
  Future<void> shot(WidgetTester tester, String name, String note) async {
    final boundary = tester.renderObject<RenderRepaintBoundary>(
      find.byKey(const ValueKey('shots-root')),
    );
    final bytes = await tester.runAsync(() async {
      final image = await boundary.toImage(pixelRatio: 1.0);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      image.dispose();
      return data!.buffer.asUint8List();
    });
    File('test/evidence/$name.png').writeAsBytesSync(bytes!);
    final visible = tester
        .widgetList<Text>(find.byType(Text))
        .map((t) => t.data ?? '')
        .where((t) => t.trim().isNotEmpty)
        .join(' | ');
    textLog.add(
      '## $name\n\n$note\n\n- 内核事实：${kernelFacts()}\n'
      '\n可见文字（全部）：\n\n```\n$visible\n```\n',
    );
  }

  setUpAll(() async {
    if (!available) return;
    await copyFixture();
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
    await worker.start();
    repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(ws.path);
    runner = ExportRunner(worker: worker, workspaceRoot: ws.path);
    validate = ValidateRunner(worker: worker, workspaceRoot: ws.path);
    template = TemplateService(worker: worker, workspaceRoot: ws.path);
    translations = TranslationRepository(worker: worker);
    await translations.bind(ws.path);
    desktop = DesktopStateRepository(worker: worker);
    await desktop.bind(ws.path);
  });

  tearDownAll(() async {
    if (!available) return;
    await worker.stop();
    File('test/evidence/chain-text-log.md').writeAsStringSync(
      '# 桌面全链截图的同源文字证据（任务 5.4）\n\n'
      'PNG 由 `test/e2e_workbench_chain_screens_test.dart` 在真实 ct worker 上生成；'
      '本文件记录每一步**界面上真实渲染的文本**（flutter_tester 无 CJK 字体，'
      '截图里中文显示为方块，故文字证据单独留档）。\n\n'
      '${textLog.join('\n')}',
    );
    for (final dir in [ws, unity]) {
      try {
        dir.deleteSync(recursive: true);
      } on FileSystemException {
        // 交给系统临时目录回收
      }
    }
  });

  testWidgets('创建 → 草稿步骤 → 净差异 → 模板 → 校验 → 导出 → 部署 → 翻译 → Quick Open', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({'workspace_path': ws.path});
    final settings = SettingsStore();
    await settings.load();
    tester.view.physicalSize = const Size(1500, 950);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      // 边界包住整个 MaterialApp：对话框/Quick Open 走根 Overlay，
      // 只包 home 会把弹窗截在外面（第一版就是这样，截图里没有对话框）。
      RepaintBoundary(
        key: const ValueKey('shots-root'),
        child: MaterialApp(
          theme: buildCtTheme(),
          home: WorkbenchScreen(
            data: repo,
            refresh: repo,
            draft: repo,
            runner: runner,
            validate: validate,
            translations: translations,
            template: template,
            desktop: desktop,
            settings: settings,
            onResourceSelected: (name) => repo.loadPreview(name),
            onExitRequested: () {},
            workspaceKey: 'shots',
            bannerLabel: '已连接原生内核（截图证据）',
          ),
        ),
      ),
    );
    await settle(tester);
    await shot(
      tester,
      'chain-01-schema',
      'Schema 模块：资源清单与只读预览都来自内核 resources.list / table.preview。',
    );

    // 草稿：加一张表，看草稿条与「步骤 / 净差异」弹层（游标、逐步撤销、资源级净差异）。
    repo.createTable('E2ETable');
    await settle(tester);
    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.draftSummaryTap'))),
    );
    await settle(tester, rounds: 60);
    await shot(
      tester,
      'chain-02-draft-steps',
      '未保存修改弹层「步骤」页：命令日志 + 游标 + 「停在此处」逐步撤销（内核只认前缀）。',
    );
    await act(
      tester,
      () => tester.tap(find.text('净差异')),
      done: () => repo.candidate != null || !repo.candidateBusy,
    );
    await settle(tester, rounds: 120);
    await shot(
      tester,
      'chain-03-netdiff',
      '同一弹层的「净差异」页：新增/修改/删除条目与阻塞问题计数，全部取自内核回包。',
    );
    await tester.tap(find.text('关闭'));
    await settle(tester, rounds: 60);

    // 模板：预检放行后才允许生成（生成会写 Excel）。
    await tester.tap(find.text('Item').first);
    await settle(tester, rounds: 60);
    if (find.byKey(const ValueKey('wb.templatePlan')).evaluate().isNotEmpty) {
      await act(
        tester,
        () => tester.tap(find.byKey(const ValueKey('wb.templatePlan'))),
        done: () => !template.busy,
      );
      await settle(tester, rounds: 60);
      await shot(
        tester,
        'chain-04-template-plan',
        '模板预检（template.plan）：迁移/新建计划与警告来自内核。',
      );
      final generateKey = const ValueKey('wb.templateGenerate');
      if (find.byKey(generateKey).evaluate().isNotEmpty &&
          tester.widget<CtButton>(find.byKey(generateKey)).onPressed != null) {
        await act(
          tester,
          () => tester.tap(find.byKey(generateKey)),
          done: () => !template.busy,
        );
        await settle(tester, rounds: 60);
        await shot(
          tester,
          'chain-05-template-generated',
          '模板生成后（template.generate）：状态由生成后的重查刷新。',
        );
      }
    }

    // 导出模块：先校验（只读闸门），再导出，再独立部署。
    await tester.tap(find.text('导出'));
    await settle(tester, rounds: 60);
    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.validateRun'))),
      done: () => !validate.busy,
    );
    await settle(tester, rounds: 60);
    await shot(
      tester,
      'chain-06-validate',
      '导出页的「校验」入口：结论与问题全部来自内核 validate（只读，不写盘）。',
    );

    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.exportRun'))),
      done: () => !runner.running,
    );
    ExportResult? exported;
    DeployResult? deployedResult;
    await tester.runAsync(() async => exported = runner.last?.result);
    expect(
      exported?.outcome,
      TaskOutcome.succeeded,
      reason: '导出终态以内核为准：${kernelFacts()}',
    );
    expect(
      (exported?.stages.length ?? 0) > 0,
      isTrue,
      reason: '阶段耗时来自 progress 事件',
    );
    await settle(tester, rounds: 60);
    await shot(
      tester,
      'chain-07-export',
      '导出完成：阶段/耗时/缓存统计与日志由 progress/log 事件汇成。',
    );

    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.deployRun'))),
      done: () => !runner.running,
    );
    await tester.runAsync(() async => deployedResult = runner.last?.deploy);
    expect(
      (deployedResult?.synced ?? 0) > 0,
      isTrue,
      reason: '独立部署要真的同步文件：${kernelFacts()}',
    );
    await settle(tester, rounds: 60);
    await shot(tester, 'chain-08-deploy', '独立部署：显式操作，真的把产物送进 Unity 工程目录。');

    // 翻译模块：sync 后看四态与分页。
    await tester.tap(find.text('翻译'));
    await settle(tester, rounds: 60);
    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.i18nSync'))),
      done: () => !translations.busy,
    );
    await settle(tester, rounds: 60);
    await shot(tester, 'chain-09-i18n', '翻译页：筛选/列显隐/分页与 sync 结果都来自内核 i18n.*。');

    // Quick Open：空查询给最近打开（跨模块可达）。
    await act(
      tester,
      () => tester.tap(find.byKey(const ValueKey('wb.draftQuickOpen'))),
    );
    await settle(tester, rounds: 60);
    await shot(tester, 'chain-10-quick-open', 'Quick Open：资源清单取自内核，空查询给最近打开。');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await settle(tester, rounds: 30);

    // 收尾断言：截图不是摆拍——内核状态确实变了。
    expect(repo.resources, isNotEmpty);
    expect(repo.candidate, isNotNull, reason: '净差异必须由内核算出');
    expect(validate.last?.ok, isTrue, reason: '校验结论来自内核：${validate.error}');
    expect(exported, isNotNull, reason: '导出结果快照必须留在 RunSummary 里');
    expect(deployedResult, isNotNull, reason: '独立部署必须留下同步计数');
    final deployed = Directory('${unity.path}/Assets/Content/Config');
    expect(deployed.existsSync(), isTrue, reason: '部署目标目录必须真的被写入');
    expect(
      deployed
          .listSync(recursive: true)
          .whereType<File>()
          .fold<int>(0, (n, _) => n + 1),
      greaterThan(0),
    );
    await tester.runAsync(() => desktop.refresh());
    await settle(tester, rounds: 20);
    expect(desktop.logs, isNotEmpty, reason: '内核日志要能进桌面日志列表（logs.list）');
    expect(
      desktop.logs.any((l) => l.module == 'export'),
      isTrue,
      reason: '导出确实产生过模块日志',
    );
  }, skip: !available);
}
