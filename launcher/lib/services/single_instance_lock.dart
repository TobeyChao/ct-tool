import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 单实例文件锁（对齐 FlClash 的 SingleInstanceLock 做法）：
/// 锁文件放在 Application Support 目录（系统保证存在），
/// 用 OS 文件锁检测重复实例；进程退出时锁自动释放。
class SingleInstanceLock {
  RandomAccessFile? _accessFile;

  Future<bool> acquire() async {
    try {
      final dir = await getApplicationSupportDirectory();
      await Directory(dir.path).create(recursive: true);
      final lockFile = File('${dir.path}/ct_launcher.lock');
      await lockFile.create();
      _accessFile = await lockFile.open(mode: FileMode.write);
      // 500ms 内拿不到锁视为已有实例（FlClash 为阻塞式，这里避免挂起）
      await _accessFile!.lock().timeout(const Duration(milliseconds: 500));
      return true;
    } catch (_) {
      return false;
    }
  }
}
