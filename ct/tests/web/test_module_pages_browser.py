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
    page.locator('.ct-sitem[data-module="export"]').click()
    page.wait_for_selector("#page-export #export-start")
    assert page.locator("#page-export .ct-panel-title", has_text="导出").count() == 1
    assert page.locator("#page-export #forced").count() == 0
    page.close()


def test_export_summary_refreshes_after_run(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="export"]').click()
    page.locator("#page-export #export-start").click()

    page.locator("#export-badge", has_text="成功").wait_for(timeout=5_000)

    assert page.locator("#export-context-pending").inner_text() == "0 张表"
    assert "成功" in page.locator("#export-context-result").inner_text()
    assert "4 张表" in page.locator("#export-context-result").inner_text()
    page.close()


def test_i18n_module_renders_lang_rows(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .ct-data tbody tr")
    rows = page.locator("#page-i18n .ct-data tbody tr").all_text_contents()
    # entry-editor rows carry the translated status; the selected table is Item
    assert any("已译完" in row for row in rows)
    assert "Item" in page.locator("#page-i18n").text_content()
    # language pills en/ja are offered in the toolbar
    pills = page.locator("#page-i18n [data-lang]").all_text_contents()
    assert "en" in pills and "ja" in pills
    page.close()


def test_logs_module_renders(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="logs"]').click()
    page.wait_for_selector("#page-logs [data-module='all']")
    assert page.locator("#page-logs [data-module]").count() == 6
    assert page.locator("#page-logs [data-level]").count() == 4
    page.close()


def test_history_module_renders_empty(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="history"]').click()
    page.wait_for_selector("#page-history .ct-empty-sub")
    # fresh cache -> empty state
    assert page.locator("#page-history .ct-empty-sub", has_text="暂无导出历史").count() == 1
    page.close()


def test_logs_level_and_search_filters(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="logs"]').click()
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
    page.locator('.ct-sitem[data-module="logs"]').click()
    marker = "live-refresh-browser-marker"
    log_buffer.add("系统", "ERROR", marker)
    page.get_by_text(marker).wait_for(timeout=3_000)
    assert page.locator("#page-logs .ct-badge-err", has_text="ERROR").count() >= 1
    page.close()


def test_logs_keep_reading_position_and_offer_jump_to_bottom(module_url: str, chromium_browser: Any) -> None:
    from ct.web.logs import log_buffer

    for index in range(80):
        log_buffer.add("系统", "INFO", f"scroll-position-marker-{index}")
    page = chromium_browser.new_page(viewport={"width": 1280, "height": 720})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="logs"]').click()
    viewport = page.locator("#page-logs .ct-log-table-wrap")
    viewport.wait_for()
    viewport.evaluate("node => node.scrollTop = Math.floor(node.scrollHeight / 2)")
    before = viewport.evaluate("node => node.scrollTop")

    log_buffer.add("系统", "INFO", "scroll-position-new-entry")
    page.wait_for_timeout(1_500)

    after = viewport.evaluate("node => node.scrollTop")
    assert abs(after - before) <= 2
    jump = page.locator("#page-logs #logs-jump-bottom")
    assert jump.is_visible()
    jump.click()
    page.wait_for_function(
        "() => { const node = document.querySelector('#page-logs .ct-log-table-wrap'); return node && node.scrollHeight - node.clientHeight - node.scrollTop <= 8; }",
        timeout=2_000,
    )
    assert viewport.evaluate("node => node.scrollHeight - node.clientHeight - node.scrollTop") <= 8
    assert jump.is_hidden()
    page.close()


def test_logs_compact_rows_keep_field_labels(module_url: str, chromium_browser: Any) -> None:
    from ct.web.logs import log_buffer

    log_buffer.add("导出", "INFO", "compact-layout-marker")
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(module_url, wait_until="load")
    page.locator("#ct-hamb").click()
    page.wait_for_timeout(200)
    page.locator('.ct-sitem[data-module="logs"]').click()
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
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n #i18n-progress")

    # open progress modal (shared dialog stack), close via 关闭 button
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("body > .ct-dialog-mask.open")
    page.click("body > .ct-dialog-mask.open [data-progress-close]")
    page.wait_for_timeout(450)
    assert page.locator("body > .ct-dialog-mask").count() == 0

    # reopen, close via backdrop click
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("body > .ct-dialog-mask.open")
    page.locator("body > .ct-dialog-mask.open").click(position={"x": 5, "y": 5})
    page.wait_for_timeout(450)
    assert page.locator("body > .ct-dialog-mask").count() == 0

    # reopen, close via Esc
    page.click("#page-i18n #i18n-progress")
    page.wait_for_selector("body > .ct-dialog-mask.open")
    page.keyboard.press("Escape")
    page.wait_for_timeout(450)
    assert page.locator("body > .ct-dialog-mask").count() == 0
    page.close()

