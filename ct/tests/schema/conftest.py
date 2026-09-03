"""Shared v4 canonical workspace fixtures for schema tests."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace

from _v4_helpers import build_v4_project


@pytest.fixture
def v4_project(tmp_path):
    return build_v4_project(tmp_path)


@pytest.fixture
def load_v4(tmp_path):
    def _load(schemas=None, types=None) -> CanonicalWorkspace:
        root = build_v4_project(tmp_path / "gd", schemas=schemas, types=types)
        return CanonicalWorkspace.load(root)

    return _load
