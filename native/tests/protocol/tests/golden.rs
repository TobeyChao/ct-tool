//! golden samples 契约测试：
//! `docs/protocol/examples/*.ndjson` 每行必须能解析为 `Message`
//! 且序列化往返后与原文逐字节等价（语义级 JSON 比较）。

use std::fs;
use std::path::PathBuf;

use ct_protocol::message::Message;

fn examples_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../docs/protocol/examples")
}

fn sample_files() -> Vec<PathBuf> {
    let mut files: Vec<_> = fs::read_dir(examples_dir())
        .expect("examples 目录不存在")
        .map(|e| e.expect("读取目录失败").path())
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("ndjson"))
        .collect();
    files.sort();
    files
}

#[test]
fn every_sample_line_roundtrips_through_rust_types() {
    let files = sample_files();
    assert!(files.len() >= 10, "样例文件数量不足：{}", files.len());

    let mut lines = 0usize;
    for path in &files {
        let text = fs::read_to_string(path).expect("读取样例失败");
        for (idx, line) in text.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            lines += 1;
            let raw: serde_json::Value = serde_json::from_str(line)
                .unwrap_or_else(|e| panic!("{}:{} 非法 JSON: {e}", path.display(), idx + 1));
            let msg: Message = serde_json::from_value(raw.clone())
                .unwrap_or_else(|e| panic!("{}:{} 不符合协议类型: {e}", path.display(), idx + 1));
            let back = serde_json::to_value(&msg).expect("序列化失败");
            assert_eq!(raw, back, "{}:{} 序列化往返不一致", path.display(), idx + 1);
        }
    }
    assert!(lines >= 25, "样例行数不足：{lines}");
}

#[test]
fn samples_cover_all_message_types() {
    let mut types: Vec<String> = Vec::new();
    for path in sample_files() {
        let text = fs::read_to_string(path).expect("读取样例失败");
        for line in text.lines().filter(|l| !l.trim().is_empty()) {
            let raw: serde_json::Value = serde_json::from_str(line).expect("非法 JSON");
            types.push(raw["type"].as_str().expect("缺 type").to_string());
        }
    }
    for expected in ["hello", "request", "progress", "log", "result", "error"] {
        assert!(
            types.iter().any(|t| t == expected),
            "样例缺少 type={expected}"
        );
    }
}
