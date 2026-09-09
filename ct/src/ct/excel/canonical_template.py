"""Generate Excel template workbooks from the canonical ``Layout``.

The header node tree uses paired comment/field rows at every depth. Structural
nodes merge horizontally over their leaf span, while shallow leaves merge their
field cells vertically through the final header row.

Every column's stable path and annotation is driven by ``ct.excel.layout``,
so headers always match the Web type expressions.
"""

from __future__ import annotations

from pathlib import Path
import warnings
from copy import copy

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.packaging.custom import DateTimeProperty, IntProperty, StringProperty
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ct.excel.layout import Column, Layout
from ct.schema.resources import EnumResource

_NAME_RUN_FONT = InlineFont(rFont="Aptos", b=True, sz=11, color="FF172033")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_COMMENT_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True, indent=0)
_THIN = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
_NORMAL_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
_GROUP_FILL = PatternFill(start_color="CFE8D8", end_color="CFE8D8", fill_type="solid")
_ARRAY_FILL = PatternFill(start_color="D7E6FA", end_color="D7E6FA", fill_type="solid")
_SLOT_FILL = PatternFill(start_color="E7D9F7", end_color="E7D9F7", fill_type="solid")
_PRIMARY_FILL = PatternFill(start_color="FBE6A5", end_color="FBE6A5", fill_type="solid")
_COMMENT_FILL = PatternFill(start_color="DCE3EC", end_color="DCE3EC", fill_type="solid")
_COMMENT_FONT = Font(name="Aptos", size=9, color="475569")
_WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
_COL_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
)
_NAME_ROW_HEIGHT = 36

_META_TOOL_VERSION = "ct_tool_version"
_META_TABLE_NAME = "ct_table_name"
_META_HEADER_ROWS = "ct_header_rows"
_META_SCHEMA_HASH = "ct_schema_hash"
_META_GENERATED_AT = "ct_generated_at"


def _richtext(name: str, annotation: str, type_color: str = "64748B") -> CellRichText:
    type_font = InlineFont(rFont="Consolas", i=True, sz=9, color=f"FF{type_color}")
    return CellRichText(
        [
            TextBlock(_NAME_RUN_FONT, f"{name}\n"),
            TextBlock(type_font, annotation),
        ]
    )


def _top_segment(table_id: str, stable_path: str) -> str:
    """Top-level field name (no group marker) for a column's stable path."""
    tail = stable_path[len(table_id) + 1:]
    head = tail.partition("/")[0]
    return head.partition("[")[0]


def _segments(table_id: str, stable_path: str) -> list[str]:
    """Path segments with each ``[g]`` group marker expanded to its own level."""
    tail = stable_path[len(table_id) + 1:]
    segments: list[str] = []
    for chunk in tail.split("/"):
        if "[" in chunk:
            name, _, rest = chunk.partition("[")
            group = rest.split("]", 1)[0]
            segments.append(name)
            segments.append(f"#{group}")
        else:
            segments.append(chunk)
    return segments


