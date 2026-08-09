"""reader 测试：ParsedRows 保留 Excel 绝对行号。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from ct.excel.reader import read_excel
from ct.schema.models import TableSchema


def _write_workbook(path: Path, rows: list[tuple]) -> None:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(list(row))
    wb.save(path)


def test_excel_rows_preserve_absolute_row_across_blank_lines(tmp_path: Path) -> None:
    """空行被跳过，但 excel_rows 记录真实 Excel 行号。"""
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string"},
        ],
    )
    xlsx = tmp_path / "item.xlsx"
    # 2 行表头，数据在第 3、4 行，第 5 行空，第 6 行数据
    _write_workbook(
        xlsx,
        [
            ("id", "name"),
            ("主键", "名称"),
            (1, "铁剑"),
            (2, "木剑"),
            (None, None),
            (3, "石剑"),
        ],
    )

    parsed = read_excel(xlsx, schema)

    assert [r["Id"] for r in parsed.rows] == [1, 2, 3]
    assert parsed.excel_rows == [3, 4, 6]


def test_reader_emits_issues_on_coercion_failure(tmp_path: Path) -> None:
    """coerce 失败显式产出带行列定位的 issue（不再靠下游猜"返回原值"）。"""
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Price", "type": "float"},
            {"name": "Name", "type": "string"},
        ],
    )
    xlsx = tmp_path / "item.xlsx"
    _write_workbook(
        xlsx,
        [
            ("id", "price", "name"),
            ("主键", "价格", "名称"),
            (1, "abc", "铁剑"),
            ("xyz", 2.0, "坏行"),
        ],
    )

    parsed = read_excel(xlsx, schema)

    # 失败值保持原值（与旧 reader 一致），同时显式标记失败。
    assert parsed.rows[0]["Price"] == "abc"
    assert parsed.rows[1]["Id"] == "xyz"
    issues = parsed.issues
    assert len(issues) == 2

    price = next(i for i in issues if i.field == "Price")
    assert price.excel_row == 3
    assert price.column == 1
    assert price.value == "abc"
    assert price.row_index == 1
    assert "期望数值类型" in price.message

    pk = next(i for i in issues if i.field == "Id")
    assert pk.excel_row == 4
    assert pk.column == 0
    assert pk.value == "xyz"
    assert pk.row_index == 2
    assert "期望整数类型" in pk.message


def test_reader_issues_are_empty_when_all_coerce_succeeds(tmp_path: Path) -> None:
    schema = TableSchema(
        table="Item",
        primary="Id",
        fields=[
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string"},
        ],
    )
    xlsx = tmp_path / "item.xlsx"
    _write_workbook(
        xlsx,
        [
            ("id", "name"),
            ("主键", "名称"),
            (1, "铁剑"),
            (2, "木剑"),
        ],
    )
    parsed = read_excel(xlsx, schema)
    assert parsed.issues == []
