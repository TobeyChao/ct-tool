import 'dart:io';

import 'package:ct_launcher/services/native_runtime.dart';
import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/worker_service.dart';
import 'package:ct_launcher/state/workbench_repository.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 桌面偏好迁移与「实际启动参数」（native-flutter-workbench 任务 2.4）。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('新安装不自动绑定真实游戏工作区', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsStore();
    await settings.load();
    expect(settings.workspacePath, isEmpty);
  });

  test('main 原生路径迁移后重启与恢复自动推断不会复活旧键', () async {
    SharedPreferences.setMockInitialValues({
      'native_runtime_path': '/runtime/ct',
      'tool_dir': '/old/python/ct',
    });
    final settings = SettingsStore();
    await settings.load();
    expect(settings.runtimePath, '/runtime/ct');
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(SettingsStore.kRuntimePath), '/runtime/ct');
    expect(prefs.containsKey('native_runtime_path'), isFalse);
    expect(prefs.containsKey('tool_dir'), isFalse);

    final reloaded = SettingsStore();
    await reloaded.load();
    expect(reloaded.runtimePath, '/runtime/ct');
    await reloaded.useInferredRuntimePath();
    final reset = SettingsStore();
    await reset.load();
    expect(reset.runtimePath, reset.inferredRuntimePath);
  });

  test('工作台已保存的路径（含空值）优先于 main 旧原生路径', () async {
    for (final saved in ['/new/ct', '']) {
      SharedPreferences.setMockInitialValues({
        'runtime_path': saved,
        'native_runtime_path': '/old/ct',
      });
      final settings = SettingsStore();
      await settings.load();
      expect(settings.runtimePath, saved);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.containsKey('native_runtime_path'), isFalse);
    }
  });

  const legacy = {'tool_dir': 'E:/repo/ct', 'port': 8123, 'host': '127.0.0.1'};

  test('旧 Python/端口配置被清除，工作区与桌面偏好保留', () async {
    SharedPreferences.setMockInitialValues({
      'workspace_path': 'D:/game/gd',
      'tray_resident': true,
      'auto_start': true,
      ...legacy,
    });
    final settings = SettingsStore();
    await settings.load();

    expect(settings.workspacePath, 'D:/game/gd');
    expect(settings.trayResident, isTrue);
    expect(settings.autoStart, isTrue);
    expect(settings.migratedFromLegacy, isTrue);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey('tool_dir'), isFalse);
    expect(prefs.containsKey('port'), isFalse);
    expect(prefs.containsKey('host'), isFalse);
    expect(await SettingsStore.legacyKeysCleared(), isTrue);
  });

  test('重启后偏好保留，且不再回读旧键', () async {
    SharedPreferences.setMockInitialValues({...legacy});
    final first = SettingsStore();
    await first.load();
    await first.setWorkspacePath('D:/game/gd2');
    await first.setRuntimePath('D:/tools/ct.exe');
    await first.setTrayResident(true);

    // 模拟重启：新建实例重新 load（底层是同一份 mock 存储）。
    final second = SettingsStore();
    await second.load();
    expect(second.workspacePath, 'D:/game/gd2');
    expect(second.runtimePath, 'D:/tools/ct.exe');
    expect(second.trayResident, isTrue);
    expect(second.autoStart, isFalse);
  });

  test('未指定运行时时回落到自动推断，清空后同样回落', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsStore();
    await settings.load();
    // 本机没构建原生二进制时推断值为空，但绝不会再给出 Python 路径。
    expect(settings.runtimePath, settings.inferredRuntimePath);
    expect(settings.runtimePath.toLowerCase(), isNot(contains('.venv')));

    await settings.setRuntimePath('D:/somewhere/ct.exe');
    expect(settings.runtimePath, 'D:/somewhere/ct.exe');
    await settings.useInferredRuntimePath();
    expect(settings.runtimePath, settings.inferredRuntimePath);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.containsKey(SettingsStore.kRuntimePath), isFalse);
  });

  test('设置里的运行时路径就是 worker 实际启动的那个', () async {
    final binary =
        Platform.environment['CT_WORKER_BIN'] ??
        (Platform.isWindows
            ? '../native/target/debug/ct.exe'
            : '../native/target/debug/ct');
    if (!File(binary).existsSync()) {
      return; // 未构建原生二进制时不判失败
    }
    final absolute = File(binary).absolute.uri.normalizePath().toFilePath();
    final workspace = await _copyFixture();
    SharedPreferences.setMockInitialValues({
      'workspace_path': workspace.path,
      'runtime_path': absolute,
      ...legacy,
    });
    final settings = SettingsStore();
    await settings.load();

    final worker = WorkerService(settings: settings);
    await worker.start();
    expect(
      worker.status,
      WorkerStatus.ready,
      reason: worker.failureReason ?? '',
    );
    expect(worker.runtime, isNotNull);
    expect(worker.runtime!.path, absolute);
    expect(worker.runtime!.source, RuntimeSource.explicit);
    expect(worker.protocolVersion, 1, reason: '协议 v1');

    final repo = WorkbenchRepository(worker: worker);
    await repo.switchWorkspace(settings.workspacePath);
    expect(repo.loadError, isNull, reason: repo.loadError ?? '');
    expect(worker.lastWorkspaceId, isNotNull);
    expect(repo.workspaceId, worker.lastWorkspaceId);
    expect(
      repo.resources.map((r) => r.name).toList(),
      containsAll(<String>['Item', 'Rarity']),
      reason: '设置里的偏好必须真的决定启动参数与首屏数据',
    );

    repo.dispose();
    // worker 的工作目录就是该临时目录：必须先优雅关闭，才能回收目录。
    await worker.stop();
    try {
      await workspace.delete(recursive: true);
    } on FileSystemException {
      // 句柄释放有延迟时留给系统临时目录回收，不影响断言。
    }
  }, timeout: const Timeout(Duration(minutes: 2)));
}

/// 复制导出流水线夹具到临时目录（绝不使用真实 gd/）。
Future<Directory> _copyFixture() async {
  final dir = await Directory.systemTemp.createTemp('ct-settings-fixture-');
  final source = Directory('../native/fixtures/export_pipeline/workspace');
  await for (final entity in source.list(recursive: true)) {
    final relative = entity.path.substring(source.path.length + 1);
    final target = '${dir.path}/$relative';
    if (entity is Directory) {
      await Directory(target).create(recursive: true);
    } else if (entity is File) {
      await Directory(File(target).parent.path).create(recursive: true);
      await entity.copy(target);
    }
  }
  return dir;
}
