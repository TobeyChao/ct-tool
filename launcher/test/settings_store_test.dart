import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ct_launcher/services/settings_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'old preferences keep workspace and shell behavior without Python fallback',
    () async {
      SharedPreferences.setMockInitialValues({
        'workspace_path': '/workspace/custom',
        'tool_dir': '/old/ct',
        'port': 8123,
        'auto_start': true,
        'tray_resident': true,
      });
      final store = SettingsStore();
      await store.load();
      expect(store.workspacePath, '/workspace/custom');
      expect(store.port, 8123);
      expect(store.autoStart, isTrue);
      expect(store.trayResident, isTrue);
      expect(store.nativeRuntimePath, isNot(contains('.venv')));
      expect(store.nativeRuntimePath, isNot('/old/ct'));
      await store.setNativeRuntimePath('/runtime/ct');
      final reloaded = SettingsStore();
      await reloaded.load();
      expect(reloaded.nativeRuntimePath, '/runtime/ct');
    },
  );
  test('fresh install never binds the real game workspace', () async {
    SharedPreferences.setMockInitialValues({});
    final store = SettingsStore();
    await store.load();
    expect(store.workspacePath, isEmpty);
  });
}
