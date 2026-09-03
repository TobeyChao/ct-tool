"""Schema editor browser tests: filter, select, draft -> validate -> apply, Quick Open (10.x/11.x)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def editor_url(tmp_path) -> Iterator[str]:
    from _helpers import build_project

    workspace = build_project(
        tmp_path / "workspace",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32", "comment": "主键"},
                    {"name": "Name", "type": "string", "comment": "名称"},
                ],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
        types=[
            {"kind": "enum", "name": "ItemRarity", "values": ["Common", "Rare"]},
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


def test_resource_groups_and_filter(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    # flat virtual list: all 3 resources visible in the window
    names = page.locator("#page-schema .ct-resource-row").all_text_contents()
    assert len(names) == 3

    page.locator("#page-schema #resource-filter").fill("Item")
    page.wait_for_timeout(50)
    filtered = page.locator("#page-schema .ct-resource-row").all_text_contents()
    assert any("Item" in n for n in filtered)
    assert len(filtered) == 2  # Item + ItemRarity
    context.close()


def test_collapsed_group_is_temporarily_expanded_by_search_and_restored(
    editor_url: str, chromium_browser: Any
) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)

    tables = page.locator('#page-schema [data-group="table"]')
    tables.click()
    assert tables.get_attribute("aria-expanded") == "false"
    assert page.locator('#page-schema [data-name="Item"]').count() == 0

    page.fill("#page-schema #resource-filter", "Item")
    page.wait_for_timeout(60)
    assert page.locator('#page-schema [data-name="Item"]').count() == 1
    page.fill("#page-schema #resource-filter", "")
    assert page.locator('#page-schema [data-name="Item"]').count() == 0

    page.reload(wait_until="load")
    page.wait_for_selector('#page-schema [data-group="table"]')
    assert page.locator('#page-schema [data-group="table"]').get_attribute("aria-expanded") == "false"
    context.close()


def test_select_resource_and_add_field_validates(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")

    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    assert "Item" in page.locator("#page-schema #editor-title").text_content()

    page.on("dialog", lambda dialog: dialog.accept("Price"))
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    assert "草稿校验通过" in page.locator("#page-schema #plan-output").text_content()
    context.close()


def test_review_plan_and_apply(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")

    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.on("dialog", lambda dialog: dialog.accept("Price"))
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    page.locator("#page-schema #review-plan").click()
    page.wait_for_selector("#page-schema #apply-plan")
    assert "风险" in page.locator("#page-schema #plan-output").text_content()

    page.locator("#page-schema #apply-plan").click()
    page.wait_for_function(
        "() => (document.querySelector('#plan-output') || {textContent: ''}).textContent.includes('已应用')",
        timeout=8000,
    )
    assert "已应用" in page.locator("#page-schema #plan-output").text_content()
    context.close()


def test_quick_open_filters_and_selects(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")

    page.keyboard.press("Control+p")
    page.wait_for_selector("#quick-open-mask:not([hidden])")
    page.fill("#page-schema #quick-open-input", "Rarity")
    page.wait_for_timeout(50)
    options = page.locator("#page-schema #quick-open-list .ct-resource-row").all_text_contents()
    assert any("ItemRarity" in o for o in options)
    page.locator("#page-schema #quick-open-list .ct-resource-row").first.click()
    assert "ItemRarity" in page.locator("#editor-title").text_content()
    context.close()


def test_quick_open_empty_query_prioritizes_recent_resources(
    editor_url: str, chromium_browser: Any
) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    page.locator('#page-schema [data-name="Quest"]').click()
    page.keyboard.press("Control+p")
    rows = page.locator("#page-schema #quick-open-list .ct-resource-row")
    assert rows.count() == 1
    assert "Quest" in rows.first.text_content()
    context.close()


def _open_schema_module(page, url) -> None:
    page.goto(url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")


def test_draft_persists_across_reload(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.on("dialog", lambda dialog: dialog.accept("Price"))
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("#page-schema .ct-draft-status")
    assert "1 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    # let the IndexedDB write commit before reload
    page.wait_for_timeout(300)
    # reload: draft restored because base revision still matches
    page.reload(wait_until="load")
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.wait_for_selector("#page-schema .ct-draft-status")
    assert "1 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    # discard clears the persisted draft
    page.locator("#page-schema #discard-draft").click()
    assert "无未应用修改" in page.locator("#page-schema .ct-draft-status").text_content()
    page.wait_for_timeout(300)
    page.reload(wait_until="load")
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.wait_for_selector("#page-schema .ct-draft-status")
    assert "无未应用修改" in page.locator("#page-schema .ct-draft-status").text_content()
    context.close()


def test_field_rename_delete_move_set_type_emit_commands(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()

    # rename prompt (type now uses the picker, not a prompt)
    page.on("dialog", lambda dialog: dialog.accept("DisplayName"))

    # rename Name -> DisplayName
    page.locator("#page-schema [data-act=\"rename\"]", has_text="Name").click()
    assert "1 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    # move the renamed field up/down
    page.locator("#page-schema [data-act=\"down\"]").first.click()
    assert "2 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    # set_type on Id via the type picker
    page.locator("#page-schema [data-act=\"type\"]", has_text="int32").click()
    page.wait_for_selector("#page-schema [data-type='int64']")
    page.locator("#page-schema [data-type='int64']").click()
    assert "3 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    # delete a field
    page.locator("#page-schema [data-act=\"delete\"]").first.click()
    assert "4 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()

    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    assert "草稿校验通过" in page.locator("#page-schema #plan-output").text_content()
    context.close()


def test_inspector_field_properties_emit_commands(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()

    page.locator("#page-schema tr[data-field=\"Name\"]").click()
    page.wait_for_selector("#page-schema #field-save")
    page.fill("#page-schema #side-inspector [data-prop=\"comment\"]", "备注")
    page.fill("#page-schema #side-inspector [data-prop=\"excel_columns\"]", "3")
    page.locator("#page-schema #field-save").click()
    assert "5 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    assert "草稿校验通过" in page.locator("#page-schema #plan-output").text_content()
    context.close()


def test_undo_redo_cursor(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()

    def add(name):
        page.on("dialog", lambda dialog: dialog.accept(name))
        page.locator("#page-schema #add-field").click()
        page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")

    add("Price")
    add("Level")
    assert page.locator("#page-schema .ct-draft-status").get_attribute("data-cursor") == "2"

    page.locator("#page-schema #undo-draft").click()
    assert page.locator("#page-schema .ct-draft-status").get_attribute("data-cursor") == "1"
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")

    page.locator("#page-schema #undo-draft").click()
    assert page.locator("#page-schema .ct-draft-status").get_attribute("data-cursor") == "0"

    page.locator("#page-schema #redo-draft").click()
    assert page.locator("#page-schema .ct-draft-status").get_attribute("data-cursor") == "1"
    page.locator("#page-schema #redo-draft").click()
    assert page.locator("#page-schema .ct-draft-status").get_attribute("data-cursor") == "2"
    context.close()


def test_compact_field_rows_at_390(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.wait_for_selector("#page-schema tr[data-field]")
    # no global horizontal scroll at 390 width
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    context.close()


def test_query_index_cards_emit_set_indexes(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema .ct-index-card")

    # configure Code=Name and Group=Id
    page.select_option("#page-schema [data-index-kind='code']", "Name")
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    page.select_option("#page-schema [data-index-kind='group']", "Id")
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")

    assert "2 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()
    # ByCode / ByGroupKey API previews are visible
    assert page.locator("#page-schema .ct-index-preview", has_text="ByCode").count() == 1
    assert page.locator("#page-schema .ct-index-preview", has_text="ByGroupKey").count() == 1

    # review plan surfaces Accessor impact for the index change
    page.locator("#page-schema #review-plan").click()
    page.wait_for_selector("#page-schema #apply-plan")
    assert "Accessor" in page.locator("#page-schema #plan-output").text_content()
    context.close()


def test_enum_editor_values_and_reverse_refs(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="ItemRarity").first.click()
    page.wait_for_selector("#page-schema #enum-add-value")

    # wire type is read-only byte
    assert "byte（只读" in page.locator("#page-schema #editor-body").text_content()

    # add a value emits a set_enum_values command
    page.on("dialog", lambda dialog: dialog.accept("Legendary"))
    page.locator("#page-schema #enum-add-value").click()
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    assert "1 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()
    assert "Legendary" in page.locator("#page-schema #editor-body").text_content()

    # remove a value
    page.locator('#page-schema [data-enum-remove="Common"]').click()
    assert "2 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()
    context.close()


def test_blocked_delete_with_references(editor_url: str, chromium_browser: Any, tmp_path: Path) -> None:
    """Dedicated workspace where Item references a record -> delete blocked."""
    import shutil
    import threading as _t
    from werkzeug.serving import make_server as _ms
    from _helpers import build_project as _bvp

    ws = tmp_path / "refws"
    _bvp(ws, schemas=[
        {"table": "Item", "primary": "Id", "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "Rewards", "type": "vector<DropReward>"},
        ]},
    ], types=[
        {"kind": "record", "name": "DropReward", "fields": [{"name": "ItemId", "type": "int32"}]},
    ])
    server = _ms("127.0.0.1", 0, create_app(ws), threaded=True)
    _t.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/static/index.html"
    try:
        context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        page.goto(url, wait_until="load")
        page.get_by_role("tab", name="Schema").click()
        page.wait_for_selector("#page-schema .ct-resource-row")
        page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
        page.wait_for_selector('#page-schema [data-navigate-type="DropReward"]')
        page.locator('#page-schema [data-navigate-type="DropReward"]').click()
        assert page.locator("#page-schema #editor-title").text_content() == "DropReward"
        page.locator("#page-schema .ct-resource-row", has_text="DropReward").first.click()
        page.wait_for_selector("#page-schema #delete-resource")
        # referenced record: delete is blocked with the use site
        page.locator("#page-schema #delete-resource").click()
        assert "无法删除" in page.locator("#page-schema #plan-output").text_content()
        assert "Rewards" in page.locator("#page-schema #plan-output").text_content()
        context.close()
    finally:
        server.shutdown()


def test_quick_open_keyboard_navigation(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")

    page.keyboard.press("Control+p")
    page.fill("#page-schema #quick-open-input", "Item")
    page.wait_for_timeout(80)
    # matches: Item, ItemRarity (by score then name); ArrowDown once -> ItemRarity
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert "ItemRarity" in page.locator("#page-schema #editor-title").text_content()
    context.close()


def test_keyboard_a11y_walkthrough(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    # module tabs are keyboard-reachable: focus the first tab, Enter activates it
    first_tab = page.locator(".ct-tab").first
    first_tab.focus()
    assert first_tab.evaluate("(el) => el === document.activeElement")
    page.keyboard.press("Enter")
    assert "active" in first_tab.get_attribute("class")

    # hidden pages stay inert (cannot be tab-focused)
    page.get_by_role("tab", name="导出").click()
    assert page.locator("#page-schema").get_attribute("inert") is not None

    # Quick Open: focus moves into the input; Esc closes
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema #quick-open-btn").focus()
    page.keyboard.press("Control+p")
    page.wait_for_selector("#page-schema #quick-open-input:focus")
    page.keyboard.press("Escape")
    assert page.locator("#page-schema #quick-open-mask").get_attribute("hidden") is not None
    assert page.locator("#page-schema #quick-open-btn").evaluate("el => el === document.activeElement")
    context.close()

def test_type_picker_selects_and_vector_toggle(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    page.wait_for_selector("#page-schema tr[data-field]")

    # open picker on the Name field (string type chip)
    page.locator("#page-schema [data-act='type']", has_text="string").click()
    page.wait_for_selector("#page-schema #type-picker-search:focus")
    # search narrows to named types; pick ItemRarity with vector toggle
    page.fill("#page-schema #type-picker-search", "ItemRarity")
    page.wait_for_timeout(60)
    page.check("#page-schema #type-picker-vector")
    page.locator("#page-schema [data-type='ItemRarity']").click()
    page.wait_for_selector("#page-schema #plan-output .ct-badge-ok")
    assert "1 条未应用命令" in page.locator("#page-schema .ct-draft-status").text_content()
    context.close()

def test_filter_counts_keyboard_and_pref_persistence(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-count")
    assert "总计" in page.locator("#page-schema .ct-resource-count").text_content()

    # filter keyboard: ArrowDown + Enter opens the highlighted row
    page.fill("#page-schema #resource-filter", "Item")
    page.wait_for_timeout(60)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert page.locator("#page-schema #editor-title").text_content().find("ItemRarity") >= 0

    # query persists across reload (localStorage preference)
    page.reload(wait_until="load")
    page.wait_for_selector("#page-schema #resource-filter")
    assert page.input_value("#page-schema #resource-filter") == "Item"
    context.close()

def test_resizable_panes_persist_width(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resize-handle.right")
    page.locator("#page-schema .ct-resize-handle.right").click()
    before = page.locator("#page-schema .ct-side").evaluate("(el) => el.getBoundingClientRect().width")

    # drag the right handle left by 80px to widen the inspector
    box = page.locator("#page-schema .ct-resize-handle.right").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 80, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    page.wait_for_timeout(80)
    after = page.locator("#page-schema .ct-side").evaluate("(el) => el.getBoundingClientRect().width")
    assert after > before, f"side pane did not grow: {before} -> {after}"
    context.close()

def test_medium_resource_overlay(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1200, "height": 800})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema #resource-toggle")

    # at medium the resource pane is hidden behind a temporary toggle
    layout = page.locator("#page-schema .ct-workspace-layout")
    assert "ct-resource-open" not in (layout.get_attribute("class") or "")
    page.locator("#page-schema #resource-toggle").click()
    assert "ct-resource-open" in (layout.get_attribute("class") or "")
    page.wait_for_selector("#page-schema .ct-resource-row")

    # selecting a resource closes the overlay
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    assert "ct-resource-open" not in (layout.get_attribute("class") or "")
    context.close()


def test_phone_page_stack_and_back(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 720, "height": 460})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.wait_for_timeout(120)

    layout = page.locator("#page-schema .ct-workspace-layout")
    assert layout.get_attribute("data-view") == "resources"

    # select a resource -> editor view
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.scroll_into_view_if_needed()
    page.locator("#page-schema .ct-resource-row", has_text="Item").first.click()
    assert layout.get_attribute("data-view") == "editor"

    # click a field row -> properties view
    page.locator("#page-schema tr[data-field='Name']").click()
    assert layout.get_attribute("data-view") == "properties"

    # Back from properties (side) -> editor; then editor back -> resources
    page.locator("#page-schema #side-back").click()
    page.wait_for_function("() => document.querySelector('#page-schema .ct-workspace-layout').dataset.view === 'editor'")
    page.locator("#page-schema #view-back").click()
    page.wait_for_function("() => document.querySelector('#page-schema .ct-workspace-layout').dataset.view === 'resources'")
    context.close()
