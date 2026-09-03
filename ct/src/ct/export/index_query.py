"""Production index hash and exact-string bucket queries.

The hash is a fixed FNV-1a 64-bit over the reader's exact UTF-8 string with
no trim, case folding or Unicode normalization. Lookups only walk the hash
bucket and confirm with ordinal string equality — different strings that
share a hash are never treated as a hit.
"""

from __future__ import annotations

from typing import Any, Callable

from ct.schema.indexes import QueryIndex

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK = 0xFFFFFFFFFFFFFFFF


def fnv1a_64(text: str) -> int:
    """Deterministic, non-random production hash over exact UTF-8 bytes."""
    value = _FNV_OFFSET
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * _FNV_PRIME) & _MASK
    return value


HashProvider = Callable[[str], int]


def production_hash(text: str) -> int:
    return fnv1a_64(text)


class StringIndex:
    """hash -> list of (exact_string, row_index); ordinal confirmation required."""

    def __init__(
        self,
        buckets: dict[int, list[tuple[str, int]]],
        *,
        hash_provider: HashProvider,
    ) -> None:
        self.buckets = buckets
        self.hash_provider = hash_provider

    @classmethod
    def build(
        cls,
        rows: list[dict[str, Any]],
        field: str,
        *,
        hash_provider: HashProvider = production_hash,
    ) -> "StringIndex":
        buckets: dict[int, list[tuple[str, int]]] = {}
        for row_index, row in enumerate(rows):
            value = row.get(field)
            if value is None:
                continue
            text = str(value)
            buckets.setdefault(hash_provider(text), []).append((text, row_index))
        return cls(buckets, hash_provider=hash_provider)

    def lookup(self, value: str) -> list[int]:
        """Return row indices whose exact string equals *value* (bucket-local)."""
        bucket = self.buckets.get(self.hash_provider(value), ())
        return [row_index for text, row_index in bucket if text == value]

    def exact_strings(self, value: str) -> list[str]:
        return [text for text, _ in self.buckets.get(self.hash_provider(value), ())]


def validate_code_index(
    rows: list[dict[str, Any]],
    index: QueryIndex,
    *,
    hash_provider: HashProvider = production_hash,
) -> list[tuple[int, str]]:
    """Return (row_index, duplicate) for every duplicated exact Code value."""
    seen: dict[str, int] = {}
    duplicates: list[tuple[int, str]] = []
    for row_index, row in enumerate(rows):
        value = row.get(index.field)
        if value is None or str(value) == "":
            continue
        text = str(value)
        if text in seen:
            duplicates.append((row_index, text))
        else:
            seen[text] = row_index
    return duplicates
