from __future__ import annotations

from pathlib import Path

from ct.schema.models import FieldDef, TableSchema
from ct.schema.naming import to_pascal_case

# Schema type → FlatBuffers type
_TYPE_MAP = {
    "int32": "int32",
    "int64": "int64",
    "float": "float32",
    "double": "float64",
    "bool": "bool",
    "string": "string",
}


def _generate_enum(field: FieldDef) -> str:
    name = to_pascal_case(field.name)
    values = field.values or []
    entries = ", ".join(f"{v} = {i}" for i, v in enumerate(values))
    return f"enum {name} : byte {{ {entries} }}"


def _generate_struct_table(field: FieldDef, enums: list[str]) -> str:
    """为 struct 生成 FlatBuffers table（非 struct）定义。"""
    name = to_pascal_case(field.name)
    lines = [f"table {name} {{"]
    for sf in field.fields or []:
        fb_type = _resolve_field_type(sf, enums)
        lines.append(f"  {sf.name}: {fb_type};")
    lines.append("}")
    return "\n".join(lines)


def _resolve_field_type(field: FieldDef, enums: list[str]) -> str:
    """解析字段的 FlatBuffers 类型。"""
    if field.type == "enum":
        return to_pascal_case(field.name)
    elif field.type == "struct":
        return to_pascal_case(field.name)
    elif field.type == "array":
        if field.element == "enum":
            return f"[{to_pascal_case(field.name)}Elem]"
        else:
            return f"[{_TYPE_MAP.get(field.element, field.element)}]"
    else:
        return _TYPE_MAP.get(field.type, field.type)


def generate_fbs(schema: TableSchema, output_dir: Path) -> Path:
    """从 TableSchema 生成 .fbs 文件。"""
    fbs_dir = output_dir / "fbs"
    fbs_dir.mkdir(parents=True, exist_ok=True)

    table_name = to_pascal_case(schema.table)
    lines: list[str] = []
    enums: list[str] = []
    struct_tables: list[str] = []

    # 收集所有需要生成的 enum 和 struct 定义
    for field in schema.fields:
        if field.server_only:
            continue
        if field.type == "enum":
            enums.append(_generate_enum(field))
        elif field.type == "struct":
            _collect_nested(field, enums, struct_tables)
        elif field.type == "array" and field.element == "enum":
            # array<enum> 需要单独的 enum 定义
            elem_name = f"{to_pascal_case(field.name)}Elem"
            values = field.element_values or []
            entries = ", ".join(f"{v} = {i}" for i, v in enumerate(values))
            enums.append(f"enum {elem_name} : byte {{ {entries} }}")

    # 写入 enum 定义
    for e in enums:
        lines.append(e)
        lines.append("")

    # 写入 struct table 定义
    for s in struct_tables:
        lines.append(s)
        lines.append("")

    # 主表 table
    lines.append(f"table {table_name} {{")
    for field in schema.fields:
        if field.server_only:
            continue
        fb_type = _resolve_field_type(field, enums)
        lines.append(f"  {field.name}: {fb_type};")
    lines.append("}")
    lines.append("")

    # 主表 Table 容器
    lines.append(f"table {table_name}Table {{")
    lines.append(f"  items: [{table_name}];")
    lines.append("}")
    lines.append("")

    # i18n 变体
    if schema.has_i18n:
        pk_field = schema.primary_field
        pk_type = _TYPE_MAP.get(pk_field.type, pk_field.type)

        lines.append(f"table {table_name}I18nEntry {{")
        lines.append(f"  {pk_field.name}: {pk_type};")
        for f in schema.i18n_fields:
            lines.append(f"  {f.name}: string;")
        lines.append("}")
        lines.append("")

        lines.append(f"table {table_name}I18nTable {{")
        lines.append(f"  entries: [{table_name}I18nEntry];")
        lines.append("}")
        lines.append("")

    # root_type
    lines.append(f"root_type {table_name}Table;")
    lines.append("")

    out_path = fbs_dir / f"{schema.table}.fbs"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return out_path


def _collect_nested(
    field: FieldDef,
    enums: list[str],
    struct_tables: list[str],
) -> None:
    """递归收集 struct 内部的 enum 和 struct 定义。"""
    for sf in field.fields or []:
        if sf.type == "enum":
            enums.append(_generate_enum(sf))
        elif sf.type == "struct":
            _collect_nested(sf, enums, struct_tables)
    struct_tables.append(_generate_struct_table(field, enums))


def generate_container_fbs(output_dir: Path) -> Path:
    """生成 container.fbs，定义 BundledTable 和 DataBundle。"""
    fbs_dir = output_dir / "fbs"
    fbs_dir.mkdir(parents=True, exist_ok=True)

    content = """\
table BundledTable {
  name: string;
  data: [ubyte];
}

table DataBundle {
  tables: [BundledTable];
}

root_type DataBundle;
"""
    out_path = fbs_dir / "container.fbs"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return out_path
