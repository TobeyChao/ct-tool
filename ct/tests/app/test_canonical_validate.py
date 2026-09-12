"""canonical  校验闸门：跨表 ref 外键校验 + 导出中止。"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_commands import CanonicalValidationError, canonical_validate
from ct.app.canonical_export import run_canonical_export
from ct.excel.canonical_reader import CanonicalParsedRows
from ct.schema.resources import TableResource


def _quest_table() -> TableResource:
    return TableResource.model_validate(
        {
            "table": "Quest",
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
            ],
        }
    )


def _write_excel(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    # two header rows (max_nesting_depth + 1 = 2) + data rows
    ws.append(["id", "type_id"])
    ws.append(["主键", "类型"])
    for row in rows:
        ws.append(row)
    wb.save(str(path))


def _workspace_with_dangling_ref(tmp_path: Path) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {"table": "ItemType", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
            {"table": "Quest", "primary": "Id", "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
            ]},
        ],
    )
    (root / "excel").mkdir(parents=True, exist_ok=True)
    _write_excel(root / "excel" / "ItemType.xlsx", [[1], [2]])
    _write_excel(root / "excel" / "Quest.xlsx", [[1, 1], [2, 99]])  # 99 dangling
    return root


def test_ref_issues_detect_dangling_and_pass_valid() -> None:
    table = _quest_table()
    parsed = CanonicalParsedRows(
        rows=[{"Id": 1, "ItemTypeId": 100}, {"Id": 2, "ItemTypeId": 2}],
        excel_rows=[3, 4],
    )
    from ct.app.canonical_commands import _ref_issues

    issues = _ref_issues(table, parsed, {"ItemType": {1, 2}})
    assert len(issues) == 1
    issue = issues[0]
    assert issue.code.value == "ref"
    assert "ItemType.Id 中不存在" in issue.message
    assert issue.excel_row == 3


def test_canonical_validate_reports_dangling_ref(tmp_path: Path) -> None:
    root = _workspace_with_dangling_ref(tmp_path)
    issues = canonical_validate(root)
    ref_issues = [i for i in issues if i.code.value == "ref"]
    assert len(ref_issues) == 1
    assert "ItemType.Id 中不存在" in ref_issues[0].message


def test_canonical_export_aborts_on_dangling_ref(tmp_path: Path) -> None:
    root = _workspace_with_dangling_ref(tmp_path)
    with pytest.raises(CanonicalValidationError) as excinfo:
        run_canonical_export(root)
    codes = {i.code.value for i in excinfo.value.issues}
    assert "ref" in codes
    # 不应产出任何产物
    assert not (root / "output" / "json").exists() or not any(
        (root / "output" / "json").glob("*.json")
    )


# ---------------------------------------------------------------------------
# CodeName 索引的数据闸门（声明了 codename 索引的表：每行必须非空且唯一）
# ---------------------------------------------------------------------------


def _codename_table(indexed: bool = True) -> TableResource:
    data = {
        "table": "ItemType",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "CodeName", "type": "string"},
        ],
    }
    if indexed:
        data["indexes"] = [{"kind": "codename"}]
    return TableResource.model_validate(data)


def _parsed(rows: list[dict], excel_rows: list[int]) -> CanonicalParsedRows:
    return CanonicalParsedRows(rows=rows, excel_rows=excel_rows)


def test_codename_issues_reject_blank_and_duplicate() -> None:
    """空 CodeName 与重复 CodeName 都要报，且带 Excel 定位。"""
    from ct.app.canonical_commands import _codename_issues

    issues = _codename_issues(
        _codename_table(),
        _parsed(
            [
                {"Id": 1, "CodeName": "sword"},
                {"Id": 2, "CodeName": "sword"},   # 重复
                {"Id": 3, "CodeName": ""},        # 空
                {"Id": 4, "CodeName": "shield"},
                {"Id": 5},                        # 字段整个缺失 = 空
            ],
            [3, 4, 5, 6, 7],
        ),
    )
    assert [(i.code.value, i.row_index, i.excel_row) for i in issues] == [
        ("duplicate_codename", 2, 4),
        ("type", 3, 5),
        ("type", 5, 7),
    ]
    assert "首次出现在第 1 行" in issues[0].message
    assert "永远查不到" in issues[1].message


def test_codename_issues_ignore_tables_without_the_index() -> None:
    """没声明索引的表里 CodeName 只是普通字段 —— 不该被这道闸门拦。"""
    from ct.app.canonical_commands import _codename_issues

    assert _codename_issues(
        _codename_table(indexed=False),
        _parsed([{"Id": 1, "CodeName": ""}, {"Id": 2, "CodeName": "same"},
                 {"Id": 3, "CodeName": "same"}], [3, 4, 5]),
    ) == []


def _workspace_with_codename(tmp_path: Path, rows: list[list]) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "ItemType",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "CodeName", "type": "string"},
                ],
                "indexes": [{"kind": "codename"}],
            }
        ],
    )
    (root / "excel").mkdir(parents=True, exist_ok=True)
    _write_excel(root / "excel" / "ItemType.xlsx", rows)
    return root


def test_canonical_export_aborts_on_duplicate_codename(tmp_path: Path) -> None:
    """端到端：重复 CodeName 必须让导出**中止**，而不是静默少一行。

    修复前：导出不报错，桶表里两行都在，但运行期 `ByCodeName()` 只命中探测序更靠前的
    那一行 —— 另一行永远查不到且毫无提示。
    """
    root = _workspace_with_codename(tmp_path, [[1, "sword"], [2, "sword"], [3, "shield"]])
    with pytest.raises(CanonicalValidationError) as excinfo:
        run_canonical_export(root)
    assert [i.code.value for i in excinfo.value.issues] == ["duplicate_codename"]
    # 校验失败不落产物（与重复主键/悬空 ref 同一条承诺）
    assert not (root / "output" / "json").exists() or not any(
        (root / "output" / "json").glob("*.json")
    )


def test_canonical_export_aborts_on_blank_codename(tmp_path: Path) -> None:
    root = _workspace_with_codename(tmp_path, [[1, "sword"], [2, None], [3, "shield"]])
    with pytest.raises(CanonicalValidationError) as excinfo:
        run_canonical_export(root)
    assert [i.code.value for i in excinfo.value.issues] == ["type"]


def test_canonical_validate_reports_duplicate_codename(tmp_path: Path) -> None:
    """`ct validate` 也要拦（它是导出之前的独立入口）。"""
    root = _workspace_with_codename(tmp_path, [[1, "sword"], [2, "sword"]])
    issues = canonical_validate(root)
    assert [i.code.value for i in issues if "codename" in i.code.value] == [
        "duplicate_codename"
    ]


def test_unique_codename_exports_clean(tmp_path: Path) -> None:
    """负向对照：唯一且非空时必须导出成功（证明上面的失败不是「一律报错」）。"""
    root = _workspace_with_codename(tmp_path, [[1, "sword"], [2, "shield"]])
    result = run_canonical_export(root)
    assert result is not None
    assert any((root / "output" / "json").glob("*.json"))
