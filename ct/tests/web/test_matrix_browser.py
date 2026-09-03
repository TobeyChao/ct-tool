""" shell viewport x zoom screenshot matrix (13.3).

Each physical viewport is divided by the zoom to yield the CSS viewport (with
deviceScaleFactor = zoom), matching real browser zoom; the matrix then
asserts the correct projection and no global horizontal scroll, and writes a
screenshot for the review evidence.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")

CT_ROOT = Path(__file__).parents[2]
MATRIX = CT_ROOT / "tests/fixtures/web/schema_workbench_matrix.json"


def _projection_for_width(width):
    if width >= 1360:
        return "wide"
    if width >= 960:
        return "medium"
    if width >= 600:
        return "compact"
    return "phone"


def _cases():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    return [
        (v["width"], v["height"], zoom)
        for v in matrix["viewports"]
        for zoom in matrix["zoom_percentages"]
    ]


@pytest.fixture(scope="module")
def _matrix_url(tmp_path_factory) -> Iterator[str]:
    from _helpers import build_project

    workspace = build_project(
        tmp_path_factory.mktemp("matrix") / "workspace",
        schemas=[
            {"table": "Item", "primary": "Id", "fields": [
                {"name": "Id", "type": "int32"}, {"name": "Name", "type": "string"},
            ]},
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


@pytest.mark.browser
@pytest.mark.parametrize(("w", "h", "zoom"), _cases())
def test_shell_matrix(
    tmp_path: Path,
    _matrix_url: str,
    chromium_browser: Any,
    w: int,
    h: int,
    zoom: int,
) -> None:
    output_root = Path(os.environ.get("CT_SCREENSHOT_DIR", str(tmp_path)))
    output_root.mkdir(parents=True, exist_ok=True)
    fraction = zoom / 100
    css = {"width": round(w / fraction), "height": round(h / fraction)}
    expected = _projection_for_width(css["width"])
    context = chromium_browser.new_context(
        viewport=css, device_scale_factor=fraction, locale="zh-CN", reduced_motion="reduce"
    )
    page = context.new_page()
    page.goto(_matrix_url + "#/export", wait_until="load")
    page.wait_for_selector(".ct-app")
    actual = page.locator("#app").get_attribute("data-projection")
    assert actual == expected, f"{w}x{h} z{zoom} (css {css['width']}): {actual} != {expected}"
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), f"{w}x{h} z{zoom}: 全局横向滚动"
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-workspace-layout")
    if expected == "medium":
        page.locator("#page-schema #resource-toggle").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row").first.click()
    if expected == "wide":
        rail_width = page.locator(".ct-activity-bar").evaluate("el => el.getBoundingClientRect().width")
        assert 54 <= rail_width <= 58
        assert page.locator("#page-schema .ct-right-activity").is_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), f"{w}x{h} z{zoom}: Schema 工作台横向滚动"
    page.screenshot(path=str(output_root / f"-{w}x{h}-z{zoom}-{expected}.png"))
    context.close()
