import 'dart:io';

import 'package:ct_launcher/services/settings_store.dart';
import 'package:ct_launcher/services/single_instance_lock.dart';
import 'package:ct_launcher/services/window_options.dart';
import 'package:ct_launcher/ui/tokens.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 桌面壳入口条件（任务 2.5）：单实例、可调窗口、不继承旧固定尺寸设置。
void main() {
  test('单实例锁状态自洽：release 之后才可再接管', () async {
    final dir = await Directory.systemTemp.createTemp('ct-single-');
    addTearDown(() {
      try {
        dir.deleteSync(recursive: true);
      } on FileSystemException {
        // 交给系统回收
      }
    });
    // 诚实边界：OS 文件锁在同一进程内不互斥，跨进程互斥要靠双启动演练验证
    // （归入任务 5.5）。这里只钉同进程语义与状态标志，不假称已验跨进程。
    final first = SingleInstanceLock(dirOverride: dir);
    expect(await first.acquire(), isTrue);
    expect(first.held, isTrue);
    await first.release();
    expect(first.held, isFalse);

    final again = SingleInstanceLock(dirOverride: dir);
    expect(await again.acquire(), isTrue, reason: '释放后应能再次取得');
    expect(again.held, isTrue);
    await again.release();
    expect(again.held, isFalse);
  });

  test('窗口参数：默认 1280×800、最小 1024×700、可调', () {
    final options = desktopWindowOptions();
    expect(desktopWindowIsResizable, isTrue);
    expect(options.size?.width, ctWindowDefaultWidth);
    expect(options.size?.height, ctWindowDefaultHeight);
    expect(options.minimumSize?.width, ctWindowMinWidth);
    expect(options.minimumSize?.height, ctWindowMinHeight);
    expect(
      desktopWindowSize.width,
      greaterThan(desktopWindowMinimumSize.width),
    );
    expect(options.center, isTrue);
    expect(options.title, isNotEmpty);
    if (Platform.isWindows || Platform.isMacOS) {
      expect(options.titleBarStyle!.name, 'hidden');
    } else {
      expect(options.titleBarStyle!.name, 'normal');
    }
  });

  test('旧面板时代的固定尺寸窗口偏好被清除且不被读取', () async {
    SharedPreferences.setMockInitialValues({
      'workspace_path': 'E:/repo/gd',
      'window_width': 640,
      'window_height': 480,
      'window_resizable': false,
      'window_x': 10,
      'window_y': 20,
      'window_maximized': true,
    });
    final settings = SettingsStore();
    await settings.load();

    expect(settings.migratedFromLegacy, isTrue);
    final prefs = await SharedPreferences.getInstance();
    for (final key in ['window_width', 'window_height', 'window_resizable']) {
      expect(prefs.containsKey(key), isFalse, reason: '$key 必须被废弃');
    }
    expect(await SettingsStore.legacyKeysCleared(), isTrue);
    // 窗口参数只来自 window_options.dart，与偏好无关
    expect(desktopWindowOptions().size?.width, ctWindowDefaultWidth);
    expect(settings.workspacePath, 'E:/repo/gd', reason: '工作区偏好仍保留');
  });
}
