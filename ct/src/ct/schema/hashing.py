"""Stable hashes for legacy templates and canonical v4 Schema resources.

Used to detect schema drift between code and an Excel template. Every
template-visible field (names, types, comments, enum values, struct
nesting, ref/i18n/server_only flags) is included so that any change
that would alter the rendered template triggers a different hash.
"""

from __future__ import annotations

import hashlib
import json

from ct.schema.models import TableSchema
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    resource_to_data,
)


CANONICAL_SCHEMA_FORMAT_VERSION = "schema-resource-v4/1"


def _stable_sha256(data: object) -> str:
    serialized = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_schema_hash(
    schema: TableSchema | TableResource,
    dependencies: tuple[RecordResource | EnumResource, ...] = (),
) -> str:
    """Return a 16-char hex sha256 prefix of the schema's normalized JSON."""
    if isinstance(schema, TableResource):
        data: object = {
            "format": CANONICAL_SCHEMA_FORMAT_VERSION,
            "table": resource_to_data(schema),
            "dependencies": [
                resource_to_data(resource)
                for resource in sorted(dependencies, key=lambda item: item.resource_id)
            ],
        }
    else:
        data = schema.model_dump()
    return _stable_sha256(data)[:16]


def compute_resource_hash(resource: SchemaResource) -> str:
    """Return a full sha256 for one canonical persisted resource."""
    return _stable_sha256(
        {
            "format": CANONICAL_SCHEMA_FORMAT_VERSION,
            "resource": resource_to_data(resource),
        }
    )
