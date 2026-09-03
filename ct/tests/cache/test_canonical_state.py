"""Sync-then-fingerprint flow and canonical cache state tests (5.13 + cache)."""

from __future__ import annotations

from pathlib import Path

from ct.cache.canonical_state import (
    CanonicalCacheState,
    load_state,
    save_state,
    upsert_bundle,
    upsert_table,
)
from ct.cache.fingerprints import (
    ArtifactFingerprints,
    data_fingerprint,
    schema_fingerprint,
    synced_i18n_fingerprint,
)

_LANGS = ["en", "ja"]


def _source(sword: str = "铁剑") -> dict:
    return {"1.Name": sword, "2.Name": "魔杖"}


def _lang_entries(confirmed_sword: bool = True) -> dict:
    return {
        "1.Name": {"source": "铁剑", "text": "Iron Sword", "confirmed": confirmed_sword},
        "2.Name": {"source": "魔杖", "text": "Wand", "confirmed": True},
    }


def _data() -> str:
    schema = schema_fingerprint({"table": "Item"}, [], [], codegen_version="")
    return data_fingerprint(schema, "e1", parsing_inputs={})


def test_source_change_forces_stale_before_hashing() -> None:
    data = _data()
    # old confirmed translation exists; source text changes 铁剑 -> 神剑
    old_entries = _lang_entries(confirmed_sword=True)
    before, synced_old = synced_i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=_LANGS,
        source_data=_source("铁剑"), lang_entries=old_entries,
    )
    assert synced_old["1.Name"]["confirmed"] is True

    after, synced_new = synced_i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=_LANGS,
        source_data=_source("神剑"), lang_entries=old_entries,
    )
    assert synced_new["1.Name"]["source"] == "神剑"
    assert synced_new["1.Name"]["confirmed"] is False  # forced stale by sync
    assert after != before


def test_published_fingerprint_does_not_self_invalidate() -> None:
    data = _data()
    # first export writes the synced entries; the stored fp must equal the
    # recomputed fp over those same written entries (no immediate expiry)
    _, synced = synced_i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=_LANGS,
        source_data=_source("神剑"), lang_entries=_lang_entries(True),
    )
    stored, _ = synced_i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=_LANGS,
        source_data=_source("神剑"), lang_entries=synced,  # the file as written
    )
    assert stored == _i18n_over_synced(data, synced)


def _i18n_over_synced(data: str, synced: dict) -> str:
    from ct.cache.fingerprints import i18n_fingerprint

    return i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=_LANGS,
        valid_keys=set(_source("神剑").keys()), entries=synced,
    )


def test_canonical_state_round_trip(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    state = CanonicalCacheState()
    fps = ArtifactFingerprints(
        schema="s", data="d", i18n={"en": "e1", "ja": "j1"}
    )
    state = upsert_table(state, "Item", fps, layout_revision=2)
    state = upsert_bundle(state, "en", "bundle-en")

    saved = save_state(cache, state)
    assert saved.exists()
    loaded = load_state(cache)
    assert loaded is not None
    assert loaded.tables["Item"].schema == "s"
    assert loaded.tables["Item"].i18n == {"en": "e1", "ja": "j1"}
    assert loaded.layout_revisions["Item"] == 2
    assert loaded.bundles["en"] == "bundle-en"


def test_canonical_state_corruption_and_missing(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    assert load_state(cache) is None
    path = cache / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ broken", encoding="utf-8")
    assert load_state(cache) is None
    path.write_text('{"format":"canonical-cache/1","tables":1}', encoding="utf-8")
    assert load_state(cache) is None
