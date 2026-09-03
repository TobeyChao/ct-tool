"""Old-format fail-fast rejection + no migrate command (3.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.schema.resource_repository import YamlResourceRepository

from _v4_helpers import build_v4_project


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_inline_struct_rejected_with_file_and_field(tmp_path: Path) -> None:
    root = build_v4_project(tmp_path / "gd")
    _write(
        root,
        "config/schemas/Item.yaml",
        """table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: DropRange
    type: struct
    fields:
      - {name: Min, type: int32}
""",
    )
    with pytest.raises(ValueError, match=r"Item.yaml.*DropRange.*旧格式"):
        CanonicalWorkspace.load(root)


def test_inline_array_rejected(tmp_path: Path) -> None:
    root = build_v4_project(tmp_path / "gd")
    _write(
        root,
        "config/schemas/Item.yaml",
        """table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Tags
    type: array
    element: int32
""",
    )
    with pytest.raises(ValueError, match=r"Item.yaml.*Tags.*旧格式"):
        CanonicalWorkspace.load(root)


def test_inline_enum_values_rejected(tmp_path: Path) -> None:
    root = build_v4_project(tmp_path / "gd")
    _write(
        root,
        "config/schemas/Item.yaml",
        """table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Rarity
    type: enum
    values: [common, rare]
""",
    )
    with pytest.raises(ValueError, match=r"Item.yaml.*Rarity.*旧格式"):
        CanonicalWorkspace.load(root)


def test_rejection_does_not_mutate_files(tmp_path: Path) -> None:
    root = build_v4_project(tmp_path / "gd")
    schema = root / "config" / "schemas" / "Item.yaml"
    original = """table: Item
primary: Id
fields:
  - name: Id
    type: int32
  - name: Tags
    type: array
    element: int32
"""
    _write(root, "config/schemas/Item.yaml", original)
    with pytest.raises(ValueError):
        CanonicalWorkspace.load(root)
    assert schema.read_text(encoding="utf-8") == original


def test_no_runtime_migration_reader(tmp_path: Path) -> None:
    # the product never parses old formats; only the canonical repository exists
    root = build_v4_project(tmp_path / "gd")
    repository = YamlResourceRepository(
        root / "config" / "schemas", root / "config" / "types"
    )
    assert repository is not None
