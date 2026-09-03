"""v4 shell browser tests: adaptive projection, state persistence, side tool (9.x)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")

CT_ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def v4_panel_url(tmp_path_factory) -> Iterator[str]:
    from _v4_helpers import build_v4_project

    workspace = build_v4_project(
        tmp_path_factory.mktemp("v4-shell") / "workspace",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Rarity", "type": "ItemRarity"},
                ],
            }
        ],
        types=[
            {"kind": "enum", "name": "ItemRarity", "values": ["Common", "Rare"]},
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [{"name": "ItemId", "type": "int32"}],
            },
        ],
    )
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


def _projection(page) -> str:
    return page.locator("#app").get_attribute("data-projection")


def test_projection_state_machine(v4_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(v4_panel_url, wait_until="networkidle")
    assert _projection(page) == "wide"

    page.set_viewport_size({"width": 720, "height": 460})
    page.wait_for_timeout(80)
    assert _projection(page) == "compact"
    # no page-level horizontal scroll at the launcher's minimum width (9.4)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

    page.set_viewport_size({"width": 400, "height": 844})
    page.wait_for_timeout(80)
    assert _projection(page) == "phone"
    context.close()


def test_selection_survives_projection_and_module_switch(v4_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(v4_panel_url, wait_until="networkidle")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector(".ct-resource-row")

    # select the first resource
    page.locator(".ct-resource-row").first.click()
    selected = page.locator(".ct-resource-row.active").text_content()

    # switch module and come back
    page.get_by_role("tab", name="日志").click()
    page.get_by_role("tab", name="Schema").click()
    assert page.locator(".ct-resource-row.active").text_content() == selected

    # narrow -> wide round trip preserves selection
    page.set_viewport_size({"width": 720, "height": 460})
    page.wait_for_timeout(80)
    page.set_viewport_size({"width": 1600, "height": 900})
    page.wait_for_timeout(80)
    assert page.locator(".ct-resource-row.active").text_content() == selected
    context.close()


def test_side_tool_two_state_toggle(v4_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(v4_panel_url, wait_until="networkidle")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector(".ct-side-tab")

    side_body = page.locator("#side-inspector")
    tab = page.locator(".ct-side-tab")
    # inspector defaults open; toggling closes (inert) and reopens (restore control stays)
    assert tab.get_attribute("aria-pressed") == "true"
    assert side_body.get_attribute("inert") is None
    side_pane = page.locator(".ct-side")
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") >= 280

    tab.click()
    page.wait_for_timeout(220)
    assert tab.get_attribute("aria-pressed") == "false"
    assert side_body.get_attribute("inert") is not None
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") <= 1
    assert tab.is_visible(), "收起后右侧 Activity Tab 必须保留"

    tab.click()
    page.wait_for_timeout(220)
    assert tab.get_attribute("aria-pressed") == "true"
    assert side_body.get_attribute("inert") is None
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") >= 280
    context.close()


def test_hidden_pages_are_inert(v4_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(v4_panel_url, wait_until="networkidle")
    page.get_by_role("tab", name="导出").click()
    hidden = page.locator("#page-schema")
    assert hidden.get_attribute("inert") is not None
    context.close()


def test_reduced_motion_disables_pane_transition(v4_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(
        viewport={"width": 1600, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    page.goto(v4_panel_url, wait_until="networkidle")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector(".ct-workspace-layout")
    duration = page.locator(".ct-workspace-layout").evaluate(
        "el => getComputedStyle(el).transitionDuration"
    )
    assert duration == "0s"
    context.close()
