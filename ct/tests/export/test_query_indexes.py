"""Table-level query index model and exact-string lookup tests (5.5/5.7/5.8)."""

from __future__ import annotations

import pytest

from ct.export.index_query import StringIndex, production_hash, validate_code_index
from ct.schema.indexes import QueryIndex, parse_indexes, validate_indexes
from ct.schema.resources import FieldDef, TableResource


def _table() -> TableResource:
    return TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
            FieldDef(name="Category", type="int32"),
            FieldDef(name="DisplayName", type="string", i18n=True),
            FieldDef(name="Rarity", type="enum:ItemRarity"),
        ],
    )


def test_parse_indexes_max_one_per_kind() -> None:
    # codename 不写 field（固定指向 CodeName）；显式写 CodeName 也接受（幂等）
    assert parse_indexes([{"kind": "codename"}]) == (QueryIndex(kind="codename"),)
    assert parse_indexes([{"kind": "codename", "field": "CodeName"}]) == (
        QueryIndex(kind="codename"),
    )
    assert parse_indexes([{"kind": "group", "field": "Category"}]) == (
        QueryIndex(kind="group", field="Category"),
    )
    with pytest.raises(ValueError, match="最多一个 codename"):
        parse_indexes([{"kind": "codename"}, {"kind": "codename"}])
    # 旧的 kind: code 一律拒绝（不给兼容别名，避免两套名字并存）
    with pytest.raises(ValueError, match="codename"):
        parse_indexes([{"kind": "code", "field": "CodeName"}])


def test_codename_requires_fixed_named_non_i18n_string_field() -> None:
    """codename 索引**固定**指向名为 ``CodeName`` 的 string 字段 —— 不是「随便指一个 string 字段」。

    所以「指错字段」这类错误现在分成两处：
    - 构造期：写了别的字段名 ⇒ QueryIndex 直接拒绝；
    - 校验期：表里没有 CodeName / 类型不是 string / 带 i18n ⇒ validate_indexes 拒绝。
    """
    table = _table()
    validate_indexes(table, (QueryIndex(kind="codename"),))

    with pytest.raises(ValueError, match="固定指向 CodeName"):
        QueryIndex(kind="codename", field="DisplayName")

    no_field = TableResource(
        table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]
    )
    with pytest.raises(ValueError, match="名为 CodeName 的字段"):
        validate_indexes(no_field, (QueryIndex(kind="codename"),))

    wrong_type = TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="CodeName", type="int32")],
    )
    with pytest.raises(ValueError, match="非 i18n 的 string"):
        validate_indexes(wrong_type, (QueryIndex(kind="codename"),))

    i18n_field = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string", i18n=True),
        ],
    )
    with pytest.raises(ValueError, match="i18n"):
        validate_indexes(i18n_field, (QueryIndex(kind="codename"),))


def test_validate_group_allows_scalar_and_enum_rejects_i18n_and_vector() -> None:
    table = _table()
    validate_indexes(table, (QueryIndex(kind="group", field="Category"),))
    validate_indexes(table, (QueryIndex(kind="group", field="Rarity"),))
    with pytest.raises(ValueError, match="i18n"):
        validate_indexes(table, (QueryIndex(kind="group", field="DisplayName"),))
    vector_table = table.model_copy(
        update={
            "fields": [
                *table.fields,
                FieldDef(name="Tags", type="vector<int32>"),
            ]
        }
    )
    with pytest.raises(ValueError, match="vector"):
        validate_indexes(vector_table, (QueryIndex(kind="group", field="Tags"),))


def _collision_hash(text: str) -> int:
    """Injectable hash: all strings share one bucket (adversarial)."""
    return 42


def test_hash_collision_returns_only_exact_match() -> None:
    rows = [
        {"Id": 1, "CodeName": "Sword"},
        {"Id": 2, "CodeName": "sWord"},
        {"Id": 3, "CodeName": "Ｓword"},
    ]
    index = StringIndex.build(rows, "CodeName", hash_provider=_collision_hash)
    assert index.lookup("Sword") == [0]
    assert index.lookup("sWord") == [1]
    assert index.lookup("missing") == []
    # visually related but distinct strings never merge
    assert index.lookup("Sword") != index.lookup("sWord")


def test_hash_is_case_sensitive_and_exact() -> None:
    assert production_hash("Code") != production_hash("code")
    assert production_hash("Ａ") != production_hash("A")  # full-width distinct


