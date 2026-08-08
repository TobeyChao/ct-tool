from __future__ import annotations


def validate_name(name: str) -> str | None:
    """校验命名符合 WYSIWYG 约定（flatc 恒等域）。

    Schema 名原样进入 FBS / Accessor 代码，不再做大小写转换。为保证
    flatc 对名字的变换是恒等（无下划线名原样透传、snake_case 名标准
    转换），名字必须满足：

    - 合法标识符
    - 首字符大写（PascalCase 形态）
    - 不以 ``_`` 开头或结尾

    合规返回 ``None``，违规返回错误信息。
    """
    if not name:
        return "名字为空"
    if not name.isidentifier():
        return f"'{name}' 不是合法标识符"
    if name.startswith("_") or name.endswith("_"):
        return f"'{name}' 不能以 _ 开头或结尾"
    if not name[0].isupper():
        return f"'{name}' 首字符必须大写（PascalCase，保证 flatc 恒等）"
    return None
