"""Enum token domain gate tests (task 4.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.app.canonical_commands import CanonicalValidationError, canonical_validate
from ct.app.canonical_workspace import CanonicalWorkspace
from _helpers import build_project, make_workbook


def _project(tmp_path: Path, *, vector: bool = False, record: bool = False) -> Path:
    fields = [{"name": "Id", "type": "int32"}]
    if vector:
        fields.append({"name": "Rarities", "type": "vector<ItemRarity>"})
    elif record:
        fields.append({"name": "Drop", "type": "DropReward"})
    else:
        fields.append({"name": "Rarity", "type": "ItemRarity"})
    types = [
        {
            "kind": "enum",
            "name": "ItemRarity",
            "values": [
                {"name": "Common", "comment": "普通"},
                {"name": "Rare", "comment": "稀有"},
            ],
        }
    ]
    if record:
        types.append(
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [{"name": "Rarity", "type": "ItemRarity"}],
            }
        )
    return build_project(
        tmp_path / "gd", schemas=[{"table": "Item", "primary": "Id", "fields": fields}], types=types
    )


def test_unknown_scalar_token_is_reported_with_location(tmp_path: Path) -> None:
    root = _project(tmp_path)
    make_workbook(root, "Item", [[1, "Legendary"]])
    issues = canonical_validate(root)
    assert len(issues) == 1
    issue = issues[0]
    assert "ItemRarity" in issue.message and "Legendary" in issue.message
    assert issue.excel_row == 3
    assert issue.field == "Rarity"


def test_declared_tokens_pass(tmp_path: Path) -> None:
    root = _project(tmp_path)
    make_workbook(root, "Item", [[1, "Common"], [2, "Rare"]])
    assert canonical_validate(root) == []


def test_blank_enum_cell_keeps_the_default_behaviour(tmp_path: Path) -> None:
    root = _project(tmp_path)
    make_workbook(root, "Item", [[1, None], [2, "Rare"]])
    assert canonical_validate(root) == []


def test_unknown_vector_element_is_reported(tmp_path: Path) -> None:
    root = _project(tmp_path, vector=True)
    make_workbook(root, "Item", [[1, "[Common,Legendary]"]])
    issues = canonical_validate(root)
    assert issues and "Legendary" in issues[0].message
    assert issues[0].field == "Rarities"


def test_unknown_record_leaf_token_is_reported(tmp_path: Path) -> None:
    root = _project(tmp_path, record=True)
    # 嵌套 Record 的 Enum 叶子：列顺序为 Id, Drop/Rarity
    make_workbook(root, "Item", [[1, "Nope"]])
    issues = canonical_validate(root)
    assert issues and "Nope" in issues[0].message
    assert issues[0].field == "Drop.Rarity"


def test_export_fails_without_artifacts(tmp_path: Path) -> None:
    from ct.app.exporting.models import ExportRequest
    from ct.app.exporting.service import run_export

    root = _project(tmp_path)
    make_workbook(root, "Item", [[1, "Legendary"]])
    with pytest.raises(CanonicalValidationError):
        run_export(ExportRequest(root=root, forced=True))
    assert not (root / "output").exists() or not any((root / "output").rglob("*.json"))


def test_removed_enum_item_is_caught_after_schema_save(tmp_path: Path) -> None:
    """删掉仍被数据引用的 Enum item：保存照常，读取闸门拦下。"""
    from ct.schema.resource_repository import dump_yaml
    from ct.schema.resources import EnumResource, resource_to_data
    import yaml

    root = _project(tmp_path)
    make_workbook(root, "Item", [[1, "Rare"]])
    assert canonical_validate(root) == []

    path = root / "config" / "types" / "ItemRarity.yaml"
    path.write_text(
        dump_yaml(
            resource_to_data(
                EnumResource.model_validate(
                    {
                        "kind": "enum",
                        "name": "ItemRarity",
                        "values": [{"name": "Common", "comment": "普通"}],
                    }
                )
            )
        ),
        encoding="utf-8",
    )
    issues = canonical_validate(root)
    assert issues and "Rare" in issues[0].message


def test_binary_serializer_refuses_unknown_tokens(tmp_path: Path) -> None:
    """即使绕过数据闸门，serializer 也不得把未知 token 静默写成 ordinal 0。"""
    from ct.export.canonical_binary import build_canonical_table_bytes
    from ct.schema.resources import EnumResource, TableResource

    enum = EnumResource.model_validate(
        {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": ""}]}
    )
    table = TableResource.model_validate(
        {
            "table": "Item",
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "Rarity", "type": "ItemRarity"},
            ],
        }
    )
    with pytest.raises(ValueError):
        build_canonical_table_bytes(
            [{"Id": 1, "Rarity": "Unknown"}], table, records={}, enums={"ItemRarity": enum}
        )
    # 空格子仍沿用默认值（ordinal 0），不算未知 token
    assert build_canonical_table_bytes(
        [{"Id": 1, "Rarity": ""}], table, records={}, enums={"ItemRarity": enum}
    )