def test_code_duplicate_validation_reports_exact_rows() -> None:
    rows = [
        {"Id": 1, "CodeName": "Sword"},
        {"Id": 2, "CodeName": "Sword"},
        {"Id": 3, "CodeName": "Shield"},
    ]
    duplicates = validate_code_index(rows, QueryIndex(kind="codename"))
    assert (1, "Sword") in duplicates


def test_normal_bucket_query_is_bucket_local() -> None:
    rows = [{"Id": i, "CodeName": f"V{i}"} for i in range(1000)]
    index = StringIndex.build(rows, "CodeName")
    hit = production_hash("V500")
    # a normal hash produces a ~1-candidate bucket; lookup touches only it
    assert len(index.buckets[hit]) == 1
    assert index.lookup("V500") == [500]
    assert index.lookup("missing") == []


def test_group_repeats_allowed_and_query_returns_all() -> None:
    rows = [
        {"Id": 1, "Category": 1},
        {"Id": 2, "Category": 2},
        {"Id": 3, "Category": 1},
        {"Id": 4, "Category": 3},
    ]
    index = StringIndex.build(rows, "Category")
    assert index.lookup("1") == [0, 2]
    assert index.lookup("3") == [3]


# ---------------------------------------------------------------------------
# 索引的持久化闭环：schema → YAML → 仓库加载 → 导出器
#
# 修复前索引只存在于编辑器草稿字典里，落盘时被丢弃（stage_candidate_yaml 只写
# resources），所以编辑器里设的索引从来没到达 YAML/导出器。
# ---------------------------------------------------------------------------


def test_indexes_round_trip_through_yaml(tmp_path) -> None:
    from ct.schema.resource_repository import dump_yaml, YamlResourceRepository
    from ct.schema.resources import FieldDef, TableResource, resource_to_data

    table = TableResource(
        table="Item",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="CodeName", type="string"),
        ],
        indexes=(QueryIndex(kind="codename"),),
    )
    schemas = tmp_path / "config" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "Item.yaml").write_text(dump_yaml(resource_to_data(table)), encoding="utf-8")

    loaded = YamlResourceRepository(schemas, tmp_path / "config" / "types").load()
    assert len(loaded.tables) == 1
    assert loaded.tables[0].indexes == (QueryIndex(kind="codename"),)


def test_table_without_indexes_writes_no_indexes_key(tmp_path) -> None:
    """没声明索引的表，YAML 里不应出现 indexes 空键（保持产物干净、diff 稳定）。"""
    from ct.schema.resources import FieldDef, TableResource, resource_to_data

    table = TableResource(
        table="Item", primary="Id", fields=[FieldDef(name="Id", type="int32")]
    )
    assert "indexes" not in resource_to_data(table)


def test_merge_indexes_attaches_draft_indexes_to_resources() -> None:
    """编辑器草稿字典 → 资源：这是索引能被持久化的关键一步。"""
    from ct.app.schema_workspace.candidate import merge_indexes
    from ct.schema.resources import FieldDef, TableResource

    table = TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32"), FieldDef(name="CodeName", type="string")],
    )
    merged = merge_indexes((table,), {"table:Item": (QueryIndex(kind="codename"),)})
    assert merged[0].indexes == (QueryIndex(kind="codename"),)
    # 不在草稿里的表保持无索引
    other = TableResource(table="Other", primary="Id", fields=[FieldDef(name="Id", type="int32")])
    assert merge_indexes((other,), {})[0].indexes == ()


def test_workspace_validates_indexes_on_load(tmp_path) -> None:
    """字段/类型不合法时**加载期**就报错，不要等到导出。"""
    import pytest

    from ct.schema.resource_repository import dump_yaml
    from ct.schema.resources import FieldDef, TableResource, resource_to_data
    from ct.app.canonical_workspace import CanonicalWorkspace

    (tmp_path / "config" / "schemas").mkdir(parents=True)
    (tmp_path / "config" / "global.yaml").write_text(
        "primary_lang: zh\nschemas_dir: config/schemas\nexcel_dir: excel\n"
        "output_dir: output\ncache_dir: cache\ni18n_dir: i18n\n",
        encoding="utf-8",
    )
    bad = TableResource(
        table="Item",
        primary="Id",
        fields=[FieldDef(name="Id", type="int32")],
        indexes=(QueryIndex(kind="codename"),),
    )
    (tmp_path / "config" / "schemas" / "Item.yaml").write_text(
        dump_yaml(resource_to_data(bad)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="名为 CodeName 的字段"):
        CanonicalWorkspace.load(tmp_path)
