"""Layered fingerprint tests: translation-only edits, language sets, reuse."""

from __future__ import annotations

from ct.cache.fingerprints import (
    ArtifactFingerprints,
    bundle_fingerprint,
    data_fingerprint,
    decide_artifact_reuse,
    effective_translation_semantics,
    i18n_fingerprint,
    schema_fingerprint,
)


def _table_payload() -> dict:
    return {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}


def _schema() -> str:
    return schema_fingerprint(_table_payload(), [], [], codegen_version="v4.1")


def _data(schema: str, excel: str = "e1") -> str:
    return data_fingerprint(schema, excel, parsing_inputs={"separator": ","})


def _en_entries() -> dict:
    return {
        "1.Name": {"source": "铁剑", "text": "Iron Sword", "confirmed": True, "status": "translated"},
        "2.Name": {"source": "魔杖", "text": "", "confirmed": False, "status": "missing"},
    }


def _en_fp(data: str, entries=None) -> str:
    return i18n_fingerprint(
        data,
        lang="en",
        primary_lang="zh",
        enabled_langs=["en", "ja"],
        valid_keys={"1.Name", "2.Name"},
        entries=entries if entries is not None else _en_entries(),
    )


def test_translation_only_edit_changes_only_en_i18n() -> None:
    schema = _schema()
    data = _data(schema)
    before = _en_fp(data)
    changed = _en_entries()
    changed["1.Name"] = {"source": "铁剑", "text": "Holy Sword", "confirmed": True}
    after = _en_fp(data, changed)

    assert before != after
    assert schema == _schema()  # schema untouched
    assert data == _data(schema)  # data untouched
    # ja fingerprint with identical semantics is unchanged
    ja = i18n_fingerprint(
        data, lang="ja", primary_lang="zh", enabled_langs=["en", "ja"],
        valid_keys={"1.Name", "2.Name"}, entries=_en_entries(),
    )
    ja_again = i18n_fingerprint(
        data, lang="ja", primary_lang="zh", enabled_langs=["en", "ja"],
        valid_keys={"1.Name", "2.Name"}, entries=dict(_en_entries()),
    )
    assert ja == ja_again


def test_confirmed_toggle_changes_fingerprint() -> None:
    data = _data(_schema())
    stale = dict(_en_entries())
    stale["1.Name"] = {"source": "铁剑", "text": "Iron Sword", "confirmed": False}
    assert _en_fp(data, stale) != _en_fp(data, _en_entries())


def test_derived_metadata_does_not_change_fingerprint() -> None:
    data = _data(_schema())
    base = _en_entries()
    reformatted = {key: {**entry, "status": "unused", "source": "改过但相同"} for key, entry in base.items()}
    assert _en_fp(data, reformatted) == _en_fp(data, base)


def test_orphan_and_unknown_keys_ignored() -> None:
    data = _data(_schema())
    base = _en_entries()
    with_orphan = dict(base)
    with_orphan["999.Gone"] = {"text": "旧", "confirmed": True, "status": "orphan"}
    assert _en_fp(data, with_orphan) == _en_fp(data, base)


def test_language_config_change_detected() -> None:
    data = _data(_schema())
    one_lang = i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=["en"],
        valid_keys={"1.Name", "2.Name"}, entries=_en_entries(),
    )
    two_langs = _en_fp(data)
    assert one_lang != two_langs


def test_missing_file_means_empty_semantics() -> None:
    data = _data(_schema())
    empty = i18n_fingerprint(
        data, lang="en", primary_lang="zh", enabled_langs=["en"],
        valid_keys={"1.Name", "2.Name"}, entries={},
    )
    assert empty != _en_fp(data)


def test_data_change_changes_all_languages() -> None:
    schema = _schema()
    old_data = _data(schema)
    new_data = _data(schema, excel="e2")
    assert _en_fp(old_data) != _en_fp(new_data)
    ja = lambda d: i18n_fingerprint(
        d, lang="ja", primary_lang="zh", enabled_langs=["en", "ja"],
        valid_keys={"1.Name", "2.Name"}, entries=_en_entries(),
    )
    assert ja(old_data) != ja(new_data)


def test_excel_layout_change_does_not_touch_schema_wire() -> None:
    schema = _schema()
    schema_layout = data_fingerprint(schema, "e1", parsing_inputs={"separator": ";"})
    schema_wire = schema_fingerprint(_table_payload(), [], [], codegen_version="v4.1")
    assert schema_layout != _data(schema)
    assert schema_wire == schema  # wire (FBS/Accessor) contract unchanged


def test_decide_artifact_reuse_split() -> None:
    schema = _schema()
    data = _data(schema)
    previous = ArtifactFingerprints(
        schema=schema,
        data=data,
        i18n={"en": _en_fp(data), "ja": "ja-old"},
    )
    current_en_only = ArtifactFingerprints(
        schema=schema,
        data=data,
        i18n={"en": "en-new", "ja": "ja-old"},
    )
    decision = decide_artifact_reuse(previous, current_en_only, langs=["en", "ja"])
    assert decision.schema_reusable is True
    assert decision.data_reusable is True
    assert decision.i18n_reusable == {"en": False, "ja": True}


def test_bundle_fingerprint_is_language_scoped() -> None:
    hashes = [("Item", "a"), ("Quest", "b")]
    en = bundle_fingerprint("en", hashes)
    en_same = bundle_fingerprint("en", list(reversed(hashes)))
    ja = bundle_fingerprint("ja", hashes)
    assert en == en_same  # deterministic table ordering
    assert en != ja


def test_transitive_shared_type_change_invalidates_dependent_schema() -> None:
    table = _table_payload()
    before = schema_fingerprint(table, [{"name": "DropReward", "fields": [{"name": "Min", "type": "int32"}]}], [], codegen_version="v4.1")
    after = schema_fingerprint(table, [{"name": "DropReward", "fields": [{"name": "Min", "type": "int32"}, {"name": "Max", "type": "int32"}]}], [], codegen_version="v4.1")
    assert before != after
    assert data_fingerprint(before, "e1", parsing_inputs={}) != data_fingerprint(after, "e1", parsing_inputs={})
