"""Detect which Excel files have changed since the last export by comparing
MD5 hashes against the cache state.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ct.schema.models import TableSchema

if TYPE_CHECKING:
    from ct.cache.state import CacheState

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 8192


def file_hash(path: Path) -> str:
    """Return the hex MD5 digest of the file at *path*."""
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def get_changed_tables(
    schemas: list[TableSchema],
    cache: CacheState,
    excel_dir: Path,
) -> list[str]:
    """Compare current Excel file hashes with cache and return changed table names."""
    changed: list[str] = []

    for schema in schemas:
        excel_path = excel_dir / schema.resolved_excel_file

        if not excel_path.exists():
            logger.warning("表 %s 的 Excel 文件不存在: %s", schema.table, excel_path)
            continue

        current_hash = file_hash(excel_path)
        cached_entry = cache.tables.get(schema.table)

        if cached_entry is None:
            logger.info("表 %s: 新文件", schema.table)
            changed.append(schema.table)
        elif current_hash != cached_entry.hash:
            logger.info("表 %s: 文件已变更", schema.table)
            changed.append(schema.table)
        else:
            logger.debug("表 %s: 文件未变更", schema.table)

    return changed
