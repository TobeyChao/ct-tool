import 'package:ct_launcher/services/protocol/protocol.dart';
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
}) async {
  tester.view.physicalSize = const Size(1400, 900);
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
        onWorkspaceChanged: (_) {},
        onRuntimeChanged: (_) {},
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<SettingsStore> loadStore(Map<String, Object> seed) async {
    SharedPreferences.setMockInitialValues(seed);
    final settings = SettingsStore();
    await settings.load();
    return settings;
  }

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
    expect(
      find.textContaining('运行时来源：应用包内置'),
      findsOneWidget,
      reason: '设置页必须能看到实际使用的原生运行时来源',
    );
    // 废弃项：不再出现端口/工具目录/Python 输入
    expect(find.text('端口'), findsNothing);
    expect(find.text('工具目录'), findsNothing);
    expect(find.textContaining('.venv'), findsNothing);
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
    expect(find.textContaining('已废弃并被清除'), findsOneWidget);
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
    await tester.tap(find.byKey(const ValueKey('wb.exit')));
    await tester.pumpAndSettle();
    expect(exits, 1, reason: '面板不自己退出，只把意图交给壳层的退出守卫');
    repo.dispose();
  });
}
