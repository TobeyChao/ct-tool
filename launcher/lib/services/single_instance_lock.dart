import 'dart:io';

import 'package:flutter/services.dart';
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
    if (held) return true;
    final Directory dir;
    try {
      dir = await _directory();
    } on MissingPluginException catch (e) {
      // 无桌面插件的宿主（例如 widget 测试）不能取得默认目录。
      // 只允许这个有明确证据的分支绕过；实际文件锁失败一律拒绝启动。
      if (dirOverride != null) rethrow;
      stderr.writeln('默认单实例目录插件不可用，跳过检测：$e');
      return true;
    } catch (e) {
      stderr.writeln('无法取得单实例锁目录：$e');
      return false;
    }

    RandomAccessFile? file;
    try {
      await dir.create(recursive: true);
      file = await File(
        '${dir.path}/ct_launcher.lock',
      ).open(mode: FileMode.append);
      // exclusive 是非阻塞锁；竞争时立即抛错（macOS errno 35）。
      // 不对阻塞锁套 timeout：timeout 不会取消仍待完成的 OS 锁操作。
      await file.lock(FileLock.exclusive);
      _accessFile = file;
      return true;
    } catch (e) {
      stderr.writeln('无法取得单实例文件锁，拒绝启动：$e');
      try {
        await file?.close();
      } catch (_) {}
      return false;
    }
  }

  Future<void> release() async {
    final file = _accessFile;
    _accessFile = null;
    if (file == null) return;
    try {
      await file.unlock();
    } catch (_) {
      // 即使解锁失败也要关闭句柄，让 OS 释放锁。
    } finally {
      try {
        await file.close();
      } catch (_) {}
    }
  }
}
