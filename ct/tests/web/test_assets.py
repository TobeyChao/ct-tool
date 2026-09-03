""" static asset tree + shell contract tests (8.1-8.6)."""

from __future__ import annotations

from pathlib import Path

from ct.web.app import create_app

from web_helpers import build_project

ASSETS = [
    "/static/index.html",
    "/static/styles/tokens.css",
    "/static/styles/base.css",
    "/static/styles/layout.css",
    "/static/styles/components.css",
    "/static/js/app-shell.js",
    "/static/js/core/api.js",
    "/static/js/core/router.js",
    "/static/js/core/task.js",
]


def test_assets_are_served(tmp_path: Path) -> None:
    root = build_project(tmp_path / "gd")
    client = create_app(root).test_client()
    for asset in ASSETS:
        resp = client.get(asset)
        assert resp.status_code == 200, asset
        assert resp.content_length and resp.content_length > 0


def test_index_references_all_styles_and_module_entry(tmp_path: Path) -> None:
    index = Path(__file__).parents[2] / "src/ct/web/static/index.html"
    text = index.read_text(encoding="utf-8")
    for css in ("tokens.css", "base.css", "layout.css", "components.css"):
        assert f"/static/styles/{css}" in text
    assert 'src="/static/js/module-registry.js"' in text


def test_core_has_no_business_module_imports(tmp_path: Path) -> None:
    static_root = Path(__file__).parents[2] / "src/ct/web/static/js"
    core_files = (static_root / "core").glob("*.js")
    for path in core_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not line.startswith("import ") or "modules/" not in line, (
                f"{path.name} 不得依赖业务模块"
            )
