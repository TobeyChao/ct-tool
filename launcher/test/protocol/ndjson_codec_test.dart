// NDJSON 编解码：行切分、跨 chunk UTF-8、超限与断连检测。
import 'dart:convert';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const codec = NdjsonCodec();

  test('编码产出单行 NDJSON', () {
    final line = codec.encodeLine(
      const Request(
        requestId: 1,
        method: Methods.validate,
        workspaceRoot: '/tmp/gd',
      ),
    );
    expect(line.endsWith('\n'), isTrue);
    expect(line.substring(0, line.length - 1).contains('\n'), isFalse);
    expect(line, contains('"type":"request"'));
  });

  test('解码往返', () {
    final message = codec.decodeLine(
      codec.encodeLine(
        const Hello(
          protocolVersion: 1,
          coreVersion: '0.0.0',
          capabilities: ['workspace'],
        ),
      ),
    );
    expect(message, isA<Hello>());
    expect((message as Hello).protocolVersion, 1);
  });

  test('流式解码处理跨 chunk 的多字节字符', () async {
    final text = codec.encodeLine(
      const LogEvent(
        requestId: 1,
        workspaceId: 'w',
        seq: 1,
        module: 'export',
        level: 'info',
        message: '解析校验完成：中文内容',
      ),
    );
    final bytes = utf8.encode(text);
    // 刻意在多字节字符中间切开。
    final mid = bytes.length ~/ 2;
    final stream = Stream.fromIterable([
      bytes.sublist(0, mid),
      bytes.sublist(mid),
    ]);
    final messages = await codec.decodeStream(stream).toList();
    expect(messages, hasLength(1));
    expect((messages.single as LogEvent).message, '解析校验完成：中文内容');
  });

  test('多条消息连续解码', () async {
    final buffer = StringBuffer()
      ..write(
        codec.encodeLine(
          const Hello(
            protocolVersion: 1,
            coreVersion: '0.0.0',
            capabilities: [],
          ),
        ),
      )
      ..write(
        codec.encodeLine(
          const Request(
            requestId: 9,
            method: Methods.shutdown,
            workspaceRoot: '/tmp/gd',
          ),
        ),
      );
    final messages = await codec
        .decodeStream(Stream.value(utf8.encode(buffer.toString())))
        .toList();
    expect(messages, hasLength(2));
    expect(messages.last, isA<Request>());
  });

  test('EOF 时残留半条消息视为异常断开', () {
    final stream = Stream.value(utf8.encode('{"type":"hello"'));
    expect(
      codec.decodeStream(stream).toList(),
      throwsA(isA<FormatException>()),
    );
  });

  test('超限消息抛出 MessageTooLargeException', () {
    final huge =
        '{"type":"request","requestId":1,"method":"validate",'
        '"workspaceRoot":"${'x' * (NdjsonCodec.maxMessageBytes)}"}';
    expect(
      () => codec.decodeLine(huge),
      throwsA(isA<MessageTooLargeException>()),
    );
  });

  test('非对象消息抛 FormatException', () {
    expect(() => codec.decodeLine('[1,2]'), throwsA(isA<FormatException>()));
    expect(() => codec.decodeLine('   '), throwsA(isA<FormatException>()));
  });
}
