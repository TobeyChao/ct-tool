""" shell browser tests: two-breakpoint projection, drawer model, state
persistence, side tool two-state, sidebar shell (responsive shell alignment)."""

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
def _panel_url(tmp_path_factory) -> Iterator[str]:
    from web_helpers import build_project

    workspace = build_project(
        tmp_path_factory.mktemp("-shell") / "workspace",
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


def _projection(page) -> str:
    return page.locator("#app").get_attribute("data-projection")


def _open_schema(page) -> None:
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")


def test_projection_state_machine(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    assert _projection(page) == "docked"

    page.set_viewport_size({"width": 800, "height": 460})
    page.wait_for_timeout(80)
    assert _projection(page) == "pane-drawer"
    # no page-level horizontal scroll at drawer widths
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

    page.set_viewport_size({"width": 400, "height": 844})
    page.wait_for_timeout(80)
    assert _projection(page) == "shell-drawer"
    # narrow topbar with workspace name, hamburger drawer instead of bottom nav
    assert page.locator(".ct-topbar").is_visible()
    assert page.locator(".ct-topbar .ct-ws-name").is_visible()
    assert page.locator(".ct-activity-bar").count() == 0
    context.close()


def test_selection_survives_projection_and_module_switch(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    _open_schema(page)

    # open the resource pane (default collapsed) and select a resource
    page.locator("#page-schema #resource-toggle").click()
    page.wait_for_timeout(200)
    page.locator(".ct-resource-row").first.click()
    selected = page.locator(".ct-resource-row.active").text_content()

    # switch module and come back
    page.locator('.ct-sitem[data-module="logs"]').click()
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector(".ct-resource-row")
    assert page.locator(".ct-resource-row.active").text_content() == selected

    # narrow -> wide round trip preserves selection (只收不展: pane stays closed)
    page.set_viewport_size({"width": 800, "height": 460})
    page.wait_for_timeout(120)
    page.set_viewport_size({"width": 1600, "height": 900})
    page.wait_for_timeout(120)
    assert page.locator(".ct-resource-row.active").text_content() == selected
    context.close()


def test_panes_default_collapsed_and_two_state_toggle(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    _open_schema(page)

    side_body = page.locator("#side-inspector")
    tab = page.locator("#page-schema .ct-side-tab")
    side_pane = page.locator("#page-schema .ct-side")
    # inspector defaults collapsed (docked panes default folded)
    assert tab.get_attribute("aria-pressed") == "false"
    assert side_body.get_attribute("inert") is not None
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") <= 1

    tab.click()
    page.wait_for_timeout(220)
    assert tab.get_attribute("aria-pressed") == "true"
    assert side_body.get_attribute("inert") is None
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") >= 280
    assert tab.is_visible(), "收起后右侧 Activity Tab 必须保留"

    tab.click()
    page.wait_for_timeout(220)
    assert tab.get_attribute("aria-pressed") == "false"
    assert side_body.get_attribute("inert") is not None
    assert side_pane.evaluate("el => el.getBoundingClientRect().width") <= 1

    # resource pane: toggle open/closed from the editor header entry
    toggle = page.locator("#page-schema #resource-toggle")
    pane = page.locator("#page-schema .ct-resource-pane")
    assert pane.evaluate("el => el.getBoundingClientRect().width") <= 1
    toggle.click()
    page.wait_for_timeout(220)
    assert pane.evaluate("el => el.getBoundingClientRect().width") >= 200
    assert toggle.get_attribute("aria-expanded") == "true"
    toggle.click()
    page.wait_for_timeout(220)
    assert pane.evaluate("el => el.getBoundingClientRect().width") <= 1
    context.close()


def test_panes_become_drawers_below_900(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 800, "height": 700})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    _open_schema(page)

    pane = page.locator("#page-schema .ct-resource-pane")

    def drawer_closed() -> bool:
        # 收起 = transform 完全滑出左缘（宽度保持，位置在视口外）
        return pane.evaluate(
            "el => { const r = el.getBoundingClientRect(); return r.x + r.width <= 1; }"
        )

    # closed drawer is off-screen (transform) and inert
    assert drawer_closed()
    assert pane.get_attribute("inert") is not None

    page.locator("#page-schema #resource-toggle").click()
    page.wait_for_timeout(300)
    box = pane.evaluate("el => el.getBoundingClientRect()")
    assert 0 <= box["x"] < 40, "抽屉应滑入左缘"

    # selecting a resource closes the drawer
    page.locator(".ct-resource-row").first.click()
    page.wait_for_timeout(300)
    assert drawer_closed()

    # Escape closes an open drawer
    page.locator("#page-schema #resource-toggle").click()
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert drawer_closed()
    context.close()


def test_hidden_pages_are_inert(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    _open_schema(page)
    page.locator('.ct-sitem[data-module="export"]').click()
    hidden = page.locator("#page-schema")
    assert hidden.get_attribute("inert") is not None
    context.close()


def test_about_and_help_dialogs(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")

    page.locator("#ct-about").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dialog")
    assert "配表工具" in page.locator(".ct-dialog").text_content()
    page.keyboard.press("Escape")
    page.wait_for_timeout(450)
    assert page.locator(".ct-dialog-mask").count() == 0

    page.locator("#ct-help").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-keys")
    help_text = page.locator(".ct-dialog").text_content()
    # help shortcuts must be truthful: all listed shortcuts actually exist
    assert "⌘P" in help_text and "⌘Z" in help_text
    page.keyboard.press("Escape")
    page.wait_for_timeout(450)
    assert page.locator(".ct-dialog-mask").count() == 0
    context.close()


def test_reduced_motion_disables_pane_transition(_panel_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(
        viewport={"width": 1600, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    page.goto(_panel_url, wait_until="networkidle")
    _open_schema(page)
    page.wait_for_selector("#page-schema .ct-workspace-layout")
    duration = page.locator("#page-schema .ct-workspace-layout").evaluate(
        "el => getComputedStyle(el).transitionDuration"
    )
    assert duration == "0s"
    context.close()
