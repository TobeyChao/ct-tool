""" module page tests: export, i18n, logs, history (12.x)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")

CT_ROOT = Path(__file__).parents[2]

def _load_web_helpers():
    """Load tests/web/_helpers.py deterministically (the bare `_helpers`
    top-level name is ambiguous across the per-dir helper copies)."""
    import importlib.util
    import sys

    name = "_web_helpers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / "_helpers.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FIXTURE = CT_ROOT / "tests/fixtures/repository_cutover/workspace"


@pytest.fixture
def module_url(tmp_path) -> Iterator[str]:
    workspace = tmp_path / "workspace"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    _load_web_helpers().convert_cutover_workspace(workspace)
    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def chromium_browser() -> Iterator[Any]:
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def test_export_module_renders(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="导出").click()
    page.wait_for_selector("#page-export #export")
    assert page.locator("#page-export .ct-panel-title", has_text="导出").count() == 1
    page.close()


def test_i18n_module_renders_lang_rows(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="翻译 i18n").click()
    page.wait_for_selector("#page-i18n .ct-data tbody tr")
    rows = page.locator("#page-i18n .ct-data tbody tr").all_text_contents()
    # entry-editor rows carry the translated status; the selected table is Item
    assert any("translated" in row for row in rows)
    assert "Item" in page.locator("#page-i18n").text_content()
    # language pills en/ja are offered in the toolbar
    pills = page.locator("#page-i18n [data-lang]").all_text_contents()
    assert "en" in pills and "ja" in pills
    page.close()


def test_logs_module_renders(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="日志").click()
    page.wait_for_selector("#page-logs [data-module='all']")
    assert page.locator("#page-logs [data-module]").count() == 6
    assert page.locator("#page-logs [data-level]").count() == 4
    page.close()


def test_history_module_renders_empty(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="历史").click()
    page.wait_for_selector("#page-history .ct-empty-sub")
    # fresh cache -> empty state
    assert page.locator("#page-history .ct-empty-sub", has_text="暂无导出历史").count() == 1
    page.close()


def test_logs_level_and_search_filters(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="日志").click()
    page.wait_for_selector("#page-logs [data-level='INFO']")
    # level pill + search input exist; toggling level does not crash
    page.locator("#page-logs [data-level='ERROR']").click()
    page.wait_for_selector("#page-logs [data-level='ERROR'].active")
    page.fill("#page-logs #log-search", "导出")
    page.wait_for_timeout(50)
    assert page.locator("#page-logs #log-search").input_value() == "导出"
    page.close()
