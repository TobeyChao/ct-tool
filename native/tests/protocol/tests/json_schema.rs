//! 机器 schema 契约测试：
//! 每行 golden sample 必须通过 `docs/protocol/schema/protocol.v1.json`。

use std::path::PathBuf;

fn schema_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../docs/protocol/schema/protocol.v1.json")
}

fn examples_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../docs/protocol/examples")
}

#[test]
fn samples_validate_against_json_schema() {
    let schema_text = std::fs::read_to_string(schema_path()).expect("读取 schema 失败");
    let schema: serde_json::Value = serde_json::from_str(&schema_text).expect("schema 非法");
    let validator = jsonschema::validator_for(&schema).expect("schema 编译失败");

    let mut files: Vec<_> = std::fs::read_dir(examples_dir())
        .expect("examples 目录不存在")
        .map(|e| e.expect("读取目录失败").path())
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("ndjson"))
        .collect();
    files.sort();
    assert!(!files.is_empty());

    for path in &files {
        let text = std::fs::read_to_string(path).expect("读取样例失败");
        for (idx, line) in text.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let instance: serde_json::Value = serde_json::from_str(line).expect("非法 JSON");
            if !validator.is_valid(&instance) {
                let errors: Vec<String> = validator
                    .iter_errors(&instance)
                    .map(|e| e.to_string())
                    .collect();
                panic!(
                    "{}:{} 不符合 protocol.v1.json:\n{}",
                    path.display(),
                    idx + 1,
                    errors.join("\n")
                );
            }
        }
    }
}
