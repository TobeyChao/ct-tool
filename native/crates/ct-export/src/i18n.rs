//! i18n 合并与序列化（`ct/export/i18n/{merger,state}.py`）：
//! 四态状态机、确认语义、key 排序（id 数值 + 字段序）、紧凑 JSON。

use std::collections::HashMap;

use serde_json::{Map, Value};

/// 翻译状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LangStatus {
    Missing,
    Translated,
    Stale,
    Orphan,
}

impl LangStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            LangStatus::Missing => "missing",
            LangStatus::Translated => "translated",
            LangStatus::Stale => "stale",
            LangStatus::Orphan => "orphan",
        }
    }
}

/// 根据 text/confirmed/in_source 计算状态。
pub fn compute_status(text: &str, confirmed: bool, in_source: bool) -> LangStatus {
    if !in_source {
        return LangStatus::Orphan;
    }
    if text.is_empty() {
        return LangStatus::Missing;
    }
    if confirmed {
        return LangStatus::Translated;
    }
    LangStatus::Stale
}

/// 合并单条 entry（规则见模块文档与 Python 同名函数）。
pub fn merge_lang_entry(
    current_source: Option<&str>,
    lang_entry: Option<&Map<String, Value>>,
) -> Map<String, Value> {
    let mut out = Map::new();
    match (current_source, lang_entry) {
        (None, None) => panic!("current_source 与 lang_entry 不能同时为空"),
        (None, Some(entry)) => {
            let source = entry.get("source").and_then(|v| v.as_str()).unwrap_or("");
            let text = entry.get("text").and_then(|v| v.as_str()).unwrap_or("");
            let confirmed = entry
                .get("confirmed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            out.insert("source".into(), Value::String(source.to_string()));
            out.insert("text".into(), Value::String(text.to_string()));
            out.insert("confirmed".into(), Value::Bool(confirmed));
            out.insert(
                "status".into(),
                Value::String(compute_status(text, confirmed, false).as_str().into()),
            );
        }
        (Some(source), None) => {
            out.insert("source".into(), Value::String(source.to_string()));
            out.insert("text".into(), Value::String(String::new()));
            out.insert("confirmed".into(), Value::Bool(false));
            out.insert(
                "status".into(),
                Value::String(LangStatus::Missing.as_str().into()),
            );
        }
        (Some(current), Some(entry)) => {
            let existing_source = entry.get("source").and_then(|v| v.as_str()).unwrap_or("");
            let text = entry.get("text").and_then(|v| v.as_str()).unwrap_or("");
            let mut confirmed = entry
                .get("confirmed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let source = if existing_source != current {
                confirmed = false;
                current.to_string()
            } else {
                existing_source.to_string()
            };
            out.insert("source".into(), Value::String(source));
            out.insert("text".into(), Value::String(text.to_string()));
            out.insert("confirmed".into(), Value::Bool(confirmed));
            out.insert(
                "status".into(),
                Value::String(compute_status(text, confirmed, true).as_str().into()),
            );
        }
    }
    out
}

/// 对一张表的所有 key 应用 merge（含 orphan 标记）。
pub fn sync_lang_table(
    source: &HashMap<String, String>,
    lang_existing: &HashMap<String, Map<String, Value>>,
) -> HashMap<String, Map<String, Value>> {
    let mut result = HashMap::new();
    for (key, source_text) in source {
        result.insert(
            key.clone(),
            merge_lang_entry(Some(source_text), lang_existing.get(key)),
        );
    }
    for (key, entry) in lang_existing {
        if source.contains_key(key) {
            continue;
        }
        result.insert(key.clone(), merge_lang_entry(None, Some(entry)));
    }
    result
}

/// key 排序：`{id}.{field}`，先 id 数值升序，再字段序。
pub fn sorted_keys<'a>(
    keys: impl Iterator<Item = &'a String>,
    field_order: &[String],
) -> Vec<String> {
    let field_index: HashMap<&str, usize> = field_order
        .iter()
        .enumerate()
        .map(|(i, n)| (n.as_str(), i))
        .collect();
    let mut keys: Vec<String> = keys.cloned().collect();
    keys.sort_by(|a, b| {
        let key_of = |k: &str| {
            let (head, _, tail) = {
                let mut parts = k.splitn(2, '.');
                let head = parts.next().unwrap_or("");
                let tail = parts.next().unwrap_or("");
                (head, (), tail)
            };
            let id_part: (u8, u64, String) = match head.parse::<u64>() {
                Ok(n) => (0, n, String::new()),
                Err(_) => (1, 0, head.to_string()),
            };
            let rank = field_index.get(tail).copied().unwrap_or(field_order.len());
            (id_part, rank, tail.to_string())
        };
        key_of(a).cmp(&key_of(b))
    });
    keys
}

/// 紧凑 JSON：每个 key 一行，含结尾换行。
pub fn serialize_i18n_object(
    data: &HashMap<String, Map<String, Value>>,
    field_order: &[String],
) -> String {
    if data.is_empty() {
        return "{}\n".to_string();
    }
    let mut lines = vec!["{".to_string()];
    let keys = sorted_keys(data.keys(), field_order);
    for (i, key) in keys.iter().enumerate() {
        let key_str = serde_json::to_string(key).unwrap();
        // value 序列化：separators (", ", ": ")
        let value_str = serialize_spaced(&Value::Object(data[key].clone()));
        let suffix = if i < keys.len() - 1 { "," } else { "" };
        lines.push(format!("  {key_str}: {value_str}{suffix}"));
    }
    lines.push("}".to_string());
    lines.join("\n") + "\n"
}

/// source 文件（`{key: text}`）同格式。
pub fn serialize_source_object(data: &HashMap<String, String>, field_order: &[String]) -> String {
    if data.is_empty() {
        return "{}\n".to_string();
    }
    let mut lines = vec!["{".to_string()];
    let keys = sorted_keys(data.keys(), field_order);
    for (i, key) in keys.iter().enumerate() {
        let key_str = serde_json::to_string(key).unwrap();
        let value_str = serde_json::to_string(&data[key]).unwrap();
        let suffix = if i < keys.len() - 1 { "," } else { "" };
        lines.push(format!("  {key_str}: {value_str}{suffix}"));
    }
    lines.push("}".to_string());
    lines.join("\n") + "\n"
}

/// Python `json.dumps(value, separators=(", ", ": "))` 形态。
fn serialize_spaced(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let parts: Vec<String> = map
                .iter()
                .map(|(k, v)| {
                    format!(
                        "{}: {}",
                        serde_json::to_string(k).unwrap(),
                        serialize_spaced(v)
                    )
                })
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
        Value::Array(items) => {
            let parts: Vec<String> = items.iter().map(serialize_spaced).collect();
            format!("[{}]", parts.join(", "))
        }
        other => serde_json::to_string(other).unwrap(),
    }
}
