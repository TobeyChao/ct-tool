"""Schema hashing — compute a stable fingerprint of a TableSchema.

Used to detect schema drift between code and an Excel template. Every
template-visible field (names, types, comments, enum values, struct
nesting, ref/i18n/server_only flags) is included so that any change
that would alter the rendered template triggers a different hash.
"""

from __future__ import annotations

import hashlib
import json

from ct.schema.models import TableSchema


def compute_schema_hash(schema: TableSchema) -> str:
    """Return a 16-char hex sha256 prefix of the schema's normalized JSON."""
    data = schema.model_dump()
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]