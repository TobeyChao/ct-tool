"""Schema 源抽象（SchemaRepository）+ YAML 实现。

canonical 模型（``TableSchema``）是唯一真理；schema 源格式可插拔
（YAML 为当前唯一实现，未来 .fbs 通过 ``schema_format`` 切换）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml
import pydantic

from ct.schema.conventions import FbsConvention
from ct.schema.models import FieldDef
from ct.schema.models import TableSchema


def _schema_error_text(exc: Exception) -> str:
    """把 pydantic ValidationError 精简为可读的一行错误，其他异常原样。"""
    if isinstance(exc, pydantic.ValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            # ctx.error 携带原始 ValueError 消息（如 "表 item: ... 首字符必须大写"），
            # 不依赖 pydantic 展示层 msg 的 "Value error, " 前缀格式。
            err_ctx = err.get("ctx") or {}
            err_obj = err_ctx.get("error")
            msg = str(err_obj) if err_obj is not None else err.get("msg", str(exc))
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts)
    return str(exc)


class SchemaRepository(Protocol):
    """从某种源格式读取表 schema，并提供其 fbs 表示。

    - ``load_all``：解析为 canonical 模型（顺序无关，拓扑排序在 loader）；
    - ``fbs_sources``：返回 ``{表名: fbs文本}``——YAML 模式为生成产物，
      .fbs 模式将直通源文件；写盘与 flatc 由管道的 FBS 步骤负责。
    """

    def load_all(self) -> list[TableSchema]: ...

    def fbs_sources(self, schemas: list[TableSchema]) -> dict[str, str]: ...


def _generate_enum(field: FieldDef) -> str:
    # 类型名加 Enum 后缀，避免与字段名同名（flatc 拒绝字段名 == 类型名）
    name = f"{field.name}{FbsConvention.ENUM_SUFFIX}"
    values = field.values or []
    entries = ", ".join(f"{v} = {i}" for i, v in enumerate(values))
    return f"enum {name} : byte {{ {entries} }}"


def _generate_struct_table(field: FieldDef, enums: list[str]) -> str:
    """为 struct 生成 FlatBuffers table（非 struct）定义。"""
    name = f"{field.name}{FbsConvention.STRUCT_SUFFIX}"
    lines = [f"table {name} {{"]
    for sf in field.fields or []:
        fb_type = _resolve_field_type(sf, enums)
        lines.append(f"  {sf.name}: {fb_type};")
    lines.append("}")
    return "\n".join(lines)


def _resolve_field_type(field: FieldDef, enums: list[str]) -> str:
    """解析字段的 FlatBuffers 类型。"""
    if field.type == "enum":
        return f"{field.name}{FbsConvention.ENUM_SUFFIX}"
    elif field.type == "struct":
        return f"{field.name}{FbsConvention.STRUCT_SUFFIX}"
    elif field.type == "array":
        if field.element == "enum":
            return f"[{field.name}{FbsConvention.ELEM_SUFFIX}]"
        return f"[{FbsConvention.TYPE_MAP.get(field.element, field.element)}]"
    else:
        return FbsConvention.TYPE_MAP.get(field.type, field.type)


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


def _schema_fbs_text(schema: TableSchema) -> str:
    """生成单张表的主 .fbs 文本（与旧 fbs_generator.generate_fbs 逐字一致）。"""
    table_name = schema.table
    lines: list[str] = []
    enums: list[str] = []
    struct_tables: list[str] = []

    for field in schema.fields:
        if field.server_only:
            continue
        if field.type == "enum":
            enums.append(_generate_enum(field))
        elif field.type == "struct":
            _collect_nested(field, enums, struct_tables)
        elif field.type == "array" and field.element == "enum":
            elem_name = f"{field.name}{FbsConvention.ELEM_SUFFIX}"
            values = field.element_values or []
            entries = ", ".join(f"{v} = {i}" for i, v in enumerate(values))
            enums.append(f"enum {elem_name} : byte {{ {entries} }}")

    for e in enums:
        lines.append(e)
        lines.append("")
    for s in struct_tables:
        lines.append(s)
        lines.append("")

    lines.append(f"table {table_name} {{")
    for field in schema.fields:
        if field.server_only:
            continue
        fb_type = _resolve_field_type(field, enums)
        lines.append(f"  {field.name}: {fb_type};")
    lines.append("}")
    lines.append("")

    lines.append(f"table {table_name}{FbsConvention.CONTAINER_SUFFIX} {{")
    lines.append(f"  items: [{table_name}];")
    lines.append("}")
    lines.append("")
    lines.append(f"root_type {table_name}{FbsConvention.CONTAINER_SUFFIX};")
    lines.append("")

    return "\n".join(lines)


def _i18n_fbs_text(schema: TableSchema) -> str:
    """生成 i18n 变体 .fbs 文本（零外部依赖，自带 root_type）。"""
    table_name = schema.table
    pk_field = schema.primary_field
    pk_type = FbsConvention.TYPE_MAP.get(pk_field.type, pk_field.type)

    i18n_lines: list[str] = []
    i18n_lines.append(f"table {table_name}{FbsConvention.I18N_ENTRY_SUFFIX} {{")
    i18n_lines.append(f"  {pk_field.name}: {pk_type};")
    for f in schema.i18n_fields:
        i18n_lines.append(f"  {f.name}: string;")
    i18n_lines.append("}")
    i18n_lines.append("")
    i18n_lines.append(f"table {table_name}{FbsConvention.I18N_TABLE_SUFFIX} {{")
    i18n_lines.append(f"  entries: [{table_name}{FbsConvention.I18N_ENTRY_SUFFIX}];")
    i18n_lines.append("}")
    i18n_lines.append("")
    i18n_lines.append(f"root_type {table_name}{FbsConvention.I18N_TABLE_SUFFIX};")
    i18n_lines.append("")
    return "\n".join(i18n_lines)


class YamlSchemaRepository:
    """从 ``config/schemas/*.yaml`` 加载 schema（自旧 loader.load_schemas 迁入）。"""

    def __init__(self, schemas_dir: Path) -> None:
        self.schemas_dir = schemas_dir

    def load_all(self) -> list[TableSchema]:
        if not self.schemas_dir.exists():
            raise FileNotFoundError(f"Schema 目录不存在: {self.schemas_dir}")

        schemas: list[TableSchema] = []
        seen_names: dict[str, Path] = {}

        for yaml_path in sorted(self.schemas_dir.glob("*.yaml")):
            try:
                with open(yaml_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except (yaml.YAMLError, OSError) as e:
                raise ValueError(f"加载 schema 失败 [{yaml_path.name}]: {e}") from e
            if data is None:
                continue
            try:
                schema = TableSchema(**data)
            except Exception as e:
                raise ValueError(
                    f"加载 schema 失败 [{yaml_path.name}]: {_schema_error_text(e)}"
                ) from e

            if schema.table in seen_names:
                raise ValueError(
                    f"表名 '{schema.table}' 重复: "
                    f"{seen_names[schema.table].name} 和 {yaml_path.name}"
                )
            seen_names[schema.table] = yaml_path
            schemas.append(schema)

        return schemas

    def fbs_sources(
        self, schemas: list[TableSchema]
    ) -> dict[str, dict[str, str | None]]:
        """返回 ``{表名: {"main": 主 fbs 文本, "i18n": 变体文本或 None}}``。"""
        sources: dict[str, dict[str, str | None]] = {}
        for schema in schemas:
            sources[schema.table] = {
                "main": _schema_fbs_text(schema),
                "i18n": _i18n_fbs_text(schema) if schema.has_i18n else None,
            }
        return sources


def create_repository(schemas_dir: Path, fmt: str = "yaml") -> SchemaRepository:
    """按 ``schema_format`` 选择 repository 实现（默认 yaml，行为不变）。"""
    if fmt == "yaml":
        return YamlSchemaRepository(schemas_dir)
    raise NotImplementedError(f"schema_format={fmt!r} 暂不支持")
