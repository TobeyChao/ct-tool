import 'dart:io';
import 'dart:convert';

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
      final runtime = Directory(
        '${root.path}/ct_launcher.app/Contents/Resources/runtime',
      )..createSync(recursive: true);
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
    const panelArgs = [
      '--root',
      '/tmp/gd',
      '--host',
      '127.0.0.1',
      '--port',
      '8000',
      '--no-browser',
    ];

    test('内置存在 → 使用内置运行时', () {
      final root = Directory.systemTemp.createTempSync('ct_builtin_');
      addTearDown(() => root.deleteSync(recursive: true));
      final bundled = File('${root.path}/ct')..createSync();
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: bundled.path,
        nativeRuntimePath: '/none/ct',
        panelArgs: panelArgs,
      );
      expect(cmd, isNotNull);
      expect(cmd!.executable, bundled.path);
      expect(cmd.args, ['panel', ...panelArgs]);
    });

    test('内置缺失 + 原生路径 CLI 存在 → 回退 CLI', () {
      final root = Directory.systemTemp.createTempSync('ct_cli_');
      final cli = File('${root.path}/ct')..createSync();
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: null,
        nativeRuntimePath: cli.path,
        panelArgs: panelArgs,
      );
      expect(cmd, isNotNull);
      expect(cmd!.executable, cli.path);
      expect(cmd.args, ['panel', ...panelArgs]);
      root.deleteSync(recursive: true);
    });

    test('内置与外部均缺失 → null', () {
      final cmd = PanelService.buildLaunchCommand(
        bundledCtPath: null,
        nativeRuntimePath: '/none/ct',
        panelArgs: panelArgs,
      );
      expect(cmd, isNull);
    });
  });

  group('真实启动', () {
    String nativeCt() =>
        Platform.environment['CT_LAUNCHER_TEST_BIN'] ??
        File(
          Platform.isWindows
              ? '../native/target/debug/ct.exe'
              : '../native/target/debug/ct',
        ).absolute.path;

    Future<void> waitRunning(PanelService service) async {
      for (var i = 0; i < 100 && service.status == PanelStatus.starting; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
      }
      expect(
        service.status,
        PanelStatus.running,
        reason: service.failureReason,
      );
    }

    Future<Map<String, dynamic>> api(
      String base,
      String path, [
      Map<String, dynamic>? body,
    ]) async {
      final client = HttpClient();
      try {
        final request = await client.openUrl(
          body == null ? 'GET' : 'POST',
          Uri.parse('$base$path'),
        );
        if (body != null) {
          request.headers.contentType = ContentType.json;
          request.write(jsonEncode(body));
        }
        final response = await request.close();
        final envelope =
            jsonDecode(await response.transform(utf8.decoder).join())
                as Map<String, dynamic>;
        expect(response.statusCode, 200, reason: envelope.toString());
        expect(envelope['ok'], true);
        return envelope;
      } finally {
        client.close(force: true);
      }
    }

    Directory tempWorkspace() {
      final root = Directory.systemTemp.createTempSync('ct_ws_');
      final config = Directory('${root.path}/config')
        ..createSync(recursive: true);
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

    test('内置与外部均缺失 → 报错提示内置运行时与原生路径', () async {
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..nativeRuntimePath = '/nonexistent-native-ct'
        ..port = 18121;
      final svc = PanelService(settings: settings);

      await svc.start();

      expect(svc.status, PanelStatus.failed);
      expect(svc.failureReason, contains('内置运行时'));
      expect(svc.failureReason, contains('原生 ct'));
      expect(svc.logs.any((e) => e.message.contains('内置运行时')), isTrue);
      ws.deleteSync(recursive: true);
    });

    test('外部原生路径回退：native ct 真实启动到 running', () async {
      final nativeBinary = nativeCt();
      expect(
        File(nativeBinary).existsSync(),
        isTrue,
        reason: '先运行 cargo build -p ct-cli',
      );
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..nativeRuntimePath = nativeBinary
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
        svc.logs.any((e) => e.message.contains('外部原生运行时')),
        isTrue,
        reason: '回退模式应提示使用外部工具',
      );

      await svc.stop();
      expect(svc.status, PanelStatus.stopped);
      await svc.start();
      await svc.stop(); // 即使在启动中关闭，也等待子进程退出
      expect(svc.status, PanelStatus.stopped);
      svc.dispose();
      client.close();
      ws.deleteSync(recursive: true);
    });

    test('原生 HTTP 就绪后打开一次，导出中停止完整发布，重启不留孤儿', () async {
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..nativeRuntimePath = nativeCt()
        ..port = 18123;
      final opened = <String>[];
      final service = PanelService(
        settings: settings,
        onReady: (url) async {
          final info = await api(url, '/api/service');
          expect(info['data']['kernel'], 'native');
          opened.add(url);
        },
      );
      addTearDown(() async {
        await service.stop();
        service.dispose();
        ws.deleteSync(recursive: true);
      });
      await service.start();
      expect(opened, isEmpty, reason: '进程刚创建时不能提前打开');
      await waitRunning(service);
      for (var i = 0; i < 50 && opened.isEmpty; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      expect(opened, [settings.baseUrl]);
      final firstPid = service.processId!;
      final firstInstance = (await api(
        settings.baseUrl,
        '/api/service',
      ))['data']['instanceId'];
      for (var i = 0; i < 80; i++) {
        final table = 'T${i.toString().padLeft(3, '0')}';
        File('${ws.path}/config/schemas/$table.yaml').writeAsStringSync('''
table: $table
primary: Id
fields:
  - name: Id
    type: int32
  - name: Name
    type: string
''');
        await api(settings.baseUrl, '/api/schema-workspace/gen-template', {
          'table': table,
        });
      }
      await api(settings.baseUrl, '/api/schema-workspace/gen-template', {
        'table': 'Item',
      });
      final result = await api(settings.baseUrl, '/api/export', {
        'forced': true,
      });
      expect(result['data']['status'], 'running');
      // Exercise the launcher's actual EOF stop protocol, not a direct process kill.
      await Future.wait([service.stop(), service.stop()]);
      expect(service.status, PanelStatus.stopped);
      expect(service.processId, isNull);
      expect(Process.killPid(firstPid, ProcessSignal.sigcont), false);
      expect(service.logs.any((log) => log.message.contains('安全停止')), true);
      final ledger = jsonDecode(
        File('${ws.path}/cache/state.json').readAsStringSync(),
      );
      expect((ledger['excel_hashes'] as Map).length, 81);
      expect(
        File('${ws.path}/.ct/export-publication.json').existsSync(),
        false,
      );
      for (final table in [
        'Item',
        ...List.generate(80, (i) => 'T${i.toString().padLeft(3, '0')}'),
      ]) {
        for (final artifact in [
          'json/${table.toLowerCase()}_zh.json',
          'fbs/${table.toLowerCase()}.fbs',
          'generated/csharp/${table.toLowerCase()}accessor.cs',
          'generated/lua/${table.toLowerCase()}accessor.lua',
        ]) {
          expect(
            File('${ws.path}/output/$artifact').lengthSync(),
            greaterThan(0),
          );
        }
      }
      expect(
        File('${ws.path}/output/binary/data_zh.bin').lengthSync(),
        greaterThan(0),
      );
      await service.start();
      await waitRunning(service);
      final secondInstance = (await api(
        settings.baseUrl,
        '/api/service',
      ))['data']['instanceId'];
      expect(secondInstance, isNot(firstInstance));
      final secondPid = service.processId!;
      await service.stop();
      expect(Process.killPid(secondPid, ProcessSignal.sigcont), false);
    }, timeout: const Timeout(Duration(minutes: 2)));

    test('浏览器打开失败保留服务运行并记录提示', () async {
      final ws = tempWorkspace();
      final settings = SettingsStore()
        ..workspacePath = ws.path
        ..nativeRuntimePath = nativeCt()
        ..port = 18124;
      final service = PanelService(
        settings: settings,
        onReady: (_) async => throw StateError('test browser unavailable'),
      );
      addTearDown(() async {
        await service.stop();
        service.dispose();
        ws.deleteSync(recursive: true);
      });
      await service.start();
      await waitRunning(service);
      for (
        var i = 0;
        i < 50 && !service.logs.any((e) => e.message.contains('无法自动打开'));
        i++
      ) {
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      expect(service.logs.any((e) => e.message.contains('无法自动打开')), true);
      expect(service.status, PanelStatus.running);
      expect(
        (await api(settings.baseUrl, '/api/service'))['data']['kernel'],
        'native',
      );
    });
  });
}
