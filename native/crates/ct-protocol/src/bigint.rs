//! 大整数编码：协议可无损传递 i64/u64。
//!
//! 规则：payload 任意深度上，超出 ±(2^53-1) 的整数以
//! `{"$int": "<decimal>"}` 标签对象表示；范围内保持 JSON number。
//! 标签对象的 `$int` 是唯一保留键，业务数据不得使用。

use serde_json::{Map, Number, Value};

/// JSON 安全整数上限（2^53 - 1）。
pub const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
/// 标签键。
pub const TAG: &str = "$int";

fn is_out_of_range(n: &Number) -> Option<String> {
    if let Some(v) = n.as_i64() {
        if !(-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&v) {
            return Some(v.to_string());
        }
        return None;
    }
    n.as_u64()
        .filter(|v| *v > MAX_SAFE_INTEGER as u64)
        .map(|v| v.to_string())
}

/// 出站编码：把 `value` 中超范围的整数替换为标签对象（原地、递归）。
pub fn encode_value(value: &mut Value) {
    match value {
        Value::Number(n) => {
            if let Some(decimal) = is_out_of_range(n) {
                let mut obj = Map::with_capacity(1);
                obj.insert(TAG.to_string(), Value::String(decimal));
                *value = Value::Object(obj);
            }
        }
        Value::Array(items) => items.iter_mut().for_each(encode_value),
        Value::Object(map) => map.values_mut().for_each(encode_value),
        _ => {}
    }
}

/// 入站解码：把标签对象还原为精确整数（原地、递归）。
/// 非法标签（多键、非字符串、非十进制）原样保留，由上层按业务校验报错。
pub fn decode_value(value: &mut Value) {
    match value {
        Value::Object(map) if map.len() == 1 && map.contains_key(TAG) => {
            let decoded = map.get(TAG).and_then(Value::as_str).and_then(|s| {
                s.parse::<i64>()
                    .map(Number::from)
                    .ok()
                    .or_else(|| s.parse::<u64>().map(Number::from).ok())
            });
            if let Some(number) = decoded {
                *value = Value::Number(number);
            }
        }
        Value::Array(items) => items.iter_mut().for_each(decode_value),
        Value::Object(map) => map.values_mut().for_each(decode_value),
        _ => {}
    }
}

/// 类型化整数字段的 serde 适配：`#[serde(with = "bigint::serde_i64")]`。
///
/// 序列化遵循同一规则（范围内 number、超范围标签对象）；
/// 反序列化接受 number 或标签对象，其余形态报错。
pub mod serde_i64 {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};
    use serde_json::Value;

    use super::{decode_value, encode_value};

    pub fn serialize<S: Serializer>(v: &i64, serializer: S) -> Result<S::Ok, S::Error> {
        let mut value = Value::from(*v);
        encode_value(&mut value);
        value.serialize(serializer)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<i64, D::Error> {
        let mut value = Value::deserialize(deserializer)?;
        decode_value(&mut value);
        value
            .as_i64()
            .ok_or_else(|| serde::de::Error::custom("期望整数或 $int 标签对象"))
    }
}
