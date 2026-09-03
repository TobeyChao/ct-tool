"""v4 static asset tree + shell contract tests (8.1-8.6)."""

from __future__ import annotations

from pathlib import Path

from ct.web.app import create_app

from _v4_helpers import build_v4_project

ASSETS = [
    "/static/v4/index.html",
    "/static/v4/styles/tokens.css",
    "/static/v4/styles/base.css",
    "/static/v4/styles/layout.css",
    "/static/v4/styles/components.css",
    "/static/v4/js/app-shell.js",
    "/static/v4/js/core/api.js",
    "/static/v4/js/core/router.js",
    "/static/v4/js/core/task.js",
]


def test_v4_assets_are_served(tmp_path: Path) -> None:
    root = build_v4_project(tmp_path / "gd")
    client = create_app(root).test_client()
    for asset in ASSETS:
        resp = client.get(asset)
        assert resp.status_code == 200, asset
        assert resp.content_length and resp.content_length > 0


def test_index_references_all_styles_and_module_entry(tmp_path: Path) -> None:
    index = Path(__file__).parents[2] / "src/ct/web/static/v4/index.html"
    text = index.read_text(encoding="utf-8")
    for css in ("tokens.css", "base.css", "layout.css", "components.css"):
        assert f"/static/v4/styles/{css}" in text
    assert 'src="/static/v4/js/module-registry.js"' in text


def test_core_has_no_business_module_imports(tmp_path: Path) -> None:
    static_root = Path(__file__).parents[2] / "src/ct/web/static/v4/js"
    core_files = (static_root / "core").glob("*.js")
    for path in core_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not line.startswith("import ") or "modules/" not in line, (
                f"{path.name} 不得依赖业务模块"
            )
