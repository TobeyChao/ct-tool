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
