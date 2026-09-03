"""Layered export fingerprints for the canonical v4 pipeline.

Artifacts are invalidated by exactly the inputs that change them, never by a
single all-or-nothing fingerprint:

- ``schema_fingerprint`` controls shared/table FBS + C#/Lua Accessor:
  Table canonical schema + transitive Record/Enum + query indexes +
  schema/codegen format version;
- ``data_fingerprint`` controls primary JSON + main-table bytes:
  schema fingerprint + Excel content + parsing/layout inputs;
- ``i18n_fingerprints[lang]`` controls that language's JSON + i18n bytes:
  data fingerprint + language config + **effective translation semantics**
  (valid source keys' text/confirmed) + merge policy version;
- ``bundle_fingerprints[lang]`` controls that language's Bundle.

Derived ``status``/``source``, orphan entries, JSON whitespace and key order
never participate in any fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

SCHEMA_FMT_VERSION = "schema-fp-v4/1"
DATA_FMT_VERSION = "data-fp-v4/1"
I18N_FMT_VERSION = "i18n-fp-v4/1"
BUNDLE_FMT_VERSION = "bundle-fp-v4/1"
MERGE_POLICY_VERSION = "merge-v1"
BUNDLE_CONTAINER_VERSION = "bundle-container-v4/1"


def _stable_sha256(data: object) -> str:
    serialized = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def schema_fingerprint(
    table: dict[str, Any],
    transitive_dependencies: list[dict[str, Any]],
    indexes: list[dict[str, Any]],
    *,
    codegen_version: str,
) -> str:
    """Fingerprint for FBS + Accessor artifacts (wire/schema level)."""
    return _stable_sha256(
        {
            "format": SCHEMA_FMT_VERSION,
            "codegen": codegen_version,
            "table": table,
            "dependencies": sorted(transitive_dependencies, key=str),
            "indexes": indexes,
        }
    )


def data_fingerprint(
    schema_fingerprint_value: str,
    excel_hash: str,
    *,
    parsing_inputs: dict[str, Any],
) -> str:
    """Fingerprint for primary JSON + main-table bytes."""
    return _stable_sha256(
        {
            "format": DATA_FMT_VERSION,
            "schema": schema_fingerprint_value,
            "excel": excel_hash,
            "parsing": parsing_inputs,
        }
    )


def effective_translation_semantics(
    entries: dict[str, dict[str, Any]],
    valid_keys: set[str],
) -> tuple[tuple[str, str, bool], ...]:
    """Only valid keys' ``text`` + ``confirmed`` (never derived status/source)."""
    semantics: list[tuple[str, str, bool]] = []
    for key in sorted(valid_keys):
        entry = entries.get(key)
        if entry is None:
            continue
        semantics.append((key, str(entry.get("text", "")), bool(entry.get("confirmed", False))))
    return tuple(semantics)


def i18n_fingerprint(
    data_fingerprint_value: str,
    *,
    lang: str,
    primary_lang: str,
    enabled_langs: Iterable[str],
    valid_keys: set[str],
    entries: dict[str, dict[str, Any]],
    merge_policy_version: str = MERGE_POLICY_VERSION,
) -> str:
    """Fingerprint for one language's JSON + i18n bytes."""
    return _stable_sha256(
        {
            "format": I18N_FMT_VERSION,
            "data": data_fingerprint_value,
            "lang": lang,
            "primary_lang": primary_lang,
            "enabled_langs": sorted(enabled_langs),
            "merge_policy": merge_policy_version,
            "semantics": effective_translation_semantics(entries, valid_keys),
        }
    )


def bundle_fingerprint(
    lang: str,
    table_bytes_hashes: Iterable[tuple[str, str]],
    *,
    container_version: str = BUNDLE_CONTAINER_VERSION,
) -> str:
    """Fingerprint for one language's Binary Bundle."""
    return _stable_sha256(
        {
            "format": BUNDLE_FMT_VERSION,
            "lang": lang,
            "container": container_version,
            "tables": sorted(table_bytes_hashes),
        }
    )


@dataclass(frozen=True)
class ArtifactFingerprints:
    """Per-table fingerprint set as stored in the cache state."""

    schema: str
    data: str
    i18n: dict[str, str] = field(default_factory=dict)  # lang -> fingerprint

    def for_lang(self, lang: str) -> str | None:
        return self.i18n.get(lang)


@dataclass(frozen=True)
class ReuseDecision:
    """Which artifacts may be reused for one Table."""

    schema_reusable: bool  # FBS + Accessor
    data_reusable: bool  # primary JSON + main bytes
    i18n_reusable: dict[str, bool]  # lang -> language artifacts reusable


def decide_artifact_reuse(
    previous: ArtifactFingerprints | None,
    current: ArtifactFingerprints,
    *,
    langs: Iterable[str],
) -> ReuseDecision:
    """Compare previous cached fingerprints with the current candidate."""
    if previous is None:
        return ReuseDecision(
            schema_reusable=False,
            data_reusable=False,
            i18n_reusable={lang: False for lang in langs},
        )
    schema_reusable = previous.schema == current.schema
    data_reusable = previous.data == current.data
    i18n_reusable: dict[str, bool] = {}
    for lang in langs:
        prev_lang = previous.i18n.get(lang)
        i18n_reusable[lang] = data_reusable and prev_lang is not None and prev_lang == current.i18n.get(lang)
    return ReuseDecision(
        schema_reusable=schema_reusable,
        data_reusable=data_reusable,
        i18n_reusable=i18n_reusable,
    )


def synced_i18n_fingerprint(
    data_fingerprint_value: str,
    *,
    lang: str,
    primary_lang: str,
    enabled_langs: Iterable[str],
    source_data: dict[str, str],
    lang_entries: dict[str, dict[str, Any]],
    merge_policy_version: str = MERGE_POLICY_VERSION,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Run the canonical sync state machine, then fingerprint the result.

    When the primary-language source text changed, sync forces ``confirmed``
    to ``False`` (the entry becomes stale) *before* hashing, so the stored
    fingerprint matches the fallback output actually written and does not
    immediately self-invalidate.
    """
    from ct.export.i18n.state import sync_lang_table

    synced = sync_lang_table(source_data, lang_entries)
    fingerprint = i18n_fingerprint(
        data_fingerprint_value,
        lang=lang,
        primary_lang=primary_lang,
        enabled_langs=enabled_langs,
        valid_keys=set(source_data.keys()),
        entries=synced,
        merge_policy_version=merge_policy_version,
    )
    return fingerprint, synced
