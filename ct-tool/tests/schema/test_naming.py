from ct.schema.naming import to_pascal_case


def test_simple_snake_case() -> None:
    assert to_pascal_case("drop_range") == "DropRange"


def test_single_letter() -> None:
    assert to_pascal_case("a") == "A"


def test_multi_segment() -> None:
    assert to_pascal_case("hello_world_foo") == "HelloWorldFoo"


def test_empty_string() -> None:
    assert to_pascal_case("") == ""


def test_already_lowercase_word() -> None:
    assert to_pascal_case("item") == "Item"


def test_uppercase_input_normalized() -> None:
    assert to_pascal_case("ITEM_TYPE") == "ItemType"