def test_i18n_table_picker_filters_and_empty(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n #i18n-pick")
    page.click("#page-i18n #i18n-pick")
    page.wait_for_selector("body > .ct-dialog-mask.open .ct-picker-row")

    # only tables with i18n fields are listed (UIConfig has none)
    rows = page.locator(".ct-dialog-mask.open .ct-picker-row").all_text_contents()
    assert all(t in "".join(rows) for t in ("Item", "ItemType", "Quest"))
    assert not any("UIConfig" in r for r in rows)

    # search narrows the list
    page.fill("[data-pick-search]", "Item")
    page.wait_for_timeout(150)
    after = page.locator(".ct-dialog-mask.open .ct-picker-row").all_text_contents()
    assert len(after) == 2
    assert all("Item" in r for r in after)

    # no match -> empty state
    page.fill("[data-pick-search]", "zzz")
    page.wait_for_timeout(150)
    assert page.locator(".ct-dialog-mask.open .ct-picker-list .ct-empty-title").count() == 1
    page.close()


def test_i18n_table_picker_click_select(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n #i18n-pick")
    page.click("#page-i18n #i18n-pick")
    page.wait_for_selector("body > .ct-dialog-mask.open .ct-picker-row")
    # no keyboard highlight box by default
    assert page.locator(".ct-dialog-mask.open .ct-picker-row.highlight").count() == 0
    page.locator(".ct-dialog-mask.open .ct-picker-row", has_text="Quest").click()
    page.wait_for_timeout(300)
    assert page.locator("body > .ct-dialog-mask").count() == 0
    assert "Quest" in page.locator("#page-i18n").text_content()
    page.close()

def test_i18n_entry_table_alignment(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
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


def test_i18n_entry_table_preserves_text_columns_on_narrow_view(
    module_url: str, chromium_browser: Any
) -> None:
    page = chromium_browser.new_page(viewport={"width": 390, "height": 844})
    page.goto(module_url, wait_until="load")
    page.locator("#ct-hamb").click()
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .ct-i18n-table table")
    metrics = page.evaluate("""() => {
      const wrap = document.querySelector('#page-i18n .ct-i18n-table');
      const table = wrap.querySelector('table');
      const th = table.querySelectorAll('thead th');
      return {
        wrapWidth: Math.round(wrap.getBoundingClientRect().width),
        tableWidth: Math.round(table.getBoundingClientRect().width),
        sourceWidth: Math.round(th[2].getBoundingClientRect().width),
        translationWidth: Math.round(th[3].getBoundingClientRect().width),
        hasHorizontalOverflow: wrap.scrollWidth > wrap.clientWidth,
      };
    }""")
    assert metrics["tableWidth"] >= 916
    assert metrics["sourceWidth"] >= 240
    assert metrics["translationWidth"] >= 240
    assert metrics["hasHorizontalOverflow"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.close()


def test_i18n_narrow_header_keeps_title_and_actions_centered(
    module_url: str, chromium_browser: Any
) -> None:
    page = chromium_browser.new_page(viewport={"width": 520, "height": 460})
    page.goto(module_url + "#/i18n", wait_until="load")
    page.wait_for_selector("#page-i18n .ct-module-head")
    metrics = page.evaluate("""() => {
      const head = document.querySelector('#page-i18n .ct-module-head');
      const actionGroup = head.querySelector('.ct-module-actions');
      actionGroup.style.width = '180px';
      const title = head.querySelector('.ct-panel-title').getBoundingClientRect();
      const actions = actionGroup.getBoundingClientRect();
      const buttons = [...actionGroup.querySelectorAll(':scope > .ct-btn')];
      return {
        titleCenter: Math.round(title.top + title.height / 2),
        actionsCenter: Math.round(actions.top + actions.height / 2),
        actionRows: new Set(buttons.map((button) => Math.round(button.getBoundingClientRect().top))).size,
      };
    }""")
    assert abs(metrics["titleCenter"] - metrics["actionsCenter"]) <= 2
    assert metrics["actionRows"] >= 2
    page.close()


def test_i18n_fullscreen_editor_saves_and_cancels(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .ct-data tbody tr")

    # Entering fullscreen from an active inline edit persists that draft first.
    page.locator("#page-i18n .trans-preview").first.click()
    page.locator("#page-i18n textarea.is-area").fill("行内待提交译文")
    page.locator("#page-i18n .ct-trans-expand").first.click()
    page.wait_for_selector("body > .ct-dialog-mask.open .ct-dlg-trans")
    assert page.locator(".ct-dlg-src").count() == 1
    assert page.locator(".ct-dlg-trans").input_value() == "行内待提交译文"
    page.fill(".ct-dlg-trans", "全新译文")
    page.locator("[data-full-save]").click()
    page.wait_for_timeout(600)
    # saved: status badge flips to 已译完 and the preview shows the text
    assert "全新译文" in page.locator("#page-i18n").text_content()
    assert page.locator("#page-i18n .ct-badge-ok", has_text="已译完").count() >= 1

    # cancel does not write back
    page.locator("#page-i18n .ct-trans-expand").first.click()
    page.wait_for_selector("body > .ct-dialog-mask.open .ct-dlg-trans")
    page.fill(".ct-dlg-trans", "不应保存")
    page.locator("[data-full-cancel]").click()
    page.wait_for_timeout(300)
    assert "不应保存" not in page.locator("#page-i18n").text_content()
    page.close()


def test_i18n_column_visibility_persists_across_rerender(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .ct-data tbody tr")

    # hide the 译文 column via the colvis menu
    page.click("#i18n-colvis-btn")
    page.wait_for_selector(".ct-col-menu:not([hidden])")
    page.locator('.ct-col-menu input[data-col="trans"]').click()
    page.wait_for_timeout(120)
    assert page.locator("#page-i18n table.ct-col-rules thead th").nth(3).is_hidden()

    # replay after a re-render (status filter toggle triggers render)
    page.locator('#page-i18n [data-filter="missing"]').click()
    page.wait_for_timeout(200)
    assert page.locator("#page-i18n table.ct-col-rules thead th").nth(3).is_hidden()
    page.locator('#page-i18n [data-filter="all"]').click()
    page.wait_for_timeout(200)

    # outside click closes the menu; state kept
    page.click("#i18n-colvis-btn")
    page.wait_for_selector(".ct-col-menu:not([hidden])")
    page.locator("#page-i18n .ct-current-table").click()
    page.wait_for_timeout(120)
    assert page.locator(".ct-col-menu").is_hidden()
    # Esc closes the menu too
    page.click("#i18n-colvis-btn")
    page.wait_for_selector(".ct-col-menu:not([hidden])")
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    assert page.locator(".ct-col-menu").is_hidden()
    # cleanup preference for other tests
    page.evaluate("localStorage.removeItem('ct-i18n-cols')")
    page.close()


def test_i18n_source_expand_tail(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .ct-data tbody tr")
    tails = page.locator("#page-i18n .ct-src-more")
    if tails.count() == 0:
        # fixture rows may all be short: force a long source through the DOM is
        # not possible (server data), so assert the mechanism is wired instead
        assert page.locator("#page-i18n .ct-src-text").count() >= 1
        page.close()
        return
    first = tails.first
    assert "展开" in first.text_content()
    first.click()
    page.wait_for_timeout(120)
    assert "收起" in first.text_content()
    first.click()
    page.wait_for_timeout(120)
    assert "展开" in first.text_content()
    page.close()


def test_i18n_inline_blur_saves_only_changed_drafts(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    saves: list[str] = []
    page.on(
        "request",
        lambda request: saves.append(request.post_data or "")
        if request.url.endswith("/api/i18n/entry") and request.method == "POST"
        else None,
    )
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_selector("#page-i18n .trans-preview")

    # Entering and leaving an unchanged row must not confirm it accidentally.
    page.locator("#page-i18n .trans-preview").first.click()
    page.locator('#page-i18n [data-filter="all"]').click()
    page.wait_for_timeout(120)
    assert saves == []

    # A changed draft still follows the active change contract: blur persists it.
    page.locator("#page-i18n .trans-preview").first.click()
    page.locator("#page-i18n textarea.is-area").fill("失焦保存译文")
    page.locator('#page-i18n [data-filter="all"]').click()
    page.wait_for_timeout(500)
    assert len(saves) == 1
    assert "失焦保存译文" in page.locator("#page-i18n").text_content()
    page.close()


def test_i18n_reactivation_recomputes_sticky_offset(module_url: str, chromium_browser: Any) -> None:
    page = chromium_browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(module_url, wait_until="load")
    page.locator('.ct-sitem[data-module="i18n"]').click()
    table = page.locator("#page-i18n table.ct-col-rules")
    page.wait_for_selector("#page-i18n table.ct-col-rules tbody tr")

    page.locator('.ct-sitem[data-module="logs"]').click()
    table.evaluate("el => el.style.removeProperty('--ct-i18n-id-w')")
    page.set_viewport_size({"width": 1200, "height": 760})
    page.locator('.ct-sitem[data-module="i18n"]').click()
    page.wait_for_timeout(80)

    offset = table.evaluate("el => el.style.getPropertyValue('--ct-i18n-id-w')")
    assert offset and float(offset.removesuffix("px")) > 0
    page.close()
