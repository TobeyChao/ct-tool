// flutter drive 的驱动入口（任务 5.2 需要 profile/release 构建，flutter test 只能 debug）。
// 用法见 integration_test/ui_responsiveness_test.dart 顶部注释。
import 'package:integration_test/integration_test_driver.dart';

Future<void> main() => integrationDriver();
