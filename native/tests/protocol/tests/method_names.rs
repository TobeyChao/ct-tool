//! 方法名常量与文档/schema 一致性。

use ct_protocol::methods;

#[test]
fn method_names_are_unique_and_match_documented_set() {
    let mut sorted = methods::ALL.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    assert_eq!(sorted.len(), methods::ALL.len(), "方法名重复");
    assert_eq!(
        methods::ALL.len(),
        25,
        "方法数量变化需同步 v1.md 与 JSON Schema"
    );

    for &name in methods::ALL {
        assert!(!name.is_empty());
        assert_eq!(name, name.to_ascii_lowercase().as_str(), "方法名必须全小写");
    }
}

#[test]
fn schema_enum_matches_method_constants() {
    let schema_text = std::fs::read_to_string(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../docs/protocol/schema/protocol.v1.json"),
    )
    .expect("读取 schema 失败");
    let schema: serde_json::Value = serde_json::from_str(&schema_text).unwrap();
    let enum_values: Vec<&str> = schema["$defs"]["request"]["properties"]["method"]["enum"]
        .as_array()
        .expect("schema 缺 method enum")
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();

    for &name in methods::ALL {
        assert!(enum_values.contains(&name), "schema 缺方法 {name}");
    }
    assert_eq!(
        enum_values.len(),
        methods::ALL.len(),
        "schema 方法集合不一致"
    );
}
