//! 命名规则（`ct/schema/naming.py`）：WYSIWYG PascalCase 恒等域。

use unicode_ident::{is_xid_continue, is_xid_start};

fn is_identifier(name: &str) -> bool {
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (is_xid_start(first) || first == '_') && chars.all(|c| is_xid_continue(c) || c == '_')
}

/// 校验命名：合法标识符、首字符大写、不以 `_` 开头/结尾。
/// 合规返回 `None`，违规返回错误信息。
pub fn validate_name(name: &str) -> Option<String> {
    if name.is_empty() {
        return Some("名字为空".to_string());
    }
    if !is_identifier(name) {
        return Some(format!("'{name}' 不是合法标识符"));
    }
    if name.starts_with('_') || name.ends_with('_') {
        return Some(format!("'{name}' 不能以 _ 开头或结尾"));
    }
    if !name.chars().next().unwrap().is_uppercase() {
        return Some(format!(
            "'{name}' 首字符必须大写（PascalCase，保证 flatc 恒等）"
        ));
    }
    None
}

/// `validate_name` 的校验版本。
pub fn require_valid_name(name: &str, label: &str) -> Result<(), String> {
    match validate_name(name) {
        Some(error) => Err(format!("{label} {name}: {error}")),
        None => Ok(()),
    }
}
