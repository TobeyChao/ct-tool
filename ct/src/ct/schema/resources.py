"""Canonical Table, Record and Enum workspace resources."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from ct.schema.naming import validate_name
from ct.schema.type_expression import (
    INTEGER_SCALAR_NAMES,
    SCALAR_DEFAULTS,
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
    excel_columns: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _reject_removed_separator(cls, value: object) -> object:
        if isinstance(value, dict) and "separator" in value:
            raise ValueError(
                "字段 separator 已移除；vector 必须使用内置 [...] 英文逗号文法"
            )
        return value

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
        if self.excel_columns is not None and not isinstance(
            self.type_expr, VectorType
        ):
            raise ValueError(
                f"字段 {self.name}: excel_columns（展开组数）仅适用于 "
                f"vector<T>（定长展开列），当前类型 {self.type_text}"
            )
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


#: CodeName 索引**固定**指向的字段名。
#:
#: 它不是一个「可以指向任意 string 字段」的索引：字段就叫 **CodeName**、类型就是 **string**
#: （与 参考实现 的 flags ``1<<1 CodeName`` + nameTableIndex 同构 —— 那边也是约定字段，
#: 不是自由指定）。所以 schema 里声明 codename 索引**不需要写 field**。
CODENAME_FIELD = "CodeName"


class QueryIndex(BaseModel):
    """表级查询索引声明（CodeName 唯一字符串查找 / Group 分组查找）。

    - ``kind: codename`` —— **不写 field**，固定指向名为 :data:`CODENAME_FIELD` 的 string 字段。
      构造后 ``field`` 会被归一化成该常量，下游（导出器 / 运行时）继续按 ``.field`` 读。
    - ``kind: group`` —— 必须给 ``field``（int32 / bool / Enum）。

    定义在这里（而不是 ``schema/indexes.py``）是为了让它成为 **Table 资源的一部分**，
    从而能随 YAML 持久化、被仓库加载、并一路到达导出器 ——
    否则编辑器里设置的索引会在落盘时被静默丢弃。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["codename", "group"]
    field: str | None = None

    @model_validator(mode="after")
    def _validate_kind_field(self) -> QueryIndex:
        if self.kind == "codename":
            # 幂等：允许省略（推荐）或正好写成 CodeName —— pydantic 对嵌套模型会重新校验，
            # 归一化后的实例必须能再次通过本校验。写别的字段名才是真错误。
            if self.field is not None and self.field != CODENAME_FIELD:
                raise ValueError(
                    f"codename 索引固定指向 {CODENAME_FIELD} 字段；不要写 field，"
                    f"或只能写 {CODENAME_FIELD}（收到 field={self.field!r}）"
                )
            object.__setattr__(self, "field", CODENAME_FIELD)
        elif not self.field:
            raise ValueError("group 索引必须指定 field")
        return self

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        """落盘形状由本模型显式决定。

        codename **不写 field** —— 归一化出来的 ``CodeName`` 若被写进 YAML，回读时又会被
        「codename 只能指向 CodeName」接受，看似无害，但会让「固定字段」这件事在 YAML 里
        显得可配置。注意不能靠 ``field_serializer`` 返回 None：``exclude_none`` 判的是
        **归一化后的原值**（非 None），结果会落成 ``field: None``。
        """
        if self.kind == "codename":
            return {"kind": self.kind}
        return {"kind": self.kind, "field": self.field}


class TableResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: str
    primary: str
    fields: list[FieldDef]
    json_key: str | None = None
    excel_file: str | None = None
    # 表级查询索引（最多各一个 codename / group）
    indexes: tuple[QueryIndex, ...] = ()

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
            and primary.type_expr.name in INTEGER_SCALAR_NAMES
        ):
            raise ValueError(
                f"表 {self.table}: 主键字段 '{self.primary}' 类型必须为 "
                f"int32 或 int64（当前: {primary.type_text}）"
            )
        if primary.server_only:
            raise ValueError(
                f"表 {self.table}: 主键字段 '{self.primary}' 不能标记 server_only"
                f"（主键是客户端与次语言 bundle 的主键，server_only 字段不进入客户端 Binary）"
            )
        return self

    @property
    def name(self) -> str:
        return self.table

    @property
    def resource_id(self) -> str:
        return f"table:{self.table}"

    @property
    def i18n_fields(self) -> list[FieldDef]:
        """顶层标记为 i18n 的字段（与 legacy TableSchema 同名派生属性对齐）。"""
        return [field for field in self.fields if field.i18n]

    @property
    def has_i18n(self) -> bool:
        return any(field.i18n for field in self.fields)

    @property
    def primary_field(self) -> FieldDef:
        """主键字段定义（primary 已在模型校验中保证存在于 fields）。"""
        return next(field for field in self.fields if field.name == self.primary)

    @property
    def resolved_json_key(self) -> str:
        return self.json_key or f"{self.table}s"

    @property
    def resolved_excel_file(self) -> str:
        return self.excel_file or f"{self.table}.xlsx"


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
    values: list["EnumItem"]
    comment: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_items(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("values"), list):
            # Keep Python-level construction ergonomic; repository loading
            # rejects this legacy YAML shape before model validation.
            value = dict(value)
            value["values"] = [
                {"name": item, "comment": ""} if isinstance(item, str) else item
                for item in value["values"]
            ]
        return value

    @model_validator(mode="after")
    def _validate_enum(self) -> EnumResource:
        _require_resource_name(self.name, label="Enum")
        if not self.values:
            raise ValueError(f"Enum {self.name}: values 不能为空")
        if len(self.values) > 256:
            raise ValueError(f"Enum {self.name}: byte wire type 最多支持 256 个值")
        seen: set[str] = set()
        for item in self.values:
            if item.name in seen:
                raise ValueError(f"Enum {self.name}: 值 '{item.name}' 重复")
            seen.add(item.name)
        return self

    @property
    def resource_id(self) -> str:
        return f"enum:{self.name}"

    @property
    def wire_type(self) -> Literal["byte"]:
        return "byte"


class EnumItem(BaseModel):
    """Ordered, documented Enum item; list position is its wire ordinal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    comment: str = ""

    @model_validator(mode="after")
    def _validate_item(self) -> "EnumItem":
        if not self.name or not self.name.isidentifier():
            raise ValueError(f"'{self.name}' 不是合法标识符")
        return self


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


def canonical_default(
    type_expr: TypeExpression,
    *,
    records: dict[str, RecordResource] | None = None,
    enums: dict[str, EnumResource] | None = None,
) -> Any:
    """Return the canonical runtime default for a resolved type expression."""
    records = records or {}
    enums = enums or {}
    if isinstance(type_expr, ScalarType):
        return SCALAR_DEFAULTS[type_expr.name]
    if isinstance(type_expr, VectorType):
        return []
    if isinstance(type_expr, NamedType):
        if type_expr.expected_kind == "enum":
            enum = enums.get(type_expr.name)
            if enum is None:
                raise ValueError(f"缺少 Enum 定义: {type_expr.name}")
            return enum.values[0].name
        record = records.get(type_expr.name)
        if record is None:
            raise ValueError(f"缺少 Record 定义: {type_expr.name}")
        return {
            field.name: canonical_default(field.type_expr, records=records, enums=enums)
            for field in record.fields
        }
    raise TypeError(f"不支持的类型: {type_expr!r}")
