"""DOM-independent fuzzy scorer tests (11.1), run in-browser via dynamic import."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def fuzzy_url(tmp_path_factory) -> Iterator[str]:
    from _v4_helpers import build_v4_project

    workspace = build_v4_project(tmp_path_factory.mktemp("fuzzy") / "workspace")
    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/v4/index.html"
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


def _load(page) -> None:
    page.evaluate(
        "async () => { const m = await import('/static/v4/js/core/fuzzy.js'); window.__fuzzy = m; }"
    )


def test_subsequence_abbreviation_matches(fuzzy_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page()
    page.goto(fuzzy_url, wait_until="load")
    _load(page)
    result = page.evaluate(
        "() => [__fuzzy.fuzzyScore('ItemType', 'IT'), __fuzzy.fuzzyScore('ItemType', 'ItemT'), __fuzzy.fuzzyScore('Quest', 'IT')]"
    )
    assert result[0] < result[1]  # tighter match scores better
    assert result[2] == 1_000_000_000 or result[2] >= 1000000  # no match


def test_rank_ties_are_deterministic(fuzzy_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page()
    page.goto(fuzzy_url, wait_until="load")
    _load(page)
    ordered = page.evaluate(
        """() => __fuzzy.rank(
          [{n:'Item'},{n:'ItemType'},{n:'ItemRarity'}],
          'it',
          (x) => x.n
        ).map(x => x.name)"""
    )
    assert ordered[0] == "Item"
    assert ordered[0] != ordered[1]
    # deterministic across calls
    again = page.evaluate(
        """() => __fuzzy.rank(
          [{n:'Item'},{n:'ItemType'},{n:'ItemRarity'}],
          'it',
          (x) => x.n
        ).map(x => x.name)"""
    )
    assert ordered == again


def test_highlight_ranges(fuzzy_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page()
    page.goto(fuzzy_url, wait_until="load")
    _load(page)
    ranges = page.evaluate("() => __fuzzy.highlightRanges('ItemRarity', 'IR')")
    assert ranges == [[0, 1], [4, 5]]
    empty = page.evaluate("() => __fuzzy.highlightRanges('ItemRarity', 'zz')")
    assert empty == []
