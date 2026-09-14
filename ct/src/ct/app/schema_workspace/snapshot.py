"""Read-only Workspace snapshot with a deterministic revision hash.

The revision covers every managed input: canonical resources, Excel files,
i18n language/config files and generation inputs. Hashing the raw file bytes
lets external edits (including formatting) be detected; semantic fingerprints
(``ct.cache.fingerprints``) separately decide artifact reuse.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.schema.resources import resource_to_data

SNAPSHOT_FORMAT = "workspace-snapshot/1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return _sha256(path.read_bytes())


def _config_payload(config) -> dict[str, Any]:
    return {
        "primary_lang": config.primary_lang,
        "secondary_langs": sorted(config.secondary_langs),
        "schemas_dir": config.schemas_dir,
        "types_dir": config.types_dir,
        "excel_dir": config.excel_dir,
        "output_dir": config.output_dir,
        "cache_dir": config.cache_dir,
        "i18n_dir": config.i18n_dir,
    }


@dataclass(frozen=True)
class WorkspaceSnapshot:
    revision: str
    config_hash: str
    resources_hash: str
    excel_hashes: dict[str, str] = field(default_factory=dict)
    i18n_hashes: dict[str, str] = field(default_factory=dict)
    generation_inputs_hash: str = ""

    def changed_inputs(self, other: "WorkspaceSnapshot") -> list[str]:
        """Return which managed input groups changed (external-change report)."""
        changed: list[str] = []
        if self.config_hash != other.config_hash:
            changed.append("config")
        if self.resources_hash != other.resources_hash:
            changed.append("schema/types")
        if self.generation_inputs_hash != other.generation_inputs_hash:
            changed.append("generation-inputs")
        excel_changed = [
            name
            for name, digest in self.excel_hashes.items()
            if other.excel_hashes.get(name) != digest
        ]
        if excel_changed:
            changed.append("excel:" + ",".join(sorted(excel_changed)))
        i18n_changed = [
            key
            for key, digest in self.i18n_hashes.items()
            if other.i18n_hashes.get(key) != digest
        ]
        if i18n_changed:
            changed.append("i18n:" + ",".join(sorted(i18n_changed)))
        return changed


def build_snapshot(
    workspace: CanonicalWorkspace,
    *,
    generation_inputs: dict[str, Any] | None = None,
) -> WorkspaceSnapshot:
    config = workspace.config

    resources_data = [
        resource_to_data(resource) for resource in workspace.resources.resources
    ]
    resources_hash = _sha256(
        json.dumps(
            {"format": SNAPSHOT_FORMAT, "resources": resources_data},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    )

    excel_dir = config.resolve("excel_dir")
    excel_hashes = {}
    for resource in workspace.resources.tables:
        excel_hashes[resource.table] = _hash_file(
            excel_dir / (resource.excel_file or f"{resource.table}.xlsx")
        ) or ""

    i18n_dir = config.resolve("i18n_dir")
    i18n_hashes: dict[str, str] = {}
    for lang in ("source", *config.secondary_langs):
        lang_dir = i18n_dir / lang
        if not lang_dir.exists():
            continue
        for path in sorted(lang_dir.glob("*.json")):
            digest = _hash_file(path)
            if digest is not None:
                i18n_hashes[f"{lang}/{path.stem}"] = digest

    generation_inputs_hash = _sha256(
        json.dumps(
            generation_inputs or {},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    )
    config_hash = _sha256(
        json.dumps(_config_payload(config), sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    payload = {
        "config": config_hash,
        "resources": resources_hash,
        "excel": excel_hashes,
        "i18n": i18n_hashes,
        "generation": generation_inputs_hash,
    }
    revision = _sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return WorkspaceSnapshot(
        revision=revision,
        config_hash=config_hash,
        resources_hash=resources_hash,
        excel_hashes=excel_hashes,
        i18n_hashes=i18n_hashes,
        generation_inputs_hash=generation_inputs_hash,
    )


# --------------------------------------------------------------------------- #
# Schema baseline (schemaRevision)
#
# The draft/save protocol compares *this* revision, not ``WorkspaceSnapshot``:
# saving YAML may not be invalidated by Excel or translation edits, and an
# unchanged Excel file must not make a draft look stale. It therefore covers
# exactly the source of truth for schema structure: the raw bytes of
# ``config/global.yaml`` (path configuration included) plus the members and raw
# bytes of the schemas/types directories.
# --------------------------------------------------------------------------- #

SCHEMA_REVISION_FORMAT = "schema-revision/1"


def config_file_path(config) -> Path:
    """Path of the project's ``config/global.yaml``."""
    return Path(config.project_root) / "config" / "global.yaml"


