"""Canonical Excel column layout for v4 Table resources.

A ``Layout`` is the single source of truth for how a Table's fields map to
Excel columns: each leaf column carries a stable canonical path, the leaf
Type Expression text, a header annotation and (for expanded
``vector<Record>``) a group ordinal. Workbook generation, reading, data
migration and the layout manifest all consume this one model.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ct.schema.resources import RecordResource, TableResource
from ct.schema.type_expression import (
    NamedType,
    ScalarType,
    TypeExpression,
    VectorType,
    serialize_type_expression,
)


@dataclass(frozen=True)
class Column:
    index: int  # 1-based column position
    stable_path: str  # canonical leaf path incl. group marker, e.g. table:Item/Rewards[1]/Min
    type_text: str  # leaf Type Expression text, e.g. "int32"
    annotation: str  # header annotation, e.g. "vector<DropReward>", "ItemRarity"
    leaf: str  # leaf display name (last segment)
    group_index: int | None = None  # 1-based group ordinal for expanded vector<Record>
    depth: int = 1  # 1-based header depth of this leaf (comment row excluded)
    comment: str = ""  # leaf field comment (header comment row)
    field_annotation: str = ""  # annotation shown on the top-level field row

    @property
    def logical_path(self) -> str:
        """Path without the ``[g]`` group marker (for stable mapping)."""
        if self.group_index is None:
            return self.stable_path
        head, _, tail = self.stable_path.partition("[")
        return head + tail[tail.find("]") + 1:]


@dataclass(frozen=True)
class Layout:
    table_id: str
    schema_hash: str
    header_rows: int  # name+type rows + 1 comment row
    columns: tuple[Column, ...]

    @property
    def column_count(self) -> int:
        return len(self.columns)


def _record_depth(record: RecordResource, records: dict[str, RecordResource]) -> int:
    """1-based depth of a record's field tree (scalar leaves = 1)."""
    max_depth = 1
    for field in record.fields:
        type_expr = field.type_expr
        if isinstance(type_expr, NamedType) and _named_kind(type_expr, records) == "record":
            nested = records.get(type_expr.name)
            if nested is not None:
                max_depth = max(max_depth, 1 + _record_depth(nested, records))
        elif isinstance(type_expr, VectorType):
            element = type_expr.element
            if (
                isinstance(element, NamedType)
                and _named_kind(element, records) == "record"
                and (field.excel_columns or 0) > 0
            ):
                nested = records.get(element.name)
                if nested is not None:
                    max_depth = max(max_depth, 2 + _record_depth(nested, records))
    return max_depth


def _named_kind(named: NamedType, records: dict[str, RecordResource]) -> str:
    """Resolve a named reference's kind: explicit kind wins, else by lookup."""
    if named.expected_kind:
        return named.expected_kind
    return "record" if named.name in records else "enum"


class LayoutBuilder:
    def __init__(
        self,
        table: TableResource,
        *,
        schema_hash: str,
        records: dict[str, RecordResource],
    ) -> None:
        self.table = table
        self.schema_hash = schema_hash
        self.records = records
        self.columns: list[Column] = []
        self.max_depth = 1

    def build(self) -> Layout:
        col = 1
        owner = self.table.resource_id
        for field in self.table.fields:
            col = self._emit(field, f"{owner}/{field.name}", col, depth=1, group=None)
        return Layout(
            table_id=self.table.resource_id,
            schema_hash=self.schema_hash,
            header_rows=self.max_depth + 1,
            columns=tuple(self.columns),
        )

    def _field_annotation(self, type_expr: TypeExpression) -> str:
        if isinstance(type_expr, VectorType):
            return f"vector<{serialize_type_expression(type_expr.element)}>"
        if isinstance(type_expr, NamedType):
            return type_expr.name
        return type_expr.name

    def _emit(
        self,
        field,
        path: str,
        col: int,
        *,
        depth: int,
        group: int | None,
        field_annotation: str = "",
    ) -> int:
        type_expr = field.type_expr
        self.max_depth = max(self.max_depth, depth)
        field_annotation = field_annotation or self._field_annotation(type_expr)

        if isinstance(type_expr, VectorType):
            return self._emit_vector(
                field, type_expr, path, col,
                depth=depth, group=group, field_annotation=field_annotation,
            )
        if isinstance(type_expr, NamedType):
            if _named_kind(type_expr, self.records) == "record":
                return self._emit_record(
                    type_expr, path, col,
                    depth=depth, group=group, field_annotation=field_annotation,
                )
            return self._emit_leaf(col, path, type_expr.name, type_expr.name, depth, group, field.comment, field_annotation)
        return self._emit_leaf(col, path, type_expr.name, type_expr.name, depth, group, field.comment, field_annotation)

    def _emit_vector(
        self,
        field,
        vector: VectorType,
        path: str,
        col: int,
        *,
        depth: int,
        group: int | None,
        field_annotation: str,
    ) -> int:
        annotation = f"vector<{serialize_type_expression(vector.element)}>"
        element = vector.element
        groups = field.excel_columns or 0
        if (
            isinstance(element, NamedType)
            and _named_kind(element, self.records) == "record"
            and groups > 0
        ):
            record = self.records[element.name]
            self.max_depth = max(
                self.max_depth, depth + 1 + _record_depth(record, self.records)
            )
            for g in range(1, groups + 1):
                for sub_field in record.fields:
                    col = self._emit(
                        sub_field,
                        f"{path}[{g}]/{sub_field.name}",
                        col,
                        depth=depth + 1,
                        group=g,
                        field_annotation=field_annotation,
                    )
            return col
        element_text = serialize_type_expression(element)
        return self._emit_leaf(col, path, element_text, annotation, depth, group, field.comment, field_annotation)

    def _emit_record(
        self,
        named: NamedType,
        path: str,
        col: int,
        *,
        depth: int,
        group: int | None,
        field_annotation: str = "",
    ) -> int:
        record = self.records[named.name]
        self.max_depth = max(self.max_depth, depth + _record_depth(record, self.records))
        for sub_field in record.fields:
            col = self._emit(
                sub_field,
                f"{path}/{sub_field.name}",
                col,
                depth=depth,
                group=group,
                field_annotation=field_annotation or named.name,
            )
        return col

    def _emit_leaf(
        self,
        col: int,
        path: str,
        type_text: str,
        annotation: str,
        depth: int,
        group: int | None,
        comment: str = "",
        field_annotation: str = "",
    ) -> int:
        self.columns.append(
            Column(
                index=col,
                stable_path=path,
                type_text=type_text,
                annotation=annotation,
                leaf=path.rpartition("/")[2],
                group_index=group,
                depth=depth,
                comment=comment,
                field_annotation=field_annotation,
            )
        )
        return col + 1


def build_layout(
    table: TableResource,
    *,
    schema_hash: str,
    records: dict[str, RecordResource],
) -> Layout:
    return LayoutBuilder(table, schema_hash=schema_hash, records=records).build()
