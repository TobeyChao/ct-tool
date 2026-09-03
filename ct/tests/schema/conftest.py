"""Shared  canonical workspace fixtures for schema tests."""

from __future__ import annotations

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace

from _helpers import build_project


@pytest.fixture
def _project(tmp_path):
    return build_project(tmp_path)


@pytest.fixture
def load(tmp_path):
    def _load(schemas=None, types=None) -> CanonicalWorkspace:
        root = build_project(tmp_path / "gd", schemas=schemas, types=types)
        return CanonicalWorkspace.load(root)

    return _load
