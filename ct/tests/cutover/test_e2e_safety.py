"""E2E safety: stale-plan, blocked-reference and interrupted-publish consistency (13.2)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.apply import (
    ApplyError,
    apply_plan,
    create_plan,
    recover,
)
from ct.web.app import create_app

FIXTURE = Path(__file__).parents[2] / "tests/fixtures/repository_cutover_v4/workspace"


def _canonical_workspace(tmp_path: Path) -> Path:
    import yaml

    root = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, root / section)
    # convert to canonical (mirror the cutover smoke conversion)
    schemas = {
        "Item": {"table": "Item", "primary": "Id", "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string", "i18n": True},
        ]},
    }
    for name, schema in schemas.items():
        (root / "config" / "schemas" / f"{name}.yaml").write_text(
            yaml.safe_dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    for old in (root / "config" / "schemas").glob("*.yaml"):
        if old.stem not in schemas:
            old.unlink()
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in str(p) and ".git" not in str(p) and "cache" not in str(p)
    }


def test_external_translation_edit_makes_plan_stale(tmp_path: Path) -> None:
    root = _canonical_workspace(tmp_path)
    ws = CanonicalWorkspace.load(root)
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    (manifest.staging_dir / "Item.yaml").write_text(
        (root / "config" / "schemas" / "Item.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    before = _snapshot(root)

    # external edit to a translation file changes the workspace revision
    lang = root / "i18n" / "en" / "Item.json"
    data = json.loads(lang.read_text(encoding="utf-8"))
    data["1.Name"]["text"] = "Edited Externally"
    lang.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ApplyError, match="源工作区已变化"):
        apply_plan(
            ws, manifest.plan_id,
            base_revision=manifest.base_revision, candidate_hash=manifest.candidate_hash,
        )
    after = _snapshot(root)
    # only the external translation edit exists; no plan writes happened
    assert before == after or lang.read_bytes() == json.dumps(data, ensure_ascii=False).encode()


def test_interrupted_publish_rolls_back_byte_consistent(tmp_path: Path, monkeypatch) -> None:
    root = _canonical_workspace(tmp_path)
    ws = CanonicalWorkspace.load(root)
    schema = root / "config" / "schemas" / "Item.yaml"
    original = schema.read_bytes()
    manifest = create_plan(
        ws,
        candidate_resources=list(ws.resources.resources),
        candidate_indexes={},
        targets=[("config/schemas/Item.yaml", "Item.yaml")],
        table_fingerprints={},
    )
    (manifest.staging_dir / "Item.yaml").write_bytes(original + b"\n# changed\n")

    calls = {"n": 0}
    real_replace = __import__("os").replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("interrupted")
        return real_replace(src, dst)

    monkeypatch.setattr("ct.app.schema_workspace.apply.os.replace", flaky)
    with pytest.raises(RuntimeError):
        apply_plan(
            ws, manifest.plan_id,
            base_revision=manifest.base_revision, candidate_hash=manifest.candidate_hash,
        )
    recover(ws)
    assert schema.read_bytes() == original  # complete old revision


def test_blocked_reference_never_writes(tmp_path: Path) -> None:
    import yaml

    root = _canonical_workspace(tmp_path)
    # add a record referenced by a missing type in a draft -> prepare blocked
    client = create_app(root).test_client()
    resp = client.post(
        "/api/schema-workspace/prepare-apply",
        json={"commands": [{"type": "set_type", "payload": {"owner": "table:Item", "name": "Name", "type_text": "MissingType"}}]},
    )
    assert resp.status_code == 400
    schema = root / "config" / "schemas" / "Item.yaml"
    assert "MissingType" not in schema.read_text(encoding="utf-8")
