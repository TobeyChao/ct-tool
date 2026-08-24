"""SchemaRepository 测试：YAML 加载 + fbs_sources golden 文本。"""

from __future__ import annotations

from pathlib import Path

import yaml

from ct.schema.models import TableSchema
from ct.schema.repository import YamlSchemaRepository, create_repository


def _item_schema() -> TableSchema:
    data = {
        "table": "Item",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string", "i18n": True},
            {"name": "Price", "type": "float"},
            {"name": "Rarity", "type": "enum", "values": ["common", "rare", "epic"]},
            {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
            {
                "name": "DropRange",
                "type": "struct",
                "fields": [
                    {"name": "Min", "type": "int32"},
                    {"name": "Max", "type": "int32"},
                ],
            },
            {"name": "Tags", "type": "array", "element": "int32", "separator": ","},
            {"name": "IsActive", "type": "bool", "server_only": True},
        ],
    }
    return TableSchema(**data)


_EXPECTED_MAIN = """\
enum RarityEnum : byte { common = 0, rare = 1, epic = 2 }

table DropRangeStruct {
  Min: int32;
  Max: int32;
}

table Item {
  Id: int32;
  Name: string;
  Price: float32;
  Rarity: RarityEnum;
  ItemTypeId: int32;
  DropRange: DropRangeStruct;
  Tags: [int32];
}

struct IndexEntry {
  id: int32;
  row: int32;
}

table ItemTable {
  items: [Item];
  index: [IndexEntry];
}

root_type ItemTable;
"""


_EXPECTED_I18N = """\
table ItemI18nEntry {
  Id: int32;
  Name: string;
}

table ItemI18nTable {
  entries: [ItemI18nEntry];
}

root_type ItemI18nTable;
"""


def test_fbs_sources_matches_legacy_generator_text(tmp_path: Path) -> None:
    """fbs_sources 产物与旧 fbs_generator 逐字一致（golden test）。"""
    schema = _item_schema()
    repo = YamlSchemaRepository(tmp_path)

    sources = repo.fbs_sources([schema])

    assert sources["Item"]["main"] == _EXPECTED_MAIN
    assert sources["Item"]["i18n"] == _EXPECTED_I18N


def test_fbs_sources_skips_i18n_when_no_i18n_fields(tmp_path: Path) -> None:
    schema = TableSchema(
        table="Monster",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Hp", "type": "int32"},
        ],
    )
    sources = YamlSchemaRepository(tmp_path).fbs_sources([schema])
    assert sources["Monster"]["i18n"] is None
    assert "Hp: int32;" in sources["Monster"]["main"]


def test_yaml_repository_load_all(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    (schemas_dir / "Item.yaml").write_text(
        yaml.safe_dump(_item_schema().model_dump()), encoding="utf-8"
    )

    repo = create_repository(schemas_dir, "yaml")
    schemas = repo.load_all()

    assert [s.table for s in schemas] == ["Item"]


def test_create_repository_rejects_unknown_format(tmp_path: Path) -> None:
    import pytest

    from ct.schema.repository import create_repository

    with pytest.raises(NotImplementedError):
        create_repository(tmp_path, "fbs")
