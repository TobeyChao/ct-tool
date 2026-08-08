from ct.schema.naming import validate_name


def test_compliant_names() -> None:
    """合规名（flatc 恒等域内）应通过校验。"""
    for name in ("UIConfig", "ItemTypeId", "DropRange", "Id", "I18nKey", "BlocksRaycast"):
        assert validate_name(name) is None, f"{name} 应合规"


def test_leading_underscore_rejected() -> None:
    assert validate_name("_private") is not None


def test_trailing_underscore_rejected() -> None:
    assert validate_name("id_") is not None


def test_lowercase_initial_rejected() -> None:
    assert validate_name("uiconfig") is not None
    assert validate_name("item_type_id") is not None


def test_non_identifier_rejected() -> None:
    assert validate_name("my-field") is not None
    assert validate_name("item type") is not None


def test_empty_rejected() -> None:
    assert validate_name("") is not None


def test_error_messages_are_actionable() -> None:
    err = validate_name("uiconfig")
    assert err is not None and "首字符必须大写" in err
    err = validate_name("_private")
    assert err is not None and "以 _ 开头或结尾" in err
