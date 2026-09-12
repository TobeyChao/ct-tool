"""Stable hashes for canonical  Schema resources.

Used to detect schema drift between code and an Excel template. Every
template-visible field (names, types, comments, enum values, struct
nesting, ref/i18n/server_only flags) is included so that any change
that would alter the rendered template triggers a different hash.
"""

from __future__ import annotations

import hashlib
import json

from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    resource_to_data,
)

from ct.schema.type_expression import NamedType, VectorType


CANONICAL_SCHEMA_FORMAT_VERSION = "schema-resource/1"


def _stable_sha256(data: object) -> str:
    serialized = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_schema_hash(
    schema: TableResource,
    dependencies: tuple[RecordResource | EnumResource, ...] = (),
) -> str:
    """Hash the table and its transitive named types from the supplied pool.

    Unrelated resources and cross-table ref targets do not affect its template.
    Record fields are traversed recursively, including vector element types.
    """
    available = {resource.name: resource for resource in dependencies}
    reachable: dict[str, RecordResource | EnumResource] = {}

    def visit(resource: TableResource | RecordResource) -> None:
        for field in resource.fields:
            expr = field.type_expr
            if isinstance(expr, VectorType):
                expr = expr.element
            if not isinstance(expr, NamedType) or expr.name in reachable:
                continue
            target = available.get(expr.name)
            if target is None:
                continue
            reachable[expr.name] = target
            if isinstance(target, RecordResource):
                visit(target)

    visit(schema)
    data: object = {
        "format": CANONICAL_SCHEMA_FORMAT_VERSION,
        "table": resource_to_data(schema),
        "dependencies": [
            resource_to_data(resource)
            for resource in sorted(reachable.values(), key=lambda item: item.resource_id)
        ],
    }
    return _stable_sha256(data)[:16]


def compute_resource_hash(resource: SchemaResource) -> str:
    """Return a full sha256 for one canonical persisted resource."""
    return _stable_sha256(
        {
            "format": CANONICAL_SCHEMA_FORMAT_VERSION,
            "resource": resource_to_data(resource),
        }
    )
