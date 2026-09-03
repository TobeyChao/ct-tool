from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app


playwright_api = pytest.importorskip("playwright.sync_api")

CT_ROOT = Path(__file__).parents[2]
MATRIX_PATH = CT_ROOT / "tests/fixtures/web/schema_workbench_matrix.json"
CUTOVER_WORKSPACE = CT_ROOT / "tests/fixtures/repository_cutover/workspace"


def _matrix_cases() -> list[tuple[int, int, int, str]]:
    # baseline is a quick smoke (full 18-combo matrix lives in 13.3)
    return [(1600, 900, 100, "wide"), (720, 460, 100, "compact"), (390, 844, 100, "phone")]
@pytest.fixture(scope="module")
def panel_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    workspace = tmp_path_factory.mktemp("browser-workspace") / "workspace"
    for source_dir in ("config", "excel", "i18n"):
        shutil.copytree(CUTOVER_WORKSPACE / source_dir, workspace / source_dir)
    from web_helpers import convert_cutover_workspace

    convert_cutover_workspace(workspace)

    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
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
@pytest.mark.parametrize(
    ("physical_width", "physical_height", "zoom_percent", "projection"),
    _matrix_cases(),
)
def test_local_panel_screenshot_matrix(
    tmp_path: Path,
    panel_url: str,
    chromium_browser: Any,
    physical_width: int,
    physical_height: int,
    zoom_percent: int,
    projection: str,
) -> None:
    output_root = Path(
        os.environ.get("CT_WEB_SCREENSHOT_DIR", str(tmp_path / "screenshots"))
    )
    output_root.mkdir(parents=True, exist_ok=True)
    screenshot_path = output_root / (
        f"schema-{physical_width}x{physical_height}-z{zoom_percent}-{projection}.png"
    )

    zoom = zoom_percent / 100
    css_viewport = {
        "width": round(physical_width / zoom),
        "height": round(physical_height / zoom),
    }
    console_errors: list[str] = []

    context = chromium_browser.new_context(
        viewport=css_viewport,
        device_scale_factor=zoom,
        locale="zh-CN",
        reduced_motion="reduce",
    )
    try:
        page = context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(panel_url + "/#/export", wait_until="domcontentloaded")
        page.wait_for_selector(".ct-app")
        page.wait_for_selector(".ct-topbar")

        #  AppShell renders for every workspace (legacy monolithic entry retired)
        assert page.locator(".ct-brand-mark", has_text="ct").count() == 1
        assert page.get_by_text("Workspace", exact=True).count() == 1
        assert page.locator(".ct-tab").count() == 5
        assert page.get_by_text("新增表", exact=True).count() == 0
        page.screenshot(path=str(screenshot_path), animations="disabled")

        assert screenshot_path.stat().st_size > 1_000
        assert console_errors == []
    finally:
        context.close()