@dataclass(frozen=True)
class SchemaRevision:
    """Schema-only baseline revision plus the per-member digests behind it."""

    revision: str
    config_digest: str = ""
    members: dict[str, str] = field(default_factory=dict)

    def matches(self, other: "SchemaRevision | None") -> bool:
        return other is not None and self.revision == other.revision

    def changed_members(self, other: "SchemaRevision | None") -> list[str]:
        """Members whose digest differs (added, removed and edited alike)."""
        if other is None:
            return sorted(self.members)
        keys = sorted(set(self.members) | set(other.members))
        return [key for key in keys if self.members.get(key) != other.members.get(key)]

    def to_payload(self) -> dict[str, Any]:
        return {"revision": self.revision, "members": dict(sorted(self.members.items()))}


@dataclass(frozen=True)
class SchemaSources:
    """Bytes captured in one pass together with the revision they hash to."""

    revision: SchemaRevision
    contents: dict[Path, bytes] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return self.revision.to_payload()


def schema_yaml_paths(config) -> list[Path]:
    """Every ``*.yaml`` member of the configured schemas and types directories."""
    paths: list[Path] = []
    for directory in (config.resolve("schemas_dir"), config.resolve("types_dir")):
        directory = Path(directory)
        if directory.exists():
            paths.extend(sorted(directory.glob("*.yaml")))
    return paths


def build_schema_revision(config, *, contents: "dict[Path, bytes] | None" = None) -> SchemaRevision:
    """Hash the schema baseline, optionally from already-captured bytes."""
    if contents is None:
        contents = capture_schema_contents(config)
    config_file = config_file_path(config)
    schemas_dir = Path(config.resolve("schemas_dir"))
    types_dir = Path(config.resolve("types_dir"))
    members: dict[str, str] = {}
    for path, data in contents.items():
        path = Path(path)
        if path == config_file:
            continue
        label = "schemas" if path.parent == schemas_dir else "types"
        members[f"{label}/{path.name}"] = _sha256(data)
    config_digest = _sha256(contents.get(config_file, b""))
    payload = {
        "format": SCHEMA_REVISION_FORMAT,
        "config": config_digest,
        "members": members,
    }
    revision = _sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    return SchemaRevision(revision=revision, config_digest=config_digest, members=members)


def capture_schema_contents(config) -> dict[Path, bytes]:
    """Read ``global.yaml`` and every schema/type YAML exactly once."""
    contents: dict[Path, bytes] = {}
    config_file = config_file_path(config)
    if config_file.exists():
        contents[config_file] = config_file.read_bytes()
    for path in schema_yaml_paths(config):
        contents[path] = path.read_bytes()
    return contents


def capture_schema_sources(config) -> SchemaSources:
    """Capture the schema baseline bytes and the revision describing them.

    Callers load the workspace from ``contents`` (``CanonicalWorkspace.load``
    accepts captured bytes) so the revision can never describe a different
    source state than the resources actually used to build a candidate.
    """
    contents = capture_schema_contents(config)
    return SchemaSources(revision=build_schema_revision(config, contents=contents), contents=contents)
