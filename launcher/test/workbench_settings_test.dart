import 'dart:async';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:ct_launcher/ui/workbench/workbench_settings.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:ct_launcher/theme.dart';
import 'package:ct_launcher/ui/workbench/workbench_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 工作台设置模块（native-flutter-workbench 任务 2.4）。
class _FakeGateway implements KernelGateway {
  _FakeGateway();

  @override
  WorkerStatus status = WorkerStatus.ready;
  @override
  String? failureReason;
  @override
  String? lastWorkspaceId = 'ws-live';

  @override
  Future<Object?> query(
    String method, {
    Map<String, Object?> params = const {},
    String? workspaceRoot,
  }) async {
    calls.add(method);
    return switch (method) {
      Methods.workspaceOpen => {
        'revision': 7,
        'status': 'ready',
        'recovery': {'needed': false, 'journals': <String>[]},
        'tables': 1,
        'records': 0,
        'enums': 0,
      },
      Methods.resourcesList => {
        'revision': 7,
        'resources': [
          {
            'name': 'Item',
            'kind': 'table',
            'sourcePath': 'config/schemas/item.yaml',
          },
        ],
      },
      _ => throw StateError('未预期方法 $method'),
    };
  }

  final List<String> calls = [];
}

Future<void> _pumpLive(
  WidgetTester tester, {
  required SettingsStore settings,
  required WorkbenchRepository repo,
  required _FakeGateway gateway,
  required VoidCallback onReload,
  VoidCallback? onExit,
  Size size = const Size(1400, 900),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: buildCtTheme(),
      home: WorkbenchScreen(
        data: repo,
        refresh: repo,
        settings: settings,
        kernelSummary: const [
          '内核状态：已连接（core 0.0.0）',
          '运行时来源：应用包内置 C:\\Apps\\runtime\\ct.exe',
        ],
        onWorkspaceChanged: (_) async {},
        onRuntimeChanged: (_) async {},
        onReloadWorkspace: onReload,
        onExitRequested: onExit,
        workspaceKey: 'settings-test',
        bannerLabel: '已连接原生内核',
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
}

Future<void> _scrollSettingsTo(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<SettingsStore> loadStore(Map<String, Object> seed) async {
    SharedPreferences.setMockInitialValues(seed);
    final settings = SettingsStore();
    await settings.load();
    return settings;
  }

  testWidgets('自动推断等待shell决定，不提前清除运行时偏好', (tester) async {
    final settings = await loadStore({'runtime_path': '/tmp/ct-explicit'});
    final initialRuntime = settings.runtimePath;
    final completed = Completer<void>();
    var calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: WorkbenchSettingsPanel(
            settings: settings,
            workspacePath: '',
            onUseInferredRuntime: () {
              calls++;
              return completed.future;
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.byKey(const ValueKey('settings.inferredRuntime'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pump();
    expect(calls, 1);
    expect(settings.runtimePath, initialRuntime);
    expect(
      (await SharedPreferences.getInstance()).getString('runtime_path'),
      '/tmp/ct-explicit',
    );
    // The shell may stay after a failed flush without applying any preference.
    completed.complete();
    await tester.pumpAndSettle();
    expect(settings.runtimePath, initialRuntime);
    expect(
      (await SharedPreferences.getInstance()).getString('runtime_path'),
      '/tmp/ct-explicit',
    );
    expect(find.text('已改用指定运行时并重连内核'), findsNothing);
  });

  testWidgets('设置模块显示内核来源与工作区，且不再出现端口/Python 配置', (tester) async {
    final settings = await loadStore({
      'workspace_path': 'D:/game/gd',
      'tool_dir': 'E:/repo/ct',
      'port': 8123,
    });
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');

    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () {},
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('wb.settingsPanel')), findsOneWidget);
    expect(
      find.byKey(const ValueKey('settings.workspacePath')),
      findsOneWidget,
    );
    expect(find.textContaining('D:/game/gd'), findsWidgets);

    final card = tester.getRect(
      find.byKey(const ValueKey('settings.workspaceCard')),
    );
    final pick = tester.getRect(
      find.byKey(const ValueKey('settings.pickWorkspace')),
    );
    final reload = tester.getRect(
      find.byKey(const ValueKey('settings.reloadWorkspace')),
    );
    expect(pick.right, lessThan(reload.left));
    expect(card.right - reload.right, moreOrLessEquals(16, epsilon: 1));

    await _scrollSettingsTo(
      tester,
      find.byKey(const ValueKey('settings.inferredRuntime')),
    );
    final runtimeCard = tester.getRect(
      find.byKey(const ValueKey('settings.runtimeCard')),
    );
    final inferredRuntime = tester.getRect(
      find.byKey(const ValueKey('settings.inferredRuntime')),
    );
    expect(
      runtimeCard.right - inferredRuntime.right,
      moreOrLessEquals(16, epsilon: 1),
    );

    await _scrollSettingsTo(
      tester,
      find.byKey(const ValueKey('settings.trayResident')),
    );
    final desktopCard = tester.getRect(
      find.byKey(const ValueKey('settings.desktopCard')),
    );
    final trayResident = tester.getRect(
      find.byKey(const ValueKey('settings.trayResident')),
    );
    expect(
      desktopCard.right - trayResident.right,
      moreOrLessEquals(16, epsilon: 1),
    );

    await _scrollSettingsTo(
      tester,
      find.byKey(const ValueKey('settings.about')),
    );
    final helpCard = tester.getRect(
      find.byKey(const ValueKey('settings.helpCard')),
    );
    final about = tester.getRect(find.byKey(const ValueKey('settings.about')));
    expect(helpCard.right - about.right, moreOrLessEquals(16, epsilon: 1));

    expect(
      find.textContaining('运行时来源：应用包内置'),
      findsOneWidget,
      reason: '设置页必须能看到实际使用的原生运行时来源',
    );
    // 废弃项：不再出现端口/工具目录/Python 输入
    expect(find.text('端口'), findsNothing);
    expect(find.text('工具目录'), findsNothing);
    expect(find.textContaining('.venv'), findsNothing);
    expect(find.byKey(const ValueKey('settings.docs')), findsOneWidget);
    expect(find.byKey(const ValueKey('settings.help')), findsOneWidget);
    expect(find.byKey(const ValueKey('settings.about')), findsOneWidget);
    repo.dispose();
  });

  testWidgets('检测到旧配置时给一次性迁移说明', (tester) async {
    final settings = await loadStore({'tool_dir': 'E:/repo/ct', 'port': 8123});
    expect(settings.migratedFromLegacy, isTrue);
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () {},
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('settings.legacyNote')), findsOneWidget);
    expect(find.textContaining('配置不再使用'), findsOneWidget);
    repo.dispose();
  });

  testWidgets('托盘常驻开关即时写回偏好，重启后仍保留', (tester) async {
    final settings = await loadStore({});
    expect(settings.trayResident, isFalse);
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () {},
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await _scrollSettingsTo(
      tester,
      find.byKey(const ValueKey('settings.trayResident')),
    );
    await tester.tap(find.byKey(const ValueKey('settings.trayResident')));
    await tester.pumpAndSettle();

    expect(settings.trayResident, isTrue);
    // 模拟重启
    final second = SettingsStore();
    await second.load();
    expect(second.trayResident, isTrue);
    repo.dispose();
  });

  testWidgets('重新读取按钮真的再走一次内核只读请求', (tester) async {
    final settings = await loadStore({});
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
    gateway.calls.clear();
    var reloads = 0;
    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () => reloads++,
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('settings.reloadWorkspace')));
    await tester.pumpAndSettle();
    expect(reloads, 1);
    repo.dispose();
  });

  testWidgets('设置里的「退出应用」只转达意图，由壳层走退出守卫', (tester) async {
    final settings = await loadStore({});
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
    var exits = 0;
    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () {},
      onExit: () => exits++,
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('wb.exit')), findsOneWidget);
    await _scrollSettingsTo(tester, find.byKey(const ValueKey('wb.exit')));
    await tester.tap(find.byKey(const ValueKey('wb.exit')));
    await tester.pumpAndSettle();
    expect(exits, 1, reason: '面板不自己退出，只把意图交给壳层的退出守卫');
    repo.dispose();
  });

  testWidgets('设置纵向堆叠在最小窗口下无溢出', (tester) async {
    final settings = await loadStore({});
    final gateway = _FakeGateway();
    final repo = WorkbenchRepository(worker: gateway);
    await repo.switchWorkspace('D:/game/gd');
    await _pumpLive(
      tester,
      settings: settings,
      repo: repo,
      gateway: gateway,
      onReload: () {},
      size: const Size(1024, 700),
    );
    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('settings.nav.workspace')),
      findsNothing,
      reason: '内容较少时不额外增加设置分类导航',
    );
    expect(
      find.byKey(const ValueKey('settings.workspaceCard')),
      findsOneWidget,
    );
    expect(find.byKey(const ValueKey('settings.trayResident')), findsOneWidget);
    expect(find.byKey(const ValueKey('settings.about')), findsOneWidget);
    await _scrollSettingsTo(tester, find.byKey(const ValueKey('wb.exit')));
    expect(tester.takeException(), isNull);
    repo.dispose();
  });
}
