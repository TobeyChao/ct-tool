"""`build_table_bytes` 逐字节 golden 测试。

快照依赖 flatbuffers 库的字节布局：升级 flatbuffers 后如漂移，需重新生成
fixture（见文件底部注释）。
"""

from __future__ import annotations

from pathlib import Path

from ct.export.binary_writer import build_table_bytes
from ct.schema.models import FieldDef, TableSchema


GOLDEN_SCHEMA = TableSchema(
    table="Item",
    primary="Id",
    fields=[
        FieldDef(name="Id", type="int32"),
        FieldDef(name="Name", type="string"),
        FieldDef(name="Rarity", type="enum", values=["common", "rare", "epic"]),
        FieldDef(name="Tags", type="array", element="int32", separator=","),
        FieldDef(name="Ratio", type="float"),
        FieldDef(name="Big", type="int64"),
        FieldDef(name="Active", type="bool"),
        FieldDef(name="Precise", type="double"),
        FieldDef(
            name="DropRange",
            type="struct",
            fields=[
                FieldDef(name="Min", type="int32"),
                FieldDef(name="Max", type="int32"),
            ],
        ),
        FieldDef(name="ServerSecret", type="int32", server_only=True),
    ],
)


GOLDEN_ROWS = [
    {
        "Id": 1,
        "Name": "铁剑",
        "Rarity": "rare",
        "Tags": [1, 2, 3],
        "Ratio": 1.5,
        "Big": 9007199254740993,
        "Active": True,
        "Precise": 0.25,
        "DropRange": {"Min": 1, "Max": 5},
        "ServerSecret": 42,
    },
    {
        "Id": 2,
        "Name": "魔杖",
        "Rarity": "epic",
        "Tags": [],
        "Ratio": 0.0,
        "Big": 0,
        "Active": False,
        "Precise": -1.5,
        "DropRange": {"Min": 0, "Max": 1},
        "ServerSecret": 7,
    },
]


def _golden_path() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "binary_golden.bin"


def test_build_table_bytes_matches_golden() -> None:
    data = build_table_bytes(GOLDEN_ROWS, GOLDEN_SCHEMA, exclude_server_only=True)
    assert data == _golden_path().read_bytes()


def test_server_only_fields_are_excluded() -> None:
    with_excluded = build_table_bytes(GOLDEN_ROWS, GOLDEN_SCHEMA, exclude_server_only=True)
    without_excluded = build_table_bytes(GOLDEN_ROWS, GOLDEN_SCHEMA, exclude_server_only=False)
    assert with_excluded != without_excluded


"""
重新生成 fixture：

    cd tool && .venv/bin/python -c "
from pathlib import Path
from tests.export.test_binary_golden import GOLDEN_SCHEMA, GOLDEN_ROWS
from ct.export.binary_writer import build_table_bytes
data = build_table_bytes(GOLDEN_ROWS, GOLDEN_SCHEMA, exclude_server_only=True)
Path('tests/fixtures/binary_golden.bin').write_bytes(data)
"
"""
