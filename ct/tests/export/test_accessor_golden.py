"""C# / Lua 访问器生成器 golden 特征测试。

固定两个样例 schema 断言生成文本逐字一致，保证重构零漂移。生成器输出
文本较长，快照存 `tests/fixtures/accessor/`。

重新生成快照：见本文件底部注释。
"""

from __future__ import annotations

from pathlib import Path

from ct.export.csharp_accessor_generator import generate_csharp_accessor
from ct.export.lua_accessor_generator import generate_lua_accessor
from ct.schema.models import FieldDef, TableSchema


def schema_a() -> TableSchema:
    """样例 A：i18n string + enum + array<int32> + server_only。"""
    return TableSchema(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Name", type="string", i18n=True),
            FieldDef(name="Rarity", type="enum", values=["common", "rare", "epic"]),
            FieldDef(name="Tags", type="array", element="int32", separator=","),
            FieldDef(name="ServerSecret", type="int32", server_only=True),
        ],
    )


def schema_b() -> TableSchema:
    """样例 B：struct（int32 / string 子字段）+ 普通标量。"""
    return TableSchema(
        table="Quest",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(
                name="DropRange",
                type="struct",
                fields=[
                    FieldDef(name="Min", type="int32"),
                    FieldDef(name="Max", type="string"),
                ],
            ),
            FieldDef(name="Ratio", type="float"),
            FieldDef(name="Big", type="int64"),
            FieldDef(name="Active", type="bool"),
            FieldDef(name="Precise", type="double"),
        ],
    )


def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "fixtures" / "accessor"


def _generate(tmp_path: Path, schema: TableSchema) -> tuple[str, str]:
    cs_path = generate_csharp_accessor(schema, tmp_path / "cs")
    lua_path = generate_lua_accessor(schema, tmp_path / "lua")
    return cs_path.read_text(encoding="utf-8"), lua_path.read_text(encoding="utf-8")


def _assert_golden(tmp_path: Path, schema: TableSchema, name: str) -> None:
    cs_text, lua_text = _generate(tmp_path, schema)
    assert cs_text == (_fixtures_dir() / f"{name}Accessor.cs.golden").read_text(
        encoding="utf-8"
    )
    assert lua_text == (_fixtures_dir() / f"{name}Accessor.lua.golden").read_text(
        encoding="utf-8"
    )


def test_csharp_and_lua_golden_a(tmp_path: Path) -> None:
    _assert_golden(tmp_path, schema_a(), "Item")


def test_csharp_and_lua_golden_b(tmp_path: Path) -> None:
    _assert_golden(tmp_path, schema_b(), "Quest")


"""
重新生成快照（cd tool）：

    .venv/bin/python -c "
from pathlib import Path
from tempfile import TemporaryDirectory
from tests.export.test_accessor_golden import schema_a, schema_b, _fixtures_dir
from ct.export.csharp_accessor_generator import generate_csharp_accessor
from ct.export.lua_accessor_generator import generate_lua_accessor

out = _fixtures_dir()
out.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory() as td:
    for schema, name in ((schema_a(), 'Item'), (schema_b(), 'Quest')):
        cs = generate_csharp_accessor(schema, Path(td))
        lua = generate_lua_accessor(schema, Path(td))
        (out / f'{name}Accessor.cs.golden').write_text(cs.read_text(), encoding='utf-8')
        (out / f'{name}Accessor.lua.golden').write_text(lua.read_text(), encoding='utf-8')
"
"""
