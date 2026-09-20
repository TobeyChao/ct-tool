// 方法名常量与机器 schema 同源校验（对应 Rust 侧 method_names.rs）。
import 'dart:convert';
import 'dart:io';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('方法名集合与 protocol.v1.json 一致', () {
    final schema =
        jsonDecode(
              File(
                '../native/docs/protocol/schema/protocol.v1.json',
              ).readAsStringSync(),
            )
            as Map<String, Object?>;
    final defs = schema[r'$defs']! as Map<String, Object?>;
    final request = defs['request']! as Map<String, Object?>;
    final properties = request['properties']! as Map<String, Object?>;
    final method = properties['method']! as Map<String, Object?>;
    final schemaMethods = (method['enum']! as List).cast<String>().toSet();

    expect(
      schemaMethods,
      equals(Methods.all.toSet()),
      reason: 'Dart 方法与 JSON Schema 不一致',
    );
    expect(Methods.all.length, 25, reason: '方法数量变化需同步 v1.md / schema / Rust');
  });
}
