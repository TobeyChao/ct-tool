/// 大整数编解码：payload 任意深度上，超出 ±(2^53-1) 的整数以
/// `{"$int": "<decimal>"}` 标签对象表示；范围内保持 JSON number。
///
/// 与 native/crates/ct-protocol/src/bigint.rs 同规则。
library;

/// JSON 安全整数上限（2^53 - 1）。
const int maxSafeInteger = 9007199254740991;

/// 标签键（保留键，业务数据不得使用）。
const String bigintTag = r'$int';

bool _isSafeInt(int v) => v >= -maxSafeInteger && v <= maxSafeInteger;

/// 出站编码：超范围 int 与所有 BigInt 替换为标签对象（递归，返回新树）。
Object? encodeBigInts(Object? value) {
  return switch (value) {
    BigInt v => {bigintTag: v.toString()},
    int v when !_isSafeInt(v) => {bigintTag: v.toString()},
    List list => list.map(encodeBigInts).toList(),
    Map map => <String, Object?>{
      for (final e in map.entries) e.key as String: encodeBigInts(e.value),
    },
    _ => value,
  };
}

/// 入站解码：合法标签对象还原为精确整数（能放下的用 int，否则 BigInt）。
/// 非法标签（多键、非字符串、非十进制）原样保留。
Object? decodeBigInts(Object? value) {
  return switch (value) {
    List list => list.map(decodeBigInts).toList(),
    Map map when map.length == 1 && map.containsKey(bigintTag) => _decodeTag(
      map,
    ),
    Map map => <String, Object?>{
      for (final e in map.entries) e.key as String: decodeBigInts(e.value),
    },
    _ => value,
  };
}

/// 合法标签还原为能放下的最小表示：i64 范围内为 int，否则 BigInt。
Object? _decodeTag(Map<dynamic, dynamic> map) {
  final raw = map[bigintTag];
  if (raw is String) {
    final asInt = int.tryParse(raw);
    if (asInt != null) return asInt;
    final asBig = BigInt.tryParse(raw);
    if (asBig != null) return asBig;
  }
  // 非法标签原样保留（键值不变，仅重建为字符串键映射）。
  return <String, Object?>{
    for (final e in map.entries) e.key as String: decodeBigInts(e.value),
  };
}
