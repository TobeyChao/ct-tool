//! 导出流水线的字节驻留诊断（`CT_MEMDIAG=1` 时输出到 stderr）。
//!
//! 只统计"谁在占着内存"，不改变任何行为：默认关闭、零开销；基准与调优时用它的
//! 分阶段数字定位峰值来源（时间/内存门槛是比值口径，必须有可复现的测量）。

use std::sync::OnceLock;

/// 一项驻留量：条数 + 估算字节。
pub struct Sample {
    pub name: &'static str,
    pub count: usize,
    pub bytes: usize,
}

pub fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| {
        std::env::var("CT_MEMDIAG")
            .ok()
            .is_some_and(|v| v == "1" || v.eq_ignore_ascii_case("true"))
    })
}

pub fn report(stage: &str, samples: &[Sample]) {
    if !enabled() {
        return;
    }
    let parts: Vec<String> = samples
        .iter()
        .map(|s| format!("{}={}", s.name, mib(s.bytes as f64)))
        .collect();
    let counts: Vec<String> = samples
        .iter()
        .filter(|s| s.count > 0)
        .map(|s| format!("{}#{}", s.name, s.count))
        .collect();
    eprintln!(
        "[memdiag] {stage} {} | {}",
        parts.join(" "),
        counts.join(" ")
    );
}

fn mib(bytes: f64) -> String {
    format!("{:.1}MiB", bytes / (1024.0 * 1024.0))
}

/// 源字节驻留（任何 (path, bytes) 集合都行）。
pub fn sample_bytes<I, P>(name: &'static str, entries: I) -> Sample
where
    I: IntoIterator<Item = (P, Vec<u8>)>,
{
    let mut count = 0usize;
    let mut bytes = 0usize;
    for (_, value) in entries {
        count += 1;
        bytes += value.len();
    }
    Sample { name, count, bytes }
}

/// `serde_json::Map` 行集的粗略驻留：键 + 值的堆与结构开销，不序列化。
pub fn sample_rows(
    name: &'static str,
    rows: &[serde_json::Map<String, serde_json::Value>],
) -> Sample {
    let mut bytes = 0usize;
    for row in rows {
        // 每行的 Map/Vec 头部与树节点开销（经验值，够用于定位量级）
        bytes += 96 + row.len() * 64;
        for (key, value) in row {
            bytes += key.len();
            bytes += match value {
                serde_json::Value::String(s) => s.len() + 32,
                serde_json::Value::Array(list) => {
                    48 + list.len() * 40
                        + list
                            .iter()
                            .map(|v| match v {
                                serde_json::Value::String(s) => s.len() + 32,
                                _ => 24,
                            })
                            .sum::<usize>()
                }
                serde_json::Value::Object(inner) => {
                    64 + inner
                        .iter()
                        .map(|(k, v)| {
                            k.len()
                                + match v {
                                    serde_json::Value::String(s) => s.len() + 32,
                                    _ => 24,
                                }
                        })
                        .sum::<usize>()
                }
                other => other.to_string().len() + 24,
            };
        }
    }
    Sample {
        name,
        count: rows.len(),
        bytes,
    }
}

/// 每语言二进制产物驻留（表 → 语言 → 字节）。
pub fn sample_builds(
    name: &'static str,
    maps: &[&std::collections::BTreeMap<String, Vec<u8>>],
) -> Sample {
    let mut bytes = 0usize;
    let mut count = 0usize;
    for map in maps {
        for value in map.values() {
            count += 1;
            bytes += value.len();
        }
    }
    Sample { name, count, bytes }
}
