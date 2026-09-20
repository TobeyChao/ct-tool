// 大整数标签规则：与 native/tests/protocol/bigint.rs 同场景。
import 'dart:convert';

import 'package:ct_launcher/services/protocol/protocol.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('范围内整数保持不变', () {
    final v = {
      'a': 42,
      'b': maxSafeInteger,
      'c': -maxSafeInteger,
      'd': [0, 1],
    };
    expect(encodeBigInts(v), equals(v));
  });

  test('超范围整数递归打标签', () {
    final encoded =
        encodeBigInts({
              'cell': BigInt.parse('18446744073709551615'),
              'nested': {
                'list': [-9223372036854775808, 7],
              },
            })
            as Map<String, Object?>;
    expect(encoded['cell'], equals({r'$int': '18446744073709551615'}));
    final list = (encoded['nested']! as Map<String, Object?>)['list']! as List;
    expect(list[0], equals({r'$int': '-9223372036854775808'}));
    expect(list[1], 7);
  });

  test('标签解码回精确整数', () {
    final decoded =
        decodeBigInts([
              {r'$int': '18446744073709551615'},
              {r'$int': '-9223372036854775808'},
            ])
            as List;
    // u64::MAX 超出 i64 范围，VM 上落在 BigInt。
    expect(decoded[0], equals(BigInt.parse('18446744073709551615')));
    expect(decoded[1], equals(-9223372036854775808));
  });

  test('边界值往返一致（解码归一为最小表示）', () {
    final cases = <Object, Object>{
      BigInt.parse('-9223372036854775808'):
          -9223372036854775808, // i64::MIN → int
      -maxSafeInteger - 1: -maxSafeInteger - 1,
      -maxSafeInteger: -maxSafeInteger,
      0: 0,
      maxSafeInteger: maxSafeInteger,
      maxSafeInteger + 1: maxSafeInteger + 1,
      BigInt.parse('9223372036854775807'):
          9223372036854775807, // i64::MAX → int
      BigInt.parse('18446744073709551615'): BigInt.parse(
        '18446744073709551615',
      ), // u64::MAX 保持 BigInt
    };
    for (final entry in cases.entries) {
      final roundtrip = decodeBigInts(encodeBigInts({'n': entry.key}));
      expect(
        roundtrip,
        equals({'n': entry.value}),
        reason: '边界值 ${entry.key} 往返失败',
      );
    }
  });

  test('非法标签原样保留', () {
    final v = [
      {r'$int': 'abc'},
      {r'$int': '1', 'x': 2},
      {r'$int': 3},
    ];
    expect(decodeBigInts(v), equals(v));
  });

  test('preview 样例中的大整数单元格可解码', () {
    final row =
        decodeBigInts(
              jsonDecode(r'[{"$int":"18446744073709551615"},"大剑"]')
                  as List<Object?>,
            )
            as List;
    expect(row[0], equals(BigInt.parse('18446744073709551615')));
    expect(row[1], '大剑');
  });
}
