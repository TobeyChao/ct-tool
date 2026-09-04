"""Canonical export smoke: run canonical export on the repository_cutover
fixture (canonical workspace) and assert the artifact tree is produced
(FBS/binary/accessors) plus the background task reports phases/history."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ct.app.canonical_export import run_canonical_export

FIXTURE = Path(__file__).parents[2] / "tests/fixtures/repository_cutover/workspace"


def test_canonical_export_writes_fbs_binary_accessors(tmp_path: Path) -> None:
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    run_canonical_export(workspace)
    fbs = workspace / "output" / "fbs"
    assert (fbs / "types.fbs").exists()
    assert "enum ItemRarity : byte" in (fbs / "types.fbs").read_text(encoding="utf-8")
    assert (fbs / "Item.fbs").exists()
    binary = workspace / "output" / "binary"
    for lang in ("zh", "en", "ja"):
        assert (binary / f"data_{lang}.bin").exists()
    generated = workspace / "output" / "generated"
    assert (generated / "csharp" / "ItemAccessor.cs").exists()
    assert (generated / "lua" / "ItemAccessor.lua").exists()


def test_canonical_export_task_reports_phases_and_history(tmp_path: Path) -> None:
    import time

    from ct.web.tasks import canonical_export_task

    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    try:
        canonical_export_task.start(workspace, forced=False)
        deadline = time.time() + 20
        steps_seen: list[str] = []
        last: dict = {}
        while time.time() < deadline:
            last = canonical_export_task.progress()
            if last["step_name"]:
                steps_seen.append(last["step_name"])
            if last["status"] != "running":
                break
            time.sleep(0.02)
        assert last.get("status") == "done", last
        assert last["tables_exported"] == 4
        assert last["step_index"] == len(last["steps"]) - 1
        assert last["forced"] is False
        # full phase list is reported; the export is fast, so only assert the
        # complete steps list plus the observed final step (no polling-granularity flake)
        assert last["steps"] == ["解析校验", "JSON", "Accessor", "FBS", "Bundle"]
        assert "Bundle" in steps_seen
        # history entry written to the workspace cache
        history = json.loads(
            (workspace / "cache" / "panel_history.json").read_text(encoding="utf-8")
        )
        assert history[-1]["result"] == "成功"
        assert history[-1]["tables"] == 4
    finally:
        canonical_export_task.status = "idle"
