"""Versioned canonical cache state with layered fingerprints.

Stores per-table ``ArtifactFingerprints``, per-language Bundle fingerprints,
layout revisions and the last-seen Excel file hash in ``cache/state.json``.
The ``excel_hashes`` ledger powers ``ct status`` data-change detection: a table
is reported as ``changed`` (pending export) when its current Excel hash differs
from the recorded one. Any version mismatch, missing field or corrupt file
fails safe to ``None`` so callers rebuild instead of trusting stale entries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ct.cache.fingerprints import ArtifactFingerprints

CACHE_STATE_VERSION = "canonical-cache/1"


@dataclass(frozen=True)
class CanonicalCacheState:
    format: str = CACHE_STATE_VERSION
    tables: dict[str, ArtifactFingerprints] = field(default_factory=dict)
    bundles: dict[str, str] = field(default_factory=dict)  # lang -> bundle fp
    layout_revisions: dict[str, int] = field(default_factory=dict)  # table -> revision
    excel_hashes: dict[str, str] = field(default_factory=dict)  # table -> excel sha256


def _path(cache_dir: Path) -> Path:
    return cache_dir / "state.json"


def load_state(cache_dir: Path) -> CanonicalCacheState | None:
    path = _path(cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format") != CACHE_STATE_VERSION:
        return None
    raw_tables = data.get("tables", {})
    raw_bundles = data.get("bundles", {})
    raw_revisions = data.get("layout_revisions", {})
    raw_excel = data.get("excel_hashes", {})
    if not all(
        isinstance(value, dict)
        for value in (raw_tables, raw_bundles, raw_revisions, raw_excel)
    ):
        return None
    try:
        tables = {
            name: ArtifactFingerprints(
                schema=item["schema"],
                data=item["data"],
                i18n=dict(item.get("i18n", {})),
            )
            for name, item in data.get("tables", {}).items()
        }
        return CanonicalCacheState(
            tables=tables,
            bundles=dict(raw_bundles),
            layout_revisions=dict(raw_revisions),
            excel_hashes=dict(raw_excel),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_state(cache_dir: Path, state: CanonicalCacheState) -> Path:
    path = _path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": state.format,
        "tables": {
            name: {
                "schema": fps.schema,
                "data": fps.data,
                "i18n": fps.i18n,
            }
            for name, fps in sorted(state.tables.items())
        },
        "bundles": dict(sorted(state.bundles.items())),
        "layout_revisions": dict(sorted(state.layout_revisions.items())),
        "excel_hashes": dict(sorted(state.excel_hashes.items())),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def upsert_table(
    state: CanonicalCacheState,
    table: str,
    fingerprints: ArtifactFingerprints,
    *,
    layout_revision: int | None = None,
) -> CanonicalCacheState:
    tables = dict(state.tables)
    tables[table] = fingerprints
    revisions = dict(state.layout_revisions)
    if layout_revision is not None:
        revisions[table] = layout_revision
    return CanonicalCacheState(
        tables=tables,
        bundles=state.bundles,
        layout_revisions=revisions,
        excel_hashes=state.excel_hashes,
    )


def upsert_bundle(state: CanonicalCacheState, lang: str, fingerprint: str) -> CanonicalCacheState:
    bundles = dict(state.bundles)
    bundles[lang] = fingerprint
    return CanonicalCacheState(
        tables=state.tables,
        bundles=bundles,
        layout_revisions=state.layout_revisions,
        excel_hashes=state.excel_hashes,
    )


def record_excel_hashes(
    state: CanonicalCacheState,
    hashes: dict[str, str],
    *,
    layout_revisions: dict[str, int] | None = None,
) -> CanonicalCacheState:
    """Record the last-seen Excel hash (and optional layout revisions) per table."""
    excel = dict(state.excel_hashes)
    excel.update(hashes)
    revisions = dict(state.layout_revisions)
    if layout_revisions:
        revisions.update(layout_revisions)
    return CanonicalCacheState(
        tables=state.tables,
        bundles=state.bundles,
        layout_revisions=revisions,
        excel_hashes=excel,
    )
