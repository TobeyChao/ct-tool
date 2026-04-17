from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


CURRENT_VERSION = 2


class TableCache(BaseModel):
    hash: str
    ids: list[int]
    fbs_bytes_hash: str | None = None
    schema_hash: str | None = None
    exported_at: str = ""


class CacheState(BaseModel):
    version: int = CURRENT_VERSION
    tables: dict[str, TableCache] = {}


# ---------------------------------------------------------------------------
# Task 5.1 – Read / write cache/state.json
# ---------------------------------------------------------------------------

def load_cache(cache_dir: Path) -> CacheState:
    """Load cache state from *cache_dir*/state.json.

    Returns an empty ``CacheState`` when the file does not exist or the
    persisted ``version`` does not match ``CURRENT_VERSION``.
    """
    state_file = cache_dir / "state.json"
    if not state_file.exists():
        return CacheState()
    try:
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return CacheState()
    if data.get("version") != CURRENT_VERSION:
        return CacheState()
    return CacheState.model_validate(data)


def save_cache(cache_state: CacheState, cache_dir: Path) -> None:
    """Persist *cache_state* to *cache_dir*/state.json."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_file = cache_dir / "state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(
            cache_state.model_dump(),
            f,
            ensure_ascii=False,
            indent=2,
        )


# ---------------------------------------------------------------------------
# Task 5.2 – Update logic
# ---------------------------------------------------------------------------

def update_table_cache(
    cache: CacheState,
    table_name: str,
    hash: str,
    ids: list[int],
    fbs_bytes_hash: str | None = None,
    schema_hash: str | None = None,
) -> None:
    """Record a successful export for *table_name* in *cache* (in-place).

    ``schema_hash`` is preserved across calls that omit it, so callers that
    only update file/fbs hashes don't need to know about the schema fingerprint.
    """
    existing = cache.tables.get(table_name)
    cache.tables[table_name] = TableCache(
        hash=hash,
        ids=ids,
        fbs_bytes_hash=fbs_bytes_hash,
        schema_hash=schema_hash if schema_hash is not None
                    else (existing.schema_hash if existing else None),
        exported_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def update_schema_hash(cache: CacheState, table_name: str, schema_hash: str) -> None:
    """Record only the schema_hash for *table_name* (used by ``gen-template``)."""
    existing = cache.tables.get(table_name)
    if existing is None:
        # Create a placeholder entry — the file/fbs hashes will be filled
        # in by the next ``ct export`` run.
        cache.tables[table_name] = TableCache(
            hash="", ids=[], schema_hash=schema_hash,
        )
    else:
        cache.tables[table_name] = existing.model_copy(update={"schema_hash": schema_hash})


# ---------------------------------------------------------------------------
# Task 5.3 – Read id sets from cache
# ---------------------------------------------------------------------------

def get_cached_ids(cache: CacheState, table_name: str) -> set[int] | None:
    """Return the set of cached IDs for *table_name*, or ``None`` if absent."""
    entry = cache.tables.get(table_name)
    if entry is None:
        return None
    return set(entry.ids)


# ---------------------------------------------------------------------------
# Task 5.4 – Reuse FlatBuffers bytes
# ---------------------------------------------------------------------------

_FBS_BYTES_DIR = "fbs_bytes"


def save_fbs_bytes(cache_dir: Path, table_name: str, data: bytes) -> None:
    """Save raw FlatBuffers bytes to ``cache_dir/fbs_bytes/<table>.bin``."""
    fbs_dir = cache_dir / _FBS_BYTES_DIR
    fbs_dir.mkdir(parents=True, exist_ok=True)
    (fbs_dir / f"{table_name}.bin").write_bytes(data)


def load_fbs_bytes(cache_dir: Path, table_name: str) -> bytes | None:
    """Load cached FlatBuffers bytes.  Returns ``None`` if the file is absent."""
    bin_path = cache_dir / _FBS_BYTES_DIR / f"{table_name}.bin"
    if not bin_path.exists():
        return None
    return bin_path.read_bytes()


def get_fbs_bytes_hash(cache: CacheState, table_name: str) -> str | None:
    """Return the stored FBS bytes hash for *table_name*, or ``None``."""
    entry = cache.tables.get(table_name)
    if entry is None:
        return None
    return entry.fbs_bytes_hash
