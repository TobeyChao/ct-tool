from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from ct.cli import app


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "repository_cutover_v4"
WORKSPACE_ROOT = FIXTURE_ROOT / "workspace"


def _tree_fingerprint(section: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    files = sorted(path for path in (WORKSPACE_ROOT / section).rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(WORKSPACE_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return len(files), digest.hexdigest()


def _relative_files(root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())


def test_repository_cutover_fixture_is_complete_and_immutable() -> None:
    baseline = json.loads((FIXTURE_ROOT / "baseline.json").read_text(encoding="utf-8"))

    assert baseline["format_version"] == 1
    assert hashlib.sha256(
        (WORKSPACE_ROOT / "config" / "global.yaml").read_bytes()
    ).hexdigest() == baseline["global_config_sha256"]

    assert sorted(path.name for path in (WORKSPACE_ROOT / "config/schemas").glob("*.yaml")) == [
        "Item.yaml",
        "ItemType.yaml",
        "Quest.yaml",
        "UIConfig.yaml",
    ]
    assert sorted(path.name for path in (WORKSPACE_ROOT / "excel").glob("*.xlsx")) == [
        "Item.xlsx",
        "ItemType.xlsx",
        "Quest.xlsx",
        "UIConfig.xlsx",
    ]

    for section, expected in baseline["sections"].items():
        count, fingerprint = _tree_fingerprint(section)
        assert count == expected["file_count"], section
        assert fingerprint == expected["tree_sha256"], section


def test_repository_cutover_fixture_clean_export_matches_golden(tmp_path: Path) -> None:
    for source_dir in ("config", "excel", "i18n"):
        shutil.copytree(WORKSPACE_ROOT / source_dir, tmp_path / source_dir)

    result = CliRunner().invoke(
        app,
        ["export", "--root", str(tmp_path), "--all", "--verbose"],
    )

    assert result.exit_code == 0, result.output
    assert "导出完成: 4 张表" in result.output

    expected_root = WORKSPACE_ROOT / "output"
    actual_root = tmp_path / "output"
    expected_files = _relative_files(expected_root)
    assert _relative_files(actual_root) == expected_files
    for relative_path in expected_files:
        assert (actual_root / relative_path).read_bytes() == (
            expected_root / relative_path
        ).read_bytes(), relative_path
