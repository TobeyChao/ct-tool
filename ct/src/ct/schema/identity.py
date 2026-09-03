"""Stable resource/field identities without persisted UUID metadata."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePath
from typing import Callable
from uuid import UUID, uuid4

from ct.schema.naming import validate_name


RESOURCE_KINDS = frozenset({"table", "record", "enum"})


def resource_id(kind: str, name: str) -> str:
    if kind not in RESOURCE_KINDS:
        raise ValueError(f"未知资源 kind: {kind}")
    name_error = validate_name(name)
    if name_error:
        raise ValueError(f"资源 {name}: {name_error}")
    return f"{kind}:{name}"


def canonical_field_path(owner_id: str, *segments: str) -> str:
    kind, separator, owner_name = owner_id.partition(":")
    if not separator or kind not in RESOURCE_KINDS or validate_name(owner_name):
        raise ValueError(f"无效资源 ID: {owner_id}")
    if not segments:
        raise ValueError("字段路径至少需要一个 segment")
    for segment in segments:
        error = validate_name(segment)
        if error:
            raise ValueError(f"字段路径 {segment}: {error}")
    return "/".join((owner_id, *segments))


def _persisted_field_id(source_key: str, path: str) -> str:
    normalized_source = PurePath(source_key).as_posix()
    digest = hashlib.sha256(
        f"schema-field\0{normalized_source}\0{path}".encode("utf-8")
    ).hexdigest()[:20]
    return f"field:{digest}"


@dataclass(frozen=True)
class FieldIdentity:
    """A Draft-session identity paired with its current canonical path."""

    field_id: str
    canonical_path: str
    persisted: bool

    @classmethod
    def from_persisted(
        cls,
        *,
        source_key: str,
        owner_id: str,
        field_segments: tuple[str, ...],
    ) -> FieldIdentity:
        path = canonical_field_path(owner_id, *field_segments)
        return cls(
            field_id=_persisted_field_id(source_key, path),
            canonical_path=path,
            persisted=True,
        )

    @classmethod
    def for_draft(
        cls,
        *,
        owner_id: str,
        field_segments: tuple[str, ...],
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> FieldIdentity:
        return cls(
            field_id=f"draft-field:{uuid_factory()}",
            canonical_path=canonical_field_path(owner_id, *field_segments),
            persisted=False,
        )

    def relocate(
        self,
        *,
        owner_id: str,
        field_segments: tuple[str, ...],
    ) -> FieldIdentity:
        """Project an explicit rename/move while retaining Draft selection identity."""
        return FieldIdentity(
            field_id=self.field_id,
            canonical_path=canonical_field_path(owner_id, *field_segments),
            persisted=self.persisted,
        )
