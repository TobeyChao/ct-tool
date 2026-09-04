"""Shared canonical Accessor/Index model for C# and Lua generators.

Both languages consume the same model: client fields in slot order, primary,
i18n fields, and the Code/Group index contracts. Neither generator parses
Type Expressions or re-derives index rules. Named ``record`` fields are resolved
against the workspace ``records`` map so the generators can emit nested row
accessors whose wire shape matches the FlatBuffers binary (a record is a nested
table at an offset; a ``vector<Record>`` is a vector of such offsets).
"""

from __future__ import annotations

from dataclasses import dataclass

from ct.schema.indexes import QueryIndex
from ct.schema.resources import RecordResource, TableResource
from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    VectorType,
    serialize_type_expression,
)


@dataclass(frozen=True)
class AccessorField:
    name: str
    slot: int  # 0-based vtable slot among client fields (or record fields)
    kind: str  # scalar | enum | record | vector | string
    type_text: str
    i18n: bool = False
    record: RecordResource | None = None  # nested record (kind=record, or vector-of-record)
    element_kind: str | None = None  # for vector: scalar | enum | record | string
    element_type: str = ""  # for vector: element type text (int32 / string / enum name / record name)
    ref_table: str | None = None  # cross-table ref 目标表名（field.ref 的 `.` 前）
    ref_field: str | None = None  # cross-table ref 目标字段名（默认主键）

    @property
    def record_name(self) -> str | None:
        return self.record.name if self.record else None

    @property
    def container_text(self) -> str | None:
        """The harmony-style single value container type for a vector field."""
        if self.kind != "vector":
            return None
        if self.element_kind == "record" and self.record_name:
            return f"NStructArray<{self.record_name}Row>"
        if self.element_kind == "string":
            return "NStructArray<NString>"
        if self.element_kind == "enum":
            return f"NArray<{self.element_type}>"
        scalar = {"int32": "int", "int64": "long", "float": "float", "double": "double", "bool": "bool"}
        return f"NArray<{scalar.get(self.element_type, "int")}>"


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
    records: dict[str, RecordResource] | None = None

    @property
    def has_i18n(self) -> bool:
        return bool(self.i18n_fields)


def _lookup_record(named: NamedType, records) -> RecordResource | None:
    if records is None:
        return None
    return records.get(named.name)


def _build_field(
    field,
    slot: int,
    records,
) -> AccessorField:
    """Resolve one FieldDef (or record field) into an AccessorField."""
    type_expr = field.type_expr
    text = serialize_type_expression(type_expr)
    if isinstance(type_expr, VectorType):
        element = type_expr.element
        if isinstance(element, NamedType):
            rec = _lookup_record(element, records)
            return AccessorField(
                name=field.name,
                slot=slot,
                kind="vector",
                type_text=text,
                i18n=field.i18n,
                record=rec,
                element_kind="record" if rec else "enum",
                element_type=element.name,
            )
        if isinstance(element, ScalarType):
            return AccessorField(
                name=field.name,
                slot=slot,
                kind="vector",
                type_text=text,
                i18n=field.i18n,
                element_kind="string" if element.name == "string" else "scalar",
                element_type=element.name,
            )
        return AccessorField(
            name=field.name,
            slot=slot,
            kind="vector",
            type_text=text,
            i18n=field.i18n,
            element_kind="scalar",
        )
    if isinstance(type_expr, NamedType):
        rec = _lookup_record(type_expr, records)
        return AccessorField(
            name=field.name,
            slot=slot,
            kind=("record" if rec else "enum"),
            type_text=text,
            i18n=field.i18n,
            record=rec,
            ref_table=_ref_table(field),
            ref_field=_ref_field(field, rec),
        )
    if isinstance(type_expr, ScalarType):
        return AccessorField(
            name=field.name,
            slot=slot,
            kind=("string" if type_expr.name == "string" else "scalar"),
            type_text=text,
            i18n=field.i18n,
            ref_table=_ref_table(field),
            ref_field=_ref_field(field, None),
        )
    return AccessorField(
        name=field.name,
        slot=slot,
        kind="scalar",
        type_text=text,
        i18n=field.i18n,
    )


def record_accessor_fields(
    record: RecordResource,
    records: dict[str, RecordResource] | None,
) -> tuple[AccessorField, ...]:
    """Resolve a Record's fields to AccessorFields (slots = field order)."""
    return tuple(
        _build_field(field, index, records)
        for index, field in enumerate(record.fields)
    )


def referenced_records(
    model: CanonicalAccessorModel,
) -> list[RecordResource]:
    """All records referenced by the table's client fields, transitively.

    Returns records in deterministic pre-order (parent before its nested
    records), so each generated row struct is emitted exactly once.
    """
    result: list[RecordResource] = []
    seen: set[str] = set()

    def visit(record: RecordResource) -> None:
        if record.name in seen:
            return
        seen.add(record.name)
        result.append(record)
        for sub in record_accessor_fields(record, model.records):
            if sub.record is not None:
                visit(sub.record)

    for field in model.client_fields:
        if field.record is not None:
            visit(field.record)
    return result


def _ref_table(field) -> str | None:
    if not field.ref:
        return None
    return field.ref.partition(".")[0] or None


def _ref_field(field, rec) -> str | None:
    if not field.ref:
        return None
    _table, _sep, fld = field.ref.partition(".")
    return fld or (rec.name if rec else None)


def build_accessor_model(
    table: TableResource,
    indexes: tuple[QueryIndex, ...],
    records: dict[str, RecordResource] | None = None,
) -> CanonicalAccessorModel:
    client = [field for field in table.fields if not field.server_only]
    slots = {field.name: index for index, field in enumerate(client)}
    fields = tuple(
        _build_field(field, slots[field.name], records) for field in client
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
        records=records,
    )
