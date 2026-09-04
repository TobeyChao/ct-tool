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


FIXTURE = CT_ROOT / "tests/fixtures/repository_cutover/workspace"


@pytest.fixture
def module_url(tmp_path) -> Iterator[str]:
    workspace = tmp_path / "workspace"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
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
    page.wait_for_selector("#page-export #export-start")
    assert page.locator("#page-export .ct-panel-title", has_text="导出").count() == 1
    assert page.locator("#page-export #forced").count() == 0
    page.close()


def test_export_summary_refreshes_after_run(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="导出").click()
    page.locator("#page-export #export-start").click()

    page.locator("#export-badge", has_text="成功").wait_for(timeout=5_000)

    assert page.locator("#export-context-pending").inner_text() == "0 张表"
    assert "成功" in page.locator("#export-context-result").inner_text()
    assert "4 张表" in page.locator("#export-context-result").inner_text()
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
    assert page.locator("#page-logs .ct-log-empty").count() == 1
    page.close()


def test_logs_refresh_while_visible(module_url: str, chromium_browser: Any) -> None:
    from ct.web.logs import log_buffer

    page = chromium_browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="日志").click()
    marker = "live-refresh-browser-marker"
    log_buffer.add("系统", "ERROR", marker)
    page.get_by_text(marker).wait_for(timeout=3_000)
    assert page.locator("#page-logs .ct-badge-err", has_text="ERROR").count() >= 1
    page.close()


def test_logs_compact_rows_keep_field_labels(module_url: str, chromium_browser: Any) -> None:
    from ct.web.logs import log_buffer

    log_buffer.add("导出", "INFO", "compact-layout-marker")
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="日志").click()
    row = page.locator("#page-logs tr", has_text="compact-layout-marker")
    row.wait_for()
    assert row.locator("[data-label='时间']").count() == 1
    assert row.locator("[data-label='模块']").count() == 1
    assert row.locator("[data-label='级别']").count() == 1
    assert row.locator("[data-label='信息']").count() == 1
    page.close()

def test_i18n_progress_modal_closes(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="翻译 i18n").click()
    page.wait_for_selector("#page-i18n #i18n-progress")

    # open progress modal, close via 关闭 button
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("#page-i18n .ct-dialog-mask")
    page.click("#page-i18n .ct-dialog-foot button[data-close]")
    page.wait_for_timeout(120)
    assert page.locator("#page-i18n .ct-dialog-mask").count() == 0

    # reopen, close via backdrop click
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("#page-i18n .ct-dialog-mask")
    page.locator("#page-i18n .ct-dialog-mask").click(position={"x": 5, "y": 5})
    page.wait_for_timeout(120)
    assert page.locator("#page-i18n .ct-dialog-mask").count() == 0

    # reopen, close via Esc
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("#page-i18n .ct-dialog-mask")
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    assert page.locator("#page-i18n .ct-dialog-mask").count() == 0
    page.close()

def test_i18n_table_picker_filters_and_empty(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="翻译 i18n").click()
    page.wait_for_selector("#page-i18n #i18n-pick")
    page.click("#page-i18n #i18n-pick")
    page.wait_for_selector("#page-i18n .ct-picker-row")

    # only tables with i18n fields are listed (UIConfig has none)
    rows = page.locator("#page-i18n .ct-picker-row").all_text_contents()
    assert all(t in "".join(rows) for t in ("Item", "ItemType", "Quest"))
    assert not any("UIConfig" in r for r in rows)

    # search narrows the list
    page.fill("#page-i18n #pick-search", "Item")
    page.wait_for_timeout(150)
    after = page.locator("#page-i18n .ct-picker-row").all_text_contents()
    assert len(after) == 2
    assert all("Item" in r for r in after)

    # no match -> empty state
    page.fill("#page-i18n #pick-search", "zzz")
    page.wait_for_timeout(150)
    assert page.locator("#page-i18n .ct-picker-list .ct-empty-title").count() == 1
    page.close()


def test_i18n_table_picker_click_select(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="翻译 i18n").click()
    page.wait_for_selector("#page-i18n #i18n-pick")
    page.click("#page-i18n #i18n-pick")
    page.wait_for_selector("#page-i18n .ct-picker-row")
    # no keyboard highlight box by default
    assert page.locator("#page-i18n .ct-picker-row.highlight").count() == 0
    page.locator("#page-i18n .ct-picker-row", has_text="Quest").click()
    page.wait_for_timeout(300)
    assert page.locator("#page-i18n .ct-dialog-mask").count() == 0
    assert "Quest" in page.locator("#page-i18n").text_content()
    page.close()

def test_i18n_entry_table_alignment(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.get_by_role("tab", name="翻译 i18n").click()
    page.wait_for_selector("#page-i18n .ct-data thead")
    m = page.evaluate("""() => {
      const th = Array.from(document.querySelectorAll('#page-i18n .ct-data thead th'));
      const opsTh = th[th.length - 1].getBoundingClientRect();
      const opsTd = document.querySelector('#page-i18n .ct-row-ops').getBoundingClientRect();
      const srcTh = th[2].getBoundingClientRect();
      const transTh = th[3].getBoundingClientRect();
      const btn = document.querySelector('#page-i18n .ct-row-ops button').getBoundingClientRect();
      return { thLeft: Math.round(opsTh.left), tdLeft: Math.round(opsTd.left),
               srcW: Math.round(srcTh.width), transW: Math.round(transTh.width), btnW: Math.round(btn.width) };
    }""")
    assert abs(m["thLeft"] - m["tdLeft"]) <= 1  # 操作 header + buttons both left-aligned
    assert abs(m["srcW"] - m["transW"]) <= 2   # 原文/译文等宽
    assert m["btnW"] >= 90                     # 保存按钮等宽
    page.close()
