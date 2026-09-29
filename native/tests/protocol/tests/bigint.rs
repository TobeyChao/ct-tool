//! 大整数编码规则：超出 ±(2^53-1) 使用 {"$int": "<decimal>"} 标签，
//! 范围内保持 JSON number；双向无损。

use ct_protocol::bigint::{decode_value, encode_value, serde_i64, MAX_SAFE_INTEGER};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[test]
fn in_range_integers_stay_plain_numbers() {
    let mut v = json!({"a": 42, "b": MAX_SAFE_INTEGER, "c": -MAX_SAFE_INTEGER, "d": [0, 1]});
    let original = v.clone();
    encode_value(&mut v);
    assert_eq!(v, original);
}

#[test]
fn out_of_range_integers_are_tagged_recursively() {
    let mut v = json!({
        "cell": u64::MAX,
        "nested": {"list": [i64::MIN, 7]}
    });
    encode_value(&mut v);
    assert_eq!(v["cell"], json!({"$int": "18446744073709551615"}));
    assert_eq!(
        v["nested"]["list"][0],
        json!({"$int": "-9223372036854775808"})
    );
    assert_eq!(v["nested"]["list"][1], json!(7));
}

#[test]
fn tagged_values_decode_back_to_exact_integers() {
    let mut v = json!([{"$int": "18446744073709551615"}, {"$int": "-9223372036854775808"}]);
    decode_value(&mut v);
    assert_eq!(v[0].as_u64(), Some(u64::MAX));
    assert_eq!(v[1].as_i64(), Some(i64::MIN));
}

#[test]
fn encode_then_decode_is_identity_for_boundary_values() {
    for n in [
        i64::MIN,
        -MAX_SAFE_INTEGER - 1,
        -MAX_SAFE_INTEGER,
        0,
        MAX_SAFE_INTEGER,
        MAX_SAFE_INTEGER + 1,
        i64::MAX,
    ] {
        let v = json!({"n": n});
        let encoded = {
            let mut tmp = v.clone();
            encode_value(&mut tmp);
            tmp
        };
        let mut decoded = encoded.clone();
        decode_value(&mut decoded);
        assert_eq!(decoded, v, "边界值 {n} 往返失败");
    }
}

#[test]
fn malformed_tags_are_left_untouched() {
    let mut v = json!([{"$int": "abc"}, {"$int": "1", "x": 2}, {"$int": 3}]);
    let original = v.clone();
    decode_value(&mut v);
    assert_eq!(v, original);
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct Typed {
    #[serde(with = "serde_i64")]
    v: i64,
}

#[test]
fn typed_field_uses_dual_representation() {
    let small = serde_json::to_value(Typed { v: 7 }).unwrap();
    assert_eq!(small, json!({"v": 7}));
    let big = serde_json::to_value(Typed { v: i64::MAX }).unwrap();
    assert_eq!(big, json!({"v": {"$int": "9223372036854775807"}}));

    let back: Typed = serde_json::from_value(big).unwrap();
    assert_eq!(back, Typed { v: i64::MAX });
    let back: Typed = serde_json::from_value(json!({"v": 9007199254740991i64})).unwrap();
    assert_eq!(
        back,
        Typed {
            v: MAX_SAFE_INTEGER
        }
    );
}

#[test]
fn preview_sample_bigint_cell_decodes() {
    let mut row: Value =
        serde_json::from_str(r#"[{"$int":"18446744073709551615"},"大剑"]"#).unwrap();
    decode_value(&mut row);
    assert_eq!(row[0].as_u64(), Some(u64::MAX));
    assert_eq!(row[1].as_str(), Some("大剑"));
}
