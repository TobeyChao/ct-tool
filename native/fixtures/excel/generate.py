"""生成 Excel 读取对照夹具（rust-native-core 任务 1.5）。

运行方式（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/excel/generate.py

产物：当前目录下的 *.xlsx 与 expected/*.json。
期望值由 openpyxl（read_only=True, data_only=True —— 与 canonical 读取器
相同的打开方式）导出，作为 Rust calamine 探针的对照基准。

约定：
- 坐标一律 1-based（与 Excel UI / excelRow 诊断一致）；
- kind ∈ empty/text/int/float/bool/datetime/error；
- datetime 值为 ISO 8601 字符串（秒精度）；
- error 值为 Excel 错误码文本（如 #DIV/0!）。
"""

from __future__ import annotations

import datetime as dt
import json
import zipfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

HERE = Path(__file__).parent
EXPECTED = HERE / "expected"

# ---------------------------------------------------------------------------
# 夹具生成
# ---------------------------------------------------------------------------


def gen_active_sheet() -> None:
    """两个 Sheet，第二个为活跃；含稀疏行/空单元格/空串/0/Unicode/bool。"""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "数据"
    ws1["A1"] = "占位"

    ws2 = wb.create_sheet("补充")
    ws2["A1"] = "名称"
    ws2["B1"] = "数量"
    ws2["A2"] = "大剑"
    ws2["B2"] = 1
    # 第 3 行整行留空（稀疏行）
    ws2["A4"] = "铁剑"
    ws2["B4"] = 0
    ws2["A5"] = ""  # 显式空串（区别于真正缺失）
    ws2["A6"] = "中文🎮"
    ws2["B6"] = 3.5
    ws2["A7"] = True
    # 第 8、9 行留空，第 10 行出现尾部数据
    ws2["A10"] = "尾部"
    ws2["B10"] = "[1, 2, 3]"  # vector 单元格在读取层就是原始文本
    wb.active = 1
    wb.save(HERE / "active_sheet.xlsx")


def gen_dates_1900() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "日期"
    ws["A1"] = dt.datetime(2024, 1, 15, 10, 30, 0)
    ws["A2"] = dt.datetime(1900, 3, 1, 0, 0, 0)  # 1900 闰年 bug 边界之后
    ws["A3"] = dt.datetime(2000, 2, 29, 23, 59, 59)
    wb.save(HERE / "dates_1900.xlsx")


def gen_dates_1904() -> None:
    wb = Workbook()
    wb.epoch = dt.datetime(1904, 1, 1)  # workbookPr date1904="1"
    ws = wb.active
    ws.title = "日期"
    ws["A1"] = dt.datetime(2024, 1, 15, 10, 30, 0)
    ws["A2"] = dt.datetime(2000, 2, 29, 23, 59, 59)
    wb.save(HERE / "dates_1904.xlsx")


# --- 以下为 openpyxl 写不出来的形态，手工构造最小 xlsx ---

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WB = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_WB_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

_SS_EMPTY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>"""

_SHEET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<dimension ref="{dimension}"/>
<sheetData>{rows}</sheetData>
</worksheet>"""


def _write_raw(
    name: str,
    rows_xml: str,
    shared_strings: str = _SS_EMPTY,
    sheet: str = "主表",
    dimension: str = "A1:Z50",
) -> None:
    with zipfile.ZipFile(HERE / name, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", _WB.format(sheet=sheet))
        z.writestr("xl/_rels/workbook.xml.rels", _WB_RELS)
        z.writestr("xl/sharedStrings.xml", shared_strings)
        z.writestr("xl/worksheets/sheet1.xml", _SHEET.format(rows=rows_xml, dimension=dimension))


def gen_formula_cache() -> None:
    """公式缓存：A2 有数值缓存、A3 有字符串缓存（t=\"str\"）、A4 无缓存。"""
    rows = """
<row r="1">
<c r="A1"><v>5</v></c>
<c r="B1"><f>A1*2</f><v>10</v></c>
<c r="C1" t="str"><f>CONCATENATE("he","llo")</f><v>hello</v></c>
<c r="D1"><f>A1*3</f></c>
</row>"""
    _write_raw("formula_cache.xlsx", rows)


def gen_errors() -> None:
    """错误值单元格（t=\"e\"）。"""
    rows = """
<row r="1">
<c r="A1" t="e"><v>#DIV/0!</v></c>
<c r="B1" t="e"><v>#N/A</v></c>
<c r="C1" t="e"><v>#VALUE!</v></c>
<c r="D1" t="e"><v>#REF!</v></c>
</row>
<row r="2"><c r="A2"><v>7</v></c></row>"""
    _write_raw("errors.xlsx", rows)


def gen_rich_text() -> None:
    """富文本表头单元格：共享字符串含多个 run，读取应为拼接纯文本。"""
    sst = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">
<si><r><rPr><b/></rPr><t>加粗</t></r><r><t>普通</t></r></si>
</sst>"""
    rows = """
<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>1</v></c></row>"""
    _write_raw("rich_text.xlsx", rows, shared_strings=sst)


# ---------------------------------------------------------------------------
# 期望值导出（openpyxl，canonical 同款打开方式）
# ---------------------------------------------------------------------------


def _kind_of(cell) -> tuple[str, object]:
    value = cell.value
    if value is None:
        return "empty", None
    if isinstance(value, bool):
        return "bool", value
    if isinstance(value, int):
        return "int", value
    if isinstance(value, float):
        return "float", value
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return "datetime", value.isoformat()
    if isinstance(value, str):
        if cell.data_type == "e":
            return "error", value
        return "text", value
    raise AssertionError(f"未知单元格类型 {type(value)!r}: {value!r}")


def dump_expected(xlsx: Path) -> None:
    wb = load_workbook(str(xlsx), read_only=True, data_only=True)
    try:
        active = wb.active
        assert active is not None
        epoch = "1904" if wb.epoch.year == 1904 else "1900"
        cells = []
        max_row = max_col = 0
        for row in active.iter_rows():
            for cell in row:
                kind, value = _kind_of(cell)
                if kind == "empty":
                    continue
                max_row = max(max_row, cell.row)
                max_col = max(max_col, cell.column)
                cells.append({"row": cell.row, "col": cell.column, "kind": kind, "value": value})
        doc = {
            "file": xlsx.name,
            "sheets": wb.sheetnames,
            "active_sheet": active.title,
            "epoch": epoch,
            "max_row": max_row,
            "max_col": max_col,
            "cells": cells,
        }
        EXPECTED.mkdir(exist_ok=True)
        (EXPECTED / f"{xlsx.stem}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        wb.close()


def main() -> None:
    gen_active_sheet()
    gen_dates_1900()
    gen_dates_1904()
    gen_formula_cache()
    gen_errors()
    gen_rich_text()
    for xlsx in sorted(HERE.glob("*.xlsx")):
        dump_expected(xlsx)
        print(f"dumped {xlsx.name}")


if __name__ == "__main__":
    main()