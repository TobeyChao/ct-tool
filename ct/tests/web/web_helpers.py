"""Shared canonical workspace builders for web tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def build_project(
    root: Path,
    *,
    schemas: list[dict[str, Any]] | None = None,
    types: list[dict[str, Any]] | None = None,
) -> Path:
    """Build a minimal canonical workspace (config + optional schemas/types)."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "config" / "types").mkdir(parents=True, exist_ok=True)
    write_yaml(
        root / "config" / "global.yaml",
        {
            "primary_lang": "zh",
            "secondary_langs": ["en"],
        },
    )
    for schema in schemas or []:
        write_yaml(root / "config" / "schemas" / f"{schema['table']}.yaml", schema)
    for type_def in types or []:
        write_yaml(root / "config" / "types" / f"{type_def['name']}.yaml", type_def)
    return root
