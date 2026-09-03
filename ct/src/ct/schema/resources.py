"""Canonical Table, Record and Enum workspace resources."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from ct.schema.naming import validate_name
from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    TypeExpression,
    VectorType,
    parse_type_expression,
    serialize_type_expression,
)


def _require_resource_name(name: str, *, label: str) -> str:
    error = validate_name(name)
    if error:
        raise ValueError(f"{label} {name}: {error}")
    return name


class FieldDef(BaseModel):
    """A field with exactly one canonical Type Expression."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    name: str
    type_expr: TypeExpression = Field(alias="type")
    i18n: bool = False
    ref: str | None = None
    server_only: bool = False
    comment: str = ""
    separator: str | None = None
    excel_columns: int | None = Field(default=None, ge=1)

    @field_validator("type_expr", mode="before")
    @classmethod
    def _parse_type(cls, value: object) -> object:
        return parse_type_expression(value) if isinstance(value, str) else value

    @field_serializer("type_expr")
    def _serialize_type(self, value: TypeExpression) -> str:
        return serialize_type_expression(value)

    @model_validator(mode="after")
    def _validate_field(self) -> FieldDef:
        _require_resource_name(self.name, label="字段")
        if self.i18n and self.server_only:
            raise ValueError(f"字段 {self.name} 不能同时标记 i18n 和 server_only")
        if self.i18n and not (
            isinstance(self.type_expr, ScalarType) and self.type_expr.name == "string"
        ):
            raise ValueError(f"字段 {self.name}: 只有 string 类型可以标记 i18n")
        if self.separator is not None and not self.separator:
            raise ValueError(f"字段 {self.name}: separator 不能为空")
        return self

    @property
    def type_text(self) -> str:
        return serialize_type_expression(self.type_expr)


def _validate_fields(
    fields: list[FieldDef],
    *,
    owner: str,
) -> list[FieldDef]:
    if not fields:
        raise ValueError(f"{owner}: fields 不能为空")
    seen: set[str] = set()
    for field in fields:
        if field.name in seen:
            raise ValueError(f"{owner}: 字段名 '{field.name}' 重复")
        seen.add(field.name)
    return fields


class TableResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: str
    primary: str
    fields: list[FieldDef]
    json_key: str | None = None
    excel_file: str | None = None

    @model_validator(mode="after")
    def _validate_table(self) -> TableResource:
        _require_resource_name(self.table, label="表")
        _validate_fields(self.fields, owner=f"表 {self.table}")
        by_name = {field.name: field for field in self.fields}
        primary = by_name.get(self.primary)
        if primary is None:
            raise ValueError(f"表 {self.table}: 主键 '{self.primary}' 不在字段列表中")
        if not (
            isinstance(primary.type_expr, ScalarType)
            and primary.type_expr.name in {"int32", "int64"}
        ):
            raise ValueError(
                f"表 {self.table}: 主键字段 '{self.primary}' 类型必须为 "
                f"int32 或 int64（当前: {primary.type_text}）"
            )
        return self

    @property
    def name(self) -> str:
        return self.table

    @property
    def resource_id(self) -> str:
        return f"table:{self.table}"


class RecordResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["record"] = "record"
    name: str
    fields: list[FieldDef]
    comment: str = ""

    @model_validator(mode="after")
    def _validate_record(self) -> RecordResource:
        _require_resource_name(self.name, label="Record")
        _validate_fields(self.fields, owner=f"Record {self.name}")
        for field in self.fields:
            if field.i18n:
                raise ValueError(
                    f"record:{self.name}/{field.name}: "
                    "首版 i18n 仅允许 Table 顶层 string 字段"
                )
            if field.server_only:
                raise ValueError(
                    f"record:{self.name}/{field.name}: "
                    "首版 server_only 仅允许 Table 顶层字段"
                )
        return self

    @property
    def resource_id(self) -> str:
        return f"record:{self.name}"


class EnumResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["enum"] = "enum"
    name: str
    values: list[str]
    comment: str = ""

    @model_validator(mode="after")
    def _validate_enum(self) -> EnumResource:
        _require_resource_name(self.name, label="Enum")
        if not self.values:
            raise ValueError(f"Enum {self.name}: values 不能为空")
        if len(self.values) > 256:
            raise ValueError(f"Enum {self.name}: byte wire type 最多支持 256 个值")
        seen: set[str] = set()
        for value in self.values:
            if not value or not value.isidentifier():
                raise ValueError(f"Enum {self.name}: '{value}' 不是合法标识符")
            if value in seen:
                raise ValueError(f"Enum {self.name}: 值 '{value}' 重复")
            seen.add(value)
        return self

    @property
    def resource_id(self) -> str:
        return f"enum:{self.name}"

    @property
    def wire_type(self) -> Literal["byte"]:
        return "byte"


NamedResource: TypeAlias = Annotated[
    RecordResource | EnumResource,
    Field(discriminator="kind"),
]
SchemaResource: TypeAlias = TableResource | RecordResource | EnumResource


def resource_to_data(resource: SchemaResource) -> dict[str, Any]:
    """Return the one canonical, human-diffable persistence representation."""
    data = resource.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_defaults=True,
    )
    if isinstance(resource, (RecordResource, EnumResource)):
        return {"kind": resource.kind, **data}
    return data


def replace_field_type(field: FieldDef, type_expr: TypeExpression) -> FieldDef:
    """Return a field with a resolved type without mutating the source model."""
    return field.model_copy(update={"type_expr": type_expr})


def named_references(type_expr: TypeExpression) -> tuple[NamedType, ...]:
    if isinstance(type_expr, NamedType):
        return (type_expr,)
    if isinstance(type_expr, VectorType):
        return named_references(type_expr.element)
    return ()
