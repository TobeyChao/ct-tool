import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:ct_launcher/services/panel_service.dart';
import 'package:ct_launcher/services/settings_store.dart';

void main() {
  group('resolveBundledCtPath（平台布局）', () {
    test('macOS：定位 .app/Contents/Resources/runtime/ct', () {
      final root = Directory.systemTemp.createTempSync('ct_bundle_macos_');
      final macos = Directory('${root.path}/ct_launcher.app/Contents/MacOS')
        ..createSync(recursive: true);
      final exe = File('${macos.path}/ct_launcher')..createSync();
      final runtime =
          Directory('${root.path}/ct_launcher.app/Contents/Resources/runtime')
            ..createSync(recursive: true);
      final ct = File('${runtime.path}/ct')..createSync();

      expect(
        PanelService.resolveBundledCtPath(
          executablePath: exe.path,
          isMacOS: true,
          isWindows: false,
        ),
        ct.path,
      );
      root.deleteSync(recursive: true);
    });

    test('macOS：无内置运行时返回 null', () {
      final root = Directory.systemTemp.createTempSync('ct_bundle_macos_');
      final macos = Directory('${root.path}/ct_launcher.app/Contents/MacOS')
        ..createSync(recursive: true);
      final exe = File('${macos.path}/ct_launcher')..createSync();

      expect(
        PanelService.resolveBundledCtPath(
          executablePath: exe.path,
          isMacOS: true,
          isWindows: false,
        ),
        isNull,
      );
      root.deleteSync(recursive: true);
    });

    test('Windows：定位同级 runtime\\ct.exe', () {
      final root = Directory.systemTemp.createTempSync('ct_bundle_win_');
      final exe = File('${root.path}/ct_launcher.exe')..createSync();
      final runtime = Directory('${root.path}/runtime')..createSync();
      final ct = File('${runtime.path}/ct.exe')..createSync();

      expect(
        PanelService.resolveBundledCtPath(
          executablePath: exe.path,
          isMacOS: false,
          isWindows: true,
        ),
        ct.path,
      );
      root.deleteSync(recursive: true);
    });

    test('Windows：无内置运行时返回 null', () {
      final root = Directory.systemTemp.createTempSync('ct_bundle_win_');
      final exe = File('${root.path}/ct_launcher.exe')..createSync();

      expect(
        PanelService.resolveBundledCtPath(
          executablePath: exe.path,
          isMacOS: false,
          isWindows: true,
        ),
        isNull,
      );
      root.deleteSync(recursive: true);
    });
  });

  group('buildLaunchCommand（三态选择）', () {
    const panelArgs = ['--root', '/tmp/gd', '--host', '127.0.0.1', '--port', '8000', '--no-browser'];

    test('内置存在 → 使用内置运行时', () {
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: '/bundled/runtime/ct',
        ctCliPath: '/none/ct',
        pythonPath: '/none/python',
        panelArgs: panelArgs,
      );
      expect(cmd, isNotNull);
      expect(cmd!.executable, '/bundled/runtime/ct');
      expect(cmd.args, ['panel', ...panelArgs]);
    });

    test('内置缺失 + 工具目录 CLI 存在 → 回退 CLI', () {
      final root = Directory.systemTemp.createTempSync('ct_cli_');
      final cli = File('${root.path}/ct')..createSync();
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: null,
        ctCliPath: cli.path,
        pythonPath: '/none/python',
        panelArgs: panelArgs,
      );
      expect(cmd, isNotNull);
      expect(cmd!.executable, cli.path);
      expect(cmd.args, ['panel', ...panelArgs]);
      root.deleteSync(recursive: true);
    });

    test('内置缺失 + venv python 存在 → 回退 python -m ct.cli', () {
      final root = Directory.systemTemp.createTempSync('ct_py_');
      final python = File('${root.path}/python')..createSync();
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: null,
        ctCliPath: '/none/ct',
        pythonPath: python.path,
        panelArgs: panelArgs,
      );
      expect(cmd, isNotNull);
      expect(cmd!.executable, python.path);
      expect(cmd.args, ['-m', 'ct.cli', 'panel', ...panelArgs]);
      root.deleteSync(recursive: true);
    });

    test('内置与外部均缺失 → null', () {
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: null,
        ctCliPath: '/none/ct',
        pythonPath: '/none/python',
        panelArgs: panelArgs,
      );
      expect(cmd, isNull);
    });
  });

  group('真实启动', () {
    Directory tempWorkspace() {
      final root = Directory.systemTemp.createTempSync('ct_ws_');
      final config = Directory('${root.path}/config')..createSync(recursive: true);
      File('${config.path}/global.yaml').writeAsStringSync('''
primary_lang: zh
secondary_langs: []
schemas_dir: config/schemas
excel_dir: excel
output_dir: output
cache_dir: cache
i18n_dir: i18n
''');
      final schemas = Directory('${root.path}/config/schemas')
        ..createSync(recursive: true);
      File('${schemas.path}/Item.yaml').writeAsStringSync('''
table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Name
    type: string
''');
      for (final d in ['excel', 'output', 'cache', 'i18n']) {
        Directory('${root.path}/$d').createSync();
      }
      return root;
    }

    test('内置与外部均缺失 → 报错提示内置运行时与工具目录', () async {
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..toolDir = '/nonexistent-tool-dir'
        ..port = 18121;
      final svc = PanelService(settings: settings);

      await svc.start();

      expect(svc.status, PanelStatus.failed);
      expect(svc.failureReason, contains('内置运行时'));
      expect(svc.failureReason, contains('工具目录'));
      expect(svc.logs.any((e) => e.message.contains('内置运行时')), isTrue);
      ws.deleteSync(recursive: true);
    });

    test('外部工具目录回退：venv ct 真实启动到 running', () async {
      final venvCt = '../ct/.venv/bin/ct';
      expect(File(venvCt).existsSync(), isTrue,
          reason: '需要 ct/.venv 存在（仓库内测试环境）');
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..toolDir = Directory.current.parent.path + '/ct'
        ..port = 18122;
      final svc = PanelService(settings: settings);

      await svc.start();

      final client = HttpClient();
      var ready = false;
      for (var i = 0; i < 40 && !ready; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 250));
        try {
          final req = await client
              .getUrl(Uri.parse('http://127.0.0.1:${settings.port}/'))
              .timeout(const Duration(seconds: 2));
          final res = await req.close();
          ready = res.statusCode == 200;
        } catch (_) {
          // 服务尚未就绪，继续轮询
        }
      }

      expect(ready, isTrue, reason: 'panel 应在 ${settings.port} 端口就绪');
      expect(svc.status, PanelStatus.running);
      expect(
        svc.logs.any((e) => e.message.contains('工具目录运行时')),
        isTrue,
        reason: '回退模式应提示使用外部工具',
      );

      await svc.stop();
      client.close();
      ws.deleteSync(recursive: true);
    });
  });
}