def generate_canonical_template(
    layout: Layout,
    out_path: Path,
    *,
    enums: dict[str, EnumResource],
    primary: str = "",
) -> Path:
    """Write a  template workbook for *layout* and return its path."""
    wb = Workbook()
    ws = wb.active
    ws.title = layout.table_id.partition(":")[2]
    table_name = layout.table_id.partition(":")[2]
    _write_header_rows(ws, layout, table_name, primary=primary)
    _apply_header_borders(ws, layout)
    _add_enum_notes(ws, layout, enums)

    total_cols = layout.column_count
    for column in range(1, total_cols + 1):
        ws.column_dimensions[get_column_letter(column)].width = 16
    for row in range(1, layout.header_rows + 1):
        if ws.row_dimensions[row].height is None:
            ws.row_dimensions[row].height = 30 if row % 2 else 38
    data_start = layout.header_rows + 1
    ws.freeze_panes = ws.cell(row=data_start, column=1)
    # openpyxl creates the bottom-pane selection at A1 by default.  With a
    # frozen multi-row header Excel initially paints rows 1..header_rows in
    # both panes until the user scrolls.  Anchor the active cell in the
    # scrollable pane so its first render starts at the first data row.
    selection = ws.sheet_view.selection[0]
    selection.activeCell = f"A{data_start}"
    selection.sqref = f"A{data_start}"

    _add_data_validations(ws, layout, enums, data_start=data_start)
    # Ordinary data cells intentionally retain the neutral workbook white
    # background; validation and Notes provide the non-visual assistance.

    _write_metadata(wb, layout, table_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return out_path


def _column_ranges(
    layout: Layout,
    table_name: str,
) -> dict[str, tuple[int, int]]:
    ranges: dict[str, list[int]] = {}
    for column in layout.columns:
        top = _top_segment(layout.table_id, column.stable_path)
        ranges.setdefault(top, []).append(column.index)
    return {
        top: (min(indexes), max(indexes))
        for top, indexes in ranges.items()
    }


def _write_header_rows(
    ws,
    layout: Layout,
    table_name: str,
    primary: str = "",
) -> None:
    max_depth = layout.header_rows // 2
    for depth in range(1, max_depth + 1):
        grouped: dict[tuple[str, ...], list[Column]] = {}
        for column in layout.columns:
            parts = _segments(layout.table_id, column.stable_path)
            if len(parts) < depth:
                continue
            grouped.setdefault(tuple(parts[:depth]), []).append(column)
        comment_row, field_row = depth * 2 - 1, depth * 2
        for parts, cols in grouped.items():
            start, end = cols[0].index, cols[-1].index
            if start < end:
                ws.merge_cells(start_row=comment_row, start_column=start, end_row=comment_row, end_column=end)
                ws.merge_cells(start_row=field_row, start_column=start, end_row=field_row, end_column=end)
            segment = parts[-1]
            anchor = ws.cell(row=field_row, column=start)
            annotation = cols[0].field_annotation or cols[0].annotation
            if depth > 1 and segment.startswith("#"):
                annotation = cols[0].type_text
            leaf_depth = len(_segments(layout.table_id, cols[0].stable_path))
            is_leaf = depth >= leaf_depth
            top_type = cols[0].field_annotation or cols[0].annotation
            if depth == 1 and top_type.startswith("vector<"):
                node_fill, type_color = _ARRAY_FILL, "315B9A"
            elif segment.startswith("#"):
                node_fill, type_color = _SLOT_FILL, "6B4AA1"
            elif not is_leaf:
                node_fill, type_color = _GROUP_FILL, "2F6B4A"
            else:
                node_fill, type_color = _NORMAL_FILL, "64748B"
            if depth == 1 and segment == primary:
                type_color = "8A5A00"
            anchor.value = _richtext(segment, annotation, type_color)
            anchor.alignment = _CENTER
            anchor.fill = _PRIMARY_FILL if depth == 1 and segment == primary else node_fill
            comment = ((cols[0].field_comment or cols[0].comment) if depth == 1 else cols[0].comment) or ""
            c = ws.cell(row=comment_row, column=start)
            c.value = comment
            c.font = _COMMENT_FONT
            c.alignment = _COMMENT_ALIGN
            c.fill = _COMMENT_FILL
            for index in range(start, end + 1):
                ws.cell(row=comment_row, column=index).border = _THIN
                ws.cell(row=field_row, column=index).border = _THIN
            if comment:
                width = max(1, end - start + 1) * 16
                chars_per_line = max(10, int(width / 1.2))
                lines = sum(max(1, (len(line) + chars_per_line - 1) // chars_per_line) for line in str(comment).splitlines())
                ws.row_dimensions[comment_row].height = min(60, max(30, 18 * lines))

    # A leaf that terminates before the deepest structural level owns one
    # field cell spanning the remaining field rows. This keeps scalar table
    # fields visually aligned with nested records and fixed-vector slots.
    for column in layout.columns:
        leaf_depth = len(_segments(layout.table_id, column.stable_path))
        if leaf_depth >= max_depth:
            continue
        start_row = leaf_depth * 2
        end_row = layout.header_rows
        if start_row == end_row:
            continue
        ws.merge_cells(
            start_row=start_row,
            start_column=column.index,
            end_row=end_row,
            end_column=column.index,
        )
        cell = ws.cell(row=start_row, column=column.index)
        cell.alignment = _CENTER


def _add_data_validations(ws, layout: Layout, enums: dict[str, EnumResource], data_start: int) -> None:
    for column in layout.columns:
        letter = get_column_letter(column.index)
        if column.type_text == "bool":
            dv = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
            dv.sqref = f"{letter}{data_start}:{letter}1048576"
            ws.add_data_validation(dv)
            continue
        if column.type_text == "int32":
            dv = DataValidation(type="whole", operator="between", formula1="-2147483648", formula2="2147483647", allow_blank=True)
            dv.sqref = f"{letter}{data_start}:{letter}1048576"
            ws.add_data_validation(dv)
            continue
        if column.type_text in {"float", "double"}:
            # Excel's data-validation parser rejects the theoretical IEEE-754
            # 1E+308 bounds even though they are valid Python floats. Keep a
            # conservative finite range; canonical validation remains the
            # authoritative check for values outside it.
            dv = DataValidation(type="decimal", operator="between", formula1="-1E+307", formula2="1E+307", allow_blank=True)
            dv.sqref = f"{letter}{data_start}:{letter}1048576"
            ws.add_data_validation(dv)
            continue
        enum = enums.get(column.type_text)
        if enum is None:
            continue
        formula = '"' + ",".join(item.name for item in enum.values) + '"'
        if len(formula) > 255:
            warnings.warn(
                f"Enum {enum.name} 候选超过 Excel 255 字符限制，"
                "请参考表头 Note 填写",
                UserWarning,
            )
            continue
        dv = DataValidation(
            type="list",
            formula1=formula,
            showDropDown=False,
            allow_blank=True,
        )
        dv.sqref = f"{letter}{data_start}:{letter}1048576"
        ws.add_data_validation(dv)


def _add_enum_notes(ws, layout: Layout, enums: dict[str, EnumResource]) -> None:
    for column in layout.columns:
        enum = enums.get(column.type_text)
        if enum is None:
            continue
        lines = [f"类型：{enum.name}" + (f"；{enum.comment}" if enum.comment else "")]
        lines.extend(f"{item.name}: {item.comment}" if item.comment else item.name for item in enum.values)
        target = ws.cell(row=max(2, column.depth * 2), column=column.index)
        if isinstance(target, MergedCell):
            for merged in ws.merged_cells.ranges:
                if target.coordinate in merged:
                    target = ws.cell(row=merged.min_row, column=merged.min_col)
                    break
        target.comment = Comment("\n".join(lines), "ct")


def _apply_header_borders(ws, layout: Layout) -> None:
    medium = Side(style="medium", color="0F172A")
    double = Side(style="double", color="334155")
    for row in range(1, layout.header_rows + 1):
        ws.cell(row=row, column=1).border = Border(left=medium, top=ws.cell(row=row, column=1).border.top, bottom=ws.cell(row=row, column=1).border.bottom, right=ws.cell(row=row, column=1).border.right)
        ws.cell(row=row, column=layout.column_count).border = Border(right=medium, top=ws.cell(row=row, column=layout.column_count).border.top, bottom=ws.cell(row=row, column=layout.column_count).border.bottom, left=ws.cell(row=row, column=layout.column_count).border.left)
    for col in range(1, layout.column_count + 1):
        cell = ws.cell(row=layout.header_rows, column=col)
        # Apply the divider to the actual bottom edge cell.  For a vertically
        # merged leaf this is a MergedCell rather than the merge anchor, and
        # Excel otherwise keeps the anchor's thin border on some columns.
        border = copy(cell.border)
        border.bottom = double
        cell.border = border
    # Re-format vertical merges after changing the divider.  openpyxl builds
    # MergedCell edge styles from the anchor, so updating only the visible
    # bottom row leaves some merged columns with the old thin edge.
    for merged in ws.merged_cells.ranges:
        if merged.max_row != layout.header_rows:
            continue
        anchor = ws.cell(row=merged.min_row, column=merged.min_col)
        border = copy(anchor.border)
        border.bottom = double
        anchor.border = border
        merged.format()


def _write_metadata(wb: Workbook, layout: Layout, table_name: str) -> None:
    from datetime import datetime, timezone

    props = wb.custom_doc_props
    props.append(StringProperty(name=_META_TOOL_VERSION, value="ct"))
    props.append(StringProperty(name=_META_TABLE_NAME, value=table_name))
    props.append(IntProperty(name=_META_HEADER_ROWS, value=layout.header_rows))
    props.append(StringProperty(name=_META_SCHEMA_HASH, value=layout.schema_hash))
    props.append(
        DateTimeProperty(
            name=_META_GENERATED_AT,
            value=datetime.now(timezone.utc),
        )
    )
