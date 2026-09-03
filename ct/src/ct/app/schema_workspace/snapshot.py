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

SNAPSHOT_FORMAT = "workspace-snapshot-v4/1"


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
