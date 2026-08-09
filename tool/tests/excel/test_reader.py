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
