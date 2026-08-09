"""FbsConvention 检查器测试：撞名不变量 + 结构规范 + flatc 降级。"""

from __future__ import annotations

from pathlib import Path

from ct.schema.conventions import validate_fbs_conventions


_VALID_MAIN = """\
enum RarityEnum : byte { common = 0, rare = 1 }

table Item {
  Rarity: RarityEnum;
}

table ItemTable {
  items: [Item];
}

root_type ItemTable;
"""


def test_generated_shape_passes_structure_check() -> None:
    issues = validate_fbs_conventions(_VALID_MAIN, table="Item")
    assert issues == []


def test_field_type_name_collision_is_rejected() -> None:
    text = """\
enum Rarity : byte { common = 0 }

table Item {
  Rarity: Rarity;
}

table ItemTable {
  items: [Item];
}

root_type ItemTable;
"""
    issues = validate_fbs_conventions(text, table="Item")
    assert any("类型名与字段名冲突" in i.message for i in issues)


def test_explicit_type_name_without_collision_passes() -> None:
    text = """\
enum RarityType : byte { common = 0 }

table Item {
  Rarity: RarityType;
}

table ItemTable {
  items: [Item];
}

root_type ItemTable;
"""
    issues = validate_fbs_conventions(text, table="Item")
    assert not any("类型名与字段名冲突" in i.message for i in issues)


def test_missing_root_type_is_rejected() -> None:
    text = """\
table Item {
  Id: int32;
}

table ItemTable {
  items: [Item];
}
"""
    issues = validate_fbs_conventions(text, table="Item")
    assert any("root_type" in i.message for i in issues)


def test_missing_flatc_degrades_to_structure_only(tmp_path: Path) -> None:
    missing = tmp_path / "no-flatc"
    issues = validate_fbs_conventions(
        _VALID_MAIN, table="Item", flatc_path=missing
    )
    assert any("跳过编译校验" in i.message for i in issues)
