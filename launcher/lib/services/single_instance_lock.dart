import 'dart:async';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 单实例文件锁（对齐 FlClash 的 SingleInstanceLock 做法）：
/// 锁文件放在 Application Support 目录（系统保证存在），
/// 用 OS 文件锁检测重复实例；进程退出时锁自动释放。
class SingleInstanceLock {
  SingleInstanceLock({this.dirOverride});

  /// 测试可注入目录；生产用应用支持目录（系统保证存在）。
  final Directory? dirOverride;
  RandomAccessFile? _accessFile;

  /// 是否已持有锁（供界面与测试断言，不靠猜）。
  bool get held => _accessFile != null;

  Future<Directory> _directory() async =>
      dirOverride ?? await getApplicationSupportDirectory();

  Future<bool> acquire() async {
    try {
      final dir = await _directory();
      await Directory(dir.path).create(recursive: true);
      final lockFile = File('${dir.path}/ct_launcher.lock');
      await lockFile.create();
      _accessFile = await lockFile.open(mode: FileMode.write);
      // 500ms 内拿不到锁视为已有实例（FlClash 为阻塞式，这里避免挂起）
      await _accessFile!.lock().timeout(const Duration(milliseconds: 500));
      return true;
    } on TimeoutException {
      // 明确是「另一个实例持有」——这才是单实例语义。
      await _accessFile?.close();
      _accessFile = null;
      return false;
    } catch (e) {
      // 查不出来（插件缺失、权限等）不能当成「已有实例」：
      // 否则应用永远起不来。这里放行并留一行诊断。
      stderr.writeln('单实例检测失败，按可启动处理：$e');
      await _accessFile?.close();
      _accessFile = null;
      return true;
    }
  }

  Future<void> release() async {
    final file = _accessFile;
    _accessFile = null;
    if (file == null) return;
    try {
      await file.unlock();
      await file.close();
    } catch (_) {
      // 进程退出时 OS 会自行释放
    }
  }
}
