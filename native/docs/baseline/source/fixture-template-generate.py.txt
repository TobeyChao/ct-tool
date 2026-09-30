"""生成模板写入/迁移对照夹具（rust-native-core 任务 1.6）。

运行方式（仓库根目录）::

    ct/.venv/Scripts/python.exe native/fixtures/template/generate.py

产物：
- layout_v1.json / layout_v2a.json / layout_v2b.json / enums.json —— 布局与枚举输入
- golden/template_v1.xlsx / template_v2a.xlsx —— Python 模板产出
- golden/data_v1.xlsx —— v1 模板 + 数据行（迁移输入）
- golden/manifest_v1.json —— v1 布局清单
- golden/migrated_v2a.xlsx —— Python 迁移产出
- expected/*.semantics.json —— openpyxl 语义转储（结构对照基准）
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent.parent / "ct" / "src"))

from openpyxl import load_workbook  # noqa: E402

from ct.excel.canonical_template import build_canonical_template  # noqa: E402
from ct.excel.layout import LayoutBuilder  # noqa: E402
from ct.excel.layout_manifest import LayoutManifest  # noqa: E402
from ct.schema.resources import (  # noqa: E402
    EnumResource,
    FieldDef,
    RecordResource,
    TableResource,
)

GOLDEN = HERE / "golden"
EXPECTED = HERE / "expected"

RECORDS = {
    "Position": RecordResource(
        name="Position",
        fields=[
            FieldDef(name="X", type="float"),
            FieldDef(name="Y", type="float"),
            FieldDef(name="Z", type="float"),
        ],
    ),
    "DropReward": RecordResource(
        name="DropReward",
        fields=[
            FieldDef(name="ItemId", type="int32"),
            FieldDef(name="Count", type="int32"),
        ],
    ),
}

ENUMS = {
    "ItemRarity": EnumResource(
        name="ItemRarity",
        values=["Common", "Rare", "Epic"],
        comment="稀有度",
    ),
    "EffectKind": EnumResource(name="EffectKind", values=["None", "Buff", "Debuff"]),
    # 候选公式超 255 字符 → 下拉跳过 + warning
    "LongEnum": EnumResource(
        name="LongEnum",
        values=[f"QuiteLongEnumValueName{index:02d}" for index in range(20)],
    ),
}


def make_table(*, drop_tags: bool = False, with_weight: bool = False) -> TableResource:
    fields = [
        FieldDef(name="Id", type="int32", comment="编号"),
        FieldDef(name="CodeName", type="string"),
        FieldDef(name="Rarity", type="ItemRarity"),
        FieldDef(name="Effect", type="Position", comment="效果位置"),
        FieldDef(name="Rewards", type="vector<DropReward>", excel_columns=2),
        FieldDef(name="Desc", type="string", comment="描述文本"),
        FieldDef(name="Active", type="bool"),
        FieldDef(name="Score", type="double"),
        FieldDef(name="Big", type="LongEnum"),
    ]
    if not drop_tags:
        fields.insert(5, FieldDef(name="Tags", type="vector<int32>"))
    if with_weight:
        fields.append(FieldDef(name="Weight", type="float"))
    return TableResource(
        table="Item", primary="Id", fields=fields, uniform=False
    )


def dump_layout(layout, path: Path) -> None:
    doc = {
        "table_id": layout.table_id,
        "schema_hash": layout.schema_hash,
        "header_rows": layout.header_rows,
        "columns": [
            {
                "index": c.index,
                "stable_path": c.stable_path,
                "type_text": c.type_text,
                "annotation": c.annotation,
                "leaf": c.leaf,
                "group_index": c.group_index,
                "depth": c.depth,
                "comment": c.comment,
                "field_comment": c.field_comment,
                "field_annotation": c.field_annotation,
                "ref": c.ref,
                "primary": c.primary,
            }
            for c in layout.columns
        ],
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_enums(path: Path) -> None:
    doc = {
        name: {
            "comment": enum.comment,
            "values": [{"name": item.name, "comment": item.comment} for item in enum.values],
        }
        for name, enum in ENUMS.items()
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_semantics(xlsx: Path, out: Path) -> None:
    """openpyxl 语义转储：单元格文本/填充/富文本 run/合并/冻结/校验/批注/尺寸/属性。"""
    wb = load_workbook(str(xlsx), rich_text=True)
    ws = wb.active
    cells = {}
    fills = {}
    runs = {}
    notes = {}
    for row in ws.iter_rows():
        for cell in row:
            value = cell.value
            if value is None:
                continue
            key = f"{cell.row},{cell.column}"
            cells[key] = str(value)
            fill = cell.fill
            if fill and fill.fill_type == "solid":
                fills[key] = str(fill.start_color.rgb)
            if hasattr(value, "__iter__") and not isinstance(value, str):
                runs[key] = [
                    {
                        "text": str(getattr(block, "text", block)),
                        "font": getattr(getattr(block, "font", None), "rFont", None),
                        "bold": bool(getattr(getattr(block, "font", None), "b", False)),
                    }
                    for block in value
                ]
            if cell.comment is not None:
                notes[key] = cell.comment.text
    props = {}
    for prop in wb.custom_doc_props.props:
        if prop.name == "ct_generated_at":
            props[prop.name] = "<timestamp>"
        else:
            props[prop.name] = getattr(prop, "value", None)
    doc = {
        "sheet": ws.title,
        "cells": cells,
        "fills": fills,
        "rich_runs": runs,
        "merges": sorted(str(r) for r in ws.merged_cells.ranges),
        "freeze": str(ws.freeze_panes),
        "validations": [
            {
                "type": dv.type,
                "formula1": dv.formula1,
                "formula2": dv.formula2,
                # whole/decimal 的 operator 缺省即 between（Excel 语义），
                # openpyxl 显式写出、rust_xlsxwriter 省略，归一为 between
                "operator": dv.operator
                or ("between" if dv.type in {"whole", "decimal"} else None),
                "sqref": str(dv.sqref),
            }
            for dv in ws.data_validations.dataValidation
        ],
        "notes": notes,
        # <col min max> 区间展开为逐列
        "col_widths": {
            col_letter: dim.width
            for dim in ws.column_dimensions.values()
            if dim.width
            for col_letter in (
                __import__("openpyxl").utils.get_column_letter(i)
                for i in range(dim.min or 1, (dim.max or dim.min or 1) + 1)
            )
        },
        "row_heights": {str(k): v.height for k, v in ws.row_dimensions.items() if v.height},
        "props": props,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def dump_data_region(xlsx: Path, out: Path) -> None:
    """数据区转储（迁移对照）：活跃 Sheet 表头之后的所有非空单元格。"""
    wb = load_workbook(str(xlsx), read_only=True, data_only=True)
    ws = wb.active
    cells = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                cells[f"{cell.row},{cell.column}"] = (
                    cell.value.isoformat()
                    if hasattr(cell.value, "isoformat")
                    else cell.value
                )
    doc = {"sheet": ws.title, "cells": cells}
    out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def dump_schema(table: TableResource, path: Path) -> None:
    """以夹具线格式导出 schema（Rust 布局构建的输入）。"""
    def field_json(f) -> dict:
        doc = {"name": f.name, "type": f.type_text}
        if f.comment:
            doc["comment"] = f.comment
        if f.excel_columns:
            doc["excel_columns"] = f.excel_columns
        if f.server_only:
            doc["server_only"] = True
        return doc

    doc = {
        "table": {
            "name": table.table,
            "primary": table.primary,
            "uniform": table.uniform,
            "indexes": [i.kind for i in table.indexes],
            "fields": [field_json(f) for f in table.fields],
        },
        "records": {
            name: {"fields": [field_json(f) for f in r.fields]}
            for name, r in RECORDS.items()
        },
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    from ct.app.canonical_commands import _migrate_excel_rows

    GOLDEN.mkdir(exist_ok=True)
    EXPECTED.mkdir(exist_ok=True)

    table_v1 = make_table()
    layout_v1 = LayoutBuilder(
        table_v1, schema_hash="sha256:fixture0001", records=RECORDS
    ).build()
    table_v2a = make_table(with_weight=True)
    layout_v2a = LayoutBuilder(
        table_v2a, schema_hash="sha256:fixture0002", records=RECORDS
    ).build()
    table_v2b = make_table(drop_tags=True)
    layout_v2b = LayoutBuilder(
        table_v2b, schema_hash="sha256:fixture0003", records=RECORDS
    ).build()

    dump_schema(table_v1, HERE / "schema_v1.json")
    dump_layout(layout_v1, HERE / "layout_v1.json")
    dump_layout(layout_v2a, HERE / "layout_v2a.json")
    dump_layout(layout_v2b, HERE / "layout_v2b.json")
    dump_enums(HERE / "enums.json")

    (GOLDEN / "template_v1.xlsx").write_bytes(
        build_canonical_template(layout_v1, enums=ENUMS, primary="Id")
    )
    (GOLDEN / "template_v2a.xlsx").write_bytes(
        build_canonical_template(layout_v2a, enums=ENUMS, primary="Id")
    )

    # 数据行（写进 v1 模板）
    header = layout_v1.header_rows
    wb = load_workbook(GOLDEN / "template_v1.xlsx")
    ws = wb.active
    by_path = {c.stable_path: c.index for c in layout_v1.columns}

    def put(row: int, path_suffix: str, value) -> None:
        ws.cell(row=row, column=by_path[f"table:Item/{path_suffix}"]).value = value

    r = header + 1
    put(r, "Id", 1)
    put(r, "CodeName", "sword_iron")
    put(r, "Rarity", "Common")
    put(r, "Effect/X", 1.5)
    put(r, "Effect/Y", 0)
    put(r, "Effect/Z", -2)
    put(r, "Rewards[1]/ItemId", 7)
    put(r, "Rewards[1]/Count", 2)
    put(r, "Tags", "[1, 2]")
    put(r, "Desc", "铁剑")
    put(r, "Active", True)
    put(r, "Score", 99.5)
    put(r, "Big", "QuiteLongEnumValueName03")
    r += 1
    put(r, "Id", 2)
    put(r, "CodeName", "potion_red")
    put(r, "Rarity", "Rare")
    put(r, "Desc", "红药🎮")
    put(r, "Active", False)
    wb.save(GOLDEN / "data_v1.xlsx")

    manifest = LayoutManifest.from_layout(layout_v1)
    (GOLDEN / "manifest_v1.json").write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 迁移 golden：v1 数据 → v2a 模板
    (GOLDEN / "migrated_v2a.xlsx").unlink(missing_ok=True)
    template_copy = GOLDEN / "_template_v2a_for_migration.xlsx"
    template_copy.write_bytes((GOLDEN / "template_v2a.xlsx").read_bytes())
    _migrate_excel_rows(
        GOLDEN / "data_v1.xlsx",
        template_copy,
        layout_v1,
        layout_v2a,
        manifest,
    )
    template_copy.rename(GOLDEN / "migrated_v2a.xlsx")

    # 行解析期望值（canonical 读取）
    from ct.excel.canonical_reader import read_canonical_excel

    def dump_parsed(xlsx_name: str, table: TableResource, layout, out_name: str) -> None:
        parsed = read_canonical_excel(
            GOLDEN / xlsx_name, layout, table, records=RECORDS, enums=ENUMS
        )
        doc = {
            "rows": parsed.rows,
            "excel_rows": parsed.excel_rows,
            "issues": [issue.to_dict() for issue in parsed.issues],
        }
        (EXPECTED / out_name).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    dump_parsed("data_v1.xlsx", table_v1, layout_v1, "parsed_v1.json")

    # 带错误的表：越界 int / 非法 vector 文法 / 非法枚举标识
    bad_wb = load_workbook(GOLDEN / "template_v1.xlsx")
    bad_ws = bad_wb.active
    r = layout_v1.header_rows + 1
    bad_ws.cell(row=r, column=by_path["table:Item/Id"]).value = "abc"  # int 期望
    bad_ws.cell(row=r, column=by_path["table:Item/Tags"]).value = "[1 2]"  # 缺逗号
    bad_ws.cell(row=r, column=by_path["table:Item/Rarity"]).value = "Legendary!"
    r += 1
    bad_ws.cell(row=r, column=by_path["table:Item/Id"]).value = 1
    bad_ws.cell(row=r, column=by_path["table:Item/Tags"]).value = '[1, "x"]'
    bad_ws.cell(row=r, column=by_path["table:Item/Score"]).value = "很双"
    bad_wb.save(GOLDEN / "bad_data_v1.xlsx")
    dump_parsed("bad_data_v1.xlsx", table_v1, layout_v1, "parsed_bad_v1.json")

    # JSON 导出 golden
    from ct.export.canonical_json import serialize_table_json

    parsed = read_canonical_excel(
        GOLDEN / "data_v1.xlsx", layout_v1, table_v1, records=RECORDS, enums=ENUMS
    )
    # 写字节（不经文本模式的 CRLF 转换；产物统一 LF）
    (EXPECTED / "json_v1.txt").write_bytes(
        serialize_table_json(parsed.rows, table_v1).encode("utf-8")
    )
    (EXPECTED / "json_empty.txt").write_bytes(
        serialize_table_json([], table_v1).encode("utf-8")
    )

    # FBS golden（含带 i18n 字段的 Buff 表）
    from ct.export.canonical_fbs import table_fbs_text, types_fbs_text
    from ct.schema.resource_graph import named_dependency_edges, resource_topological_order

    table_buff = TableResource(
        table="Buff",
        primary="Id",
        fields=[
            FieldDef(name="Id", type="int32"),
            FieldDef(name="Desc", type="string", i18n=True),
            FieldDef(name="Kind", type="EffectKind"),
        ],
        uniform=False,
    )
    # 仓库加载后具名类型才解析（record:/enum: 前缀）——拓扑序要求解析态
    from ct.schema.resource_repository import YamlResourceRepository
    from ct.schema.resources import resource_to_data
    from ct.schema.resource_repository import dump_yaml

    captured: dict[Path, bytes] = {}
    schemas_dir = Path("config/schemas")
    types_dir = Path("config/types")
    captured[schemas_dir / "item.yaml"] = dump_yaml(resource_to_data(table_v1)).encode("utf-8")
    captured[schemas_dir / "buff.yaml"] = dump_yaml(resource_to_data(table_buff)).encode("utf-8")
    for r in RECORDS.values():
        captured[types_dir / f"{r.name}.yaml"] = dump_yaml(resource_to_data(r)).encode("utf-8")
    for e in ENUMS.values():
        captured[types_dir / f"{e.name}.yaml"] = dump_yaml(resource_to_data(e)).encode("utf-8")
    repo = YamlResourceRepository(schemas_dir, types_dir, contents=captured)
    resolved_ws = repo.load()
    table_v1_resolved = next(t for t in resolved_ws.tables if t.table == "Item")
    table_buff_resolved = next(t for t in resolved_ws.tables if t.table == "Buff")
    all_resources = [table_v1_resolved, table_buff_resolved, *resolved_ws.records, *resolved_ws.enums]
    order = resource_topological_order(all_resources, named_graph=named_dependency_edges(all_resources))
    resources_map = {r.resource_id: r for r in all_resources}
    (EXPECTED / "types.fbs.txt").write_bytes(
        types_fbs_text(order, resources_map).encode("utf-8")
    )
    (EXPECTED / "Item.fbs.txt").write_bytes(table_fbs_text(table_v1_resolved).encode("utf-8"))
    (EXPECTED / "Buff.fbs.txt").write_bytes(table_fbs_text(table_buff_resolved).encode("utf-8"))
    # Buff 的 schema JSON（Rust 侧重建用）
    (HERE / "schema_buff.json").write_text(
        json.dumps(
            {
                "table": {
                    "name": "Buff",
                    "primary": "Id",
                    "uniform": False,
                    "fields": [
                        {"name": "Id", "type": "int32"},
                        {"name": "Desc", "type": "string", "i18n": True},
                        {"name": "Kind", "type": "EffectKind"},
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # C# / Lua accessor golden（complex non-uniform + uniform + i18n）
    from ct.export.canonical_accessor import render_csharp_accessor, render_lua_accessor
    from ct.export.canonical_binary import plan_object_layout


    from ct.schema.resources import QueryIndex as _QI
    item_indexes = (_QI(kind="codename"),)
    records_models = {name: r for name, r in RECORDS.items()}
    (EXPECTED / "Item_accessor.cs.txt").write_bytes(
        render_csharp_accessor(
            table_v1_resolved, item_indexes, records=records_models
        ).encode("utf-8")
    )
    (EXPECTED / "Item_accessor.lua.txt").write_bytes(
        render_lua_accessor(table_v1_resolved, item_indexes, records=records_models).encode("utf-8")
    )
    # uniform 变体（定宽字面量偏移路径）
    layout_info = plan_object_layout(
        [f for f in table_v1_resolved.fields if not f.server_only], records_models
    )
    uniform_offsets = layout_info.slot_offsets
    (EXPECTED / "Item_accessor_uniform.cs.txt").write_bytes(
        render_csharp_accessor(
            table_v1_resolved, item_indexes, records=records_models,
            uniform_offsets=uniform_offsets,
        ).encode("utf-8")
    )
    (EXPECTED / "Buff_accessor.cs.txt").write_bytes(
        render_csharp_accessor(table_buff_resolved, (), records=records_models).encode("utf-8")
    )
    (EXPECTED / "Buff_accessor.lua.txt").write_bytes(
        render_lua_accessor(table_buff_resolved, (), records=records_models).encode("utf-8")
    )

    # 语义转储
    dump_semantics(GOLDEN / "template_v1.xlsx", EXPECTED / "template_v1.semantics.json")
    dump_semantics(GOLDEN / "template_v2a.xlsx", EXPECTED / "template_v2a.semantics.json")
    dump_data_region(GOLDEN / "data_v1.xlsx", EXPECTED / "data_v1.data.json")
    dump_data_region(GOLDEN / "migrated_v2a.xlsx", EXPECTED / "migrated_v2a.data.json")

    print("fixtures/template 生成完成")


if __name__ == "__main__":
    main()