"""Transactional apply + recovery tests (7.1-7.4, 7.8)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.apply import (
    ApplyError,
    WorkspaceApplyLock,
    apply_plan,
    create_plan,
    load_plan,
    preflight_writable,
    recover,
    validate_plan_stale,
)
from ct.app.schema_workspace.snapshot import build_snapshot

from _v4_helpers import build_v4_project


def _ws(tmp_path: Path) -> CanonicalWorkspace:
    root = build_v4_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32", "comment": "a"}],
            }
        ],
    )
    return CanonicalWorkspace.load(root)


def test_create_plan_and_stale_detection(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    assert manifest.plan_id
    assert load_plan(ws, manifest.plan_id) is not None

    # wrong base revision -> stale before any write
    with pytest.raises(ApplyError, match="源工作区已变化"):
        apply_plan(
            ws, manifest.plan_id,
            base_revision="stale-revision", candidate_hash=manifest.candidate_hash,
        )


def test_expired_plan_rejected(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    from ct.app.schema_workspace.apply import PlanManifest

    expired = PlanManifest(
        plan_id=manifest.plan_id,
        base_revision=manifest.base_revision,
        candidate_hash=manifest.candidate_hash,
        created_at=manifest.created_at,
        expires_at=time.time() - 1,
        staging_dir=manifest.staging_dir,
        targets=manifest.targets,
        table_fingerprints=manifest.table_fingerprints,
    )
    assert expired.is_expired()
    with pytest.raises(ApplyError, match="已过期"):
        validate_plan_stale(
            ws, expired,
            base_revision=expired.base_revision, candidate_hash=expired.candidate_hash,
        )


def test_apply_publishes_new_files_and_keeps_consistency(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    staged_schema = tmp_path / "gd" / "config" / "schemas" / "Item.yaml"
    old_content = staged_schema.read_text(encoding="utf-8")
    new_content = old_content.replace("comment: a", "comment: b")

    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    (manifest.staging_dir / "Item.yaml").write_text(new_content, encoding="utf-8")

    result = apply_plan(
        ws, manifest.plan_id,
        base_revision=manifest.base_revision, candidate_hash=manifest.candidate_hash,
    )
    assert result["published"] == ["config/schemas/Item.yaml"]
    assert staged_schema.read_text(encoding="utf-8") == new_content
    # plan consumed after success
    assert load_plan(ws, manifest.plan_id) is None


def test_apply_lock_serializes(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    with WorkspaceApplyLock(ws):
        with pytest.raises(ApplyError, match="占用"):
            with WorkspaceApplyLock(ws):
                pass


def test_recovery_rolls_back_partial_publish(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    schema = tmp_path / "gd" / "config" / "schemas" / "Item.yaml"
    original = schema.read_text(encoding="utf-8")
    new_content = original.replace("comment: a", "comment: b")

    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    (manifest.staging_dir / "Item.yaml").write_text(new_content, encoding="utf-8")

    # simulate a crash during publish: os.replace raises halfway
    calls = {"n": 0}
    real_replace = __import__("os").replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("模拟中断")
        return real_replace(src, dst)

    monkeypatch.setattr("ct.app.schema_workspace.apply.os.replace", flaky_replace)
    with pytest.raises(RuntimeError, match="模拟中断"):
        apply_plan(
            ws, manifest.plan_id,
            base_revision=manifest.base_revision, candidate_hash=manifest.candidate_hash,
        )

    # journal exists -> recover rolls back to the complete old revision
    journal = ws.resolve("cache_dir") / "apply.journal.json"
    assert journal.exists()
    reports = recover(ws)
    assert any("old revision" in report for report in reports)
    assert schema.read_text(encoding="utf-8") == original
    assert not journal.exists()


def test_preflight_reports_blocked_targets(tmp_path: Path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    # simulate a read-only (locked) target
    schema = tmp_path / "gd" / "config" / "schemas" / "Item.yaml"
    monkeypatch.setattr("ct.app.schema_workspace.apply.os.access", lambda path, mode: False)
    with pytest.raises(ApplyError, match="不可写或正被占用"):
        preflight_writable(ws, manifest)
    assert schema.read_text(encoding="utf-8")  # untouched
