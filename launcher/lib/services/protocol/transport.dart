/// 传输层抽象与 NDJSON 编解码。
///
/// worker 进程生命周期管理属于后续任务（2.1/2.2），这里只定义接口与编解码，
/// 使协议契约可以不依赖进程独立测试。
library;

import 'dart:async';
import 'dart:convert';

import 'messages.dart';

/// 消息超过协议上限（4 MiB）。
final class MessageTooLargeException implements Exception {
  const MessageTooLargeException(this.length);
  final int length;

  @override
  String toString() => '消息超过协议上限 4 MiB（$length 字节）';
}

/// worker 传输抽象：stdio 实现（任务 2.1）与协议夹具共用。
abstract interface class WorkerTransport {
  /// 入站消息流；解析失败以 error 事件上抛。
  Stream<Message> get messages;

  /// 发送一条消息（hello/request）。
  void send(Message message);

  /// 关闭连接；实现须先尝试安全 shutdown，不得以强杀代替取消。
  Future<void> close();
}

/// NDJSON 编解码：每行一条完整 JSON 消息。
final class NdjsonCodec {
  const NdjsonCodec();

  static const int maxMessageBytes = 4 * 1024 * 1024;

  String encodeLine(Message message) => '${jsonEncode(message.toJson())}\n';

  Message decodeLine(String line) {
    final trimmed = line.trimRight();
    if (trimmed.isEmpty) {
      throw const FormatException('空行不是合法协议消息');
    }
    if (utf8.encode(trimmed).length > maxMessageBytes) {
      throw MessageTooLargeException(utf8.encode(trimmed).length);
    }
    final Object? decoded = jsonDecode(trimmed);
    if (decoded is! Map<String, Object?>) {
      throw const FormatException('协议消息必须是 JSON 对象');
    }
    return Message.fromJson(decoded);
  }

  /// 把字节流解码为消息流：按行切分，正确处理跨 chunk 的 UTF-8。
  ///
  /// EOF 时仍有未以换行结尾的残留数据，视为对端异常断开并抛
  /// [FormatException]（协议要求每条消息以换行结束）。
  Stream<Message> decodeStream(Stream<List<int>> bytes) async* {
    var pending = '';
    // cast：调用方可能传入 Stream<Uint8List>，Utf8Decoder 的元素类型是 List<int>。
    await for (final chunk in bytes.cast<List<int>>().transform(utf8.decoder)) {
      pending += chunk;
      int idx;
      while ((idx = pending.indexOf('\n')) >= 0) {
        final line = pending.substring(0, idx);
        pending = pending.substring(idx + 1);
        if (line.trim().isEmpty) continue;
        yield decodeLine(line);
      }
    }
    if (pending.trim().isNotEmpty) {
      throw const FormatException('连接在消息中途断开');
    }
  }
}
