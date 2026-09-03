"""Shared canonical Accessor/Index model for C# and Lua generators.

Both languages consume the same model: client fields in slot order, primary,
i18n fields, and the Code/Group index contracts. Neither generator parses
Type Expressions or re-derives index rules.
"""

from __future__ import annotations

from dataclasses import dataclass

from ct.schema.indexes import QueryIndex
from ct.schema.resources import TableResource
from ct.schema.type_expression import NamedType, ScalarType


@dataclass(frozen=True)
class AccessorField:
    name: str
    slot: int  # 0-based vtable slot among client fields
    kind: str  # scalar | enum | record | vector | string
    type_text: str
    i18n: bool = False


@dataclass(frozen=True)
class AccessorIndex:
    kind: str  # code | group
    field: str
    slot: int


@dataclass(frozen=True)
class CanonicalAccessorModel:
    table: TableResource
    client_fields: tuple[AccessorField, ...]
    primary: AccessorField
    i18n_fields: tuple[AccessorField, ...]
    indexes: tuple[AccessorIndex, ...]

    @property
    def has_i18n(self) -> bool:
        return bool(self.i18n_fields)


def _kind(type_expr) -> str:
    if isinstance(type_expr, ScalarType):
        return "string" if type_expr.name == "string" else "scalar"
    if isinstance(type_expr, NamedType):
        return "enum" if type_expr.expected_kind == "enum" else "record"
    return "vector"


def build_accessor_model(
    table: TableResource,
    indexes: tuple[QueryIndex, ...],
) -> CanonicalAccessorModel:
    client = [field for field in table.fields if not field.server_only]
    slots = {field.name: index for index, field in enumerate(client)}
    fields = tuple(
        AccessorField(
            name=field.name,
            slot=slots[field.name],
            kind=_kind(field.type_expr),
            type_text=_type_text(field),
            i18n=field.i18n,
        )
        for field in client
    )
    primary = next(field for field in fields if field.name == table.primary)
    i18n_fields = tuple(field for field in fields if field.i18n)
    accessor_indexes = tuple(
        AccessorIndex(index.kind, index.field, slots[index.field])
        for index in indexes
    )
    return CanonicalAccessorModel(
        table=table,
        client_fields=fields,
        primary=primary,
        i18n_fields=i18n_fields,
        indexes=accessor_indexes,
    )


def _type_text(field) -> str:
    from ct.schema.type_expression import serialize_type_expression

    return serialize_type_expression(field.type_expr)
