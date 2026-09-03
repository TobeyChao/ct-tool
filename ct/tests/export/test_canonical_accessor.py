"""Canonical C#/Lua accessor + Code/Group API tests (5.4/5.6)."""

from __future__ import annotations

from ct.export.canonical_accessor import golden_csharp, golden_lua
from ct.export.canonical_accessor_model import build_accessor_model
from ct.schema.indexes import QueryIndex
from ct.schema.resources import FieldDef, TableResource


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
            FieldDef(name="Note", type="string", i18n=True),
            FieldDef(name="Secret", type="int32", server_only=True),
        ],
    )


def test_accessor_model_shared_shape() -> None:
    model = build_accessor_model(
        _table(),
        (QueryIndex("code", "CodeName"), QueryIndex("group", "Category")),
    )
    assert [field.name for field in model.client_fields] == [
        "Id", "CodeName", "Category", "Note",
    ]
    assert model.primary.slot == 0
    assert model.indexes[0].kind == "code"
    assert model.indexes[0].field == "CodeName"
    assert model.indexes[0].slot == 1
    assert model.has_i18n is True


def test_csharp_exposes_bycode_and_bygroupkey() -> None:
    text = golden_csharp()
    assert "public static ItemRow? ByCode(string code)" in text
    assert "ByGroupKey(int value)" in text
    assert "WireReader.LookupCode" in text
    assert "WireReader.LookupGroup" in text
    assert "CodeName" in text
    assert "Secret" not in text  # server_only excluded


def test_lua_exposes_bycode_and_bygroupkey() -> None:
    text = golden_lua()
    assert "function M.ByCode(code)" in text
    assert "function M.ByGroupKey(value)" in text
    assert "GD.IndexCode" in text
    assert "GD.IndexGroup" in text
    assert "Secret" not in text


def test_generation_is_deterministic() -> None:
    assert golden_csharp() == golden_csharp()
    assert golden_lua() == golden_lua()


def test_no_indexes_still_emits_row_api() -> None:
    csharp = golden_csharp(indexes=())
    lua = golden_lua(indexes=())
    assert "ByCode" not in csharp
    assert "ByGroupKey" not in csharp
    assert "function M.ByCode" not in lua
    assert "ByID" in lua
