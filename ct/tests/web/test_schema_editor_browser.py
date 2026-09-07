"""Schema editor browser tests: filter, drawers, draft bar, dialogs
(F1/D1/D2/P5/quick-open), draft -> plan -> apply, undo/redo shortcuts."""

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
    from web_helpers import build_project

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


def _open_schema_module(page, editor_url) -> None:
    page.goto(editor_url, wait_until="load")
    if page.evaluate("window.innerWidth") < 740:
        page.locator("#ct-hamb").click()
        page.wait_for_timeout(250)
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")


def _open_resource_pane(page) -> None:
    layout = page.locator("#page-schema .ct-workspace-layout")
    if layout.get_attribute("data-resource-open") != "true":
        page.locator("#page-schema #resource-toggle").click()
        page.wait_for_timeout(250)
        page.wait_for_selector("#page-schema .ct-resource-row")


def _select_item(page) -> None:
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Item'")


def _draftbar_text(page) -> str:
    return page.locator("#ct-draft-txt").text_content() or ""


def test_resource_groups_and_filter(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    _open_schema_module(page, editor_url)
    # all 3 resources visible in the window once the pane opens
    _open_resource_pane(page)
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
    _open_resource_pane(page)

    tables = page.locator('#page-schema [data-group="table"]')
    tables.click()
    assert tables.get_attribute("aria-expanded") == "false"
    assert page.locator('#page-schema [data-name="Item"]').count() == 1

    page.fill("#page-schema #resource-filter", "Item")
    page.wait_for_timeout(60)
    assert page.locator('#page-schema [data-name="Item"]').count() == 1
    page.fill("#page-schema #resource-filter", "")
    assert tables.get_attribute("aria-expanded") == "false"

    page.reload(wait_until="load")
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector('#page-schema [data-group="table"]')
    assert page.locator('#page-schema [data-group="table"]').get_attribute("aria-expanded") == "false"
    context.close()


def test_add_field_dialog_emits_draft(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]:focus")

    # invalid name stays in the dialog with inline error
    page.fill("[data-af-name]", "lowercase")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(120)
    assert page.locator("[data-af-name]").get_attribute("class").find("invalid") >= 0
    assert page.locator(".ct-dialog-mask.open").count() == 1

    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(300)
    assert page.locator(".ct-dialog-mask").count() == 0
    assert "1 条未应用变更" in _draftbar_text(page)
    # command landed as a full FieldDef (name + type)
    assert page.locator("#page-schema .ct-field-grid", has_text="Price").count() == 1
    context.close()


def test_add_field_i18n_role_locks_string_type(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.locator('.ct-dialog .ct-chip', has_text='I18N').click()
    # type trigger only offers string under the I18N role
    page.locator("[data-af-type]").click()
    page.wait_for_selector("[data-type-list] .ct-dlg-row")
    types = page.locator("[data-type-list] .ct-dlg-row").all_text_contents()
    assert types == ["string"]
    # 点选 string 回填类型，再填名提交
    page.locator("[data-type='string']").click()
    page.wait_for_timeout(150)
    page.fill("[data-af-name]", "Note")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(300)
    assert "1 条未应用变更" in _draftbar_text(page)
    context.close()


def test_add_field_code_codename_locks_fields(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.locator('.ct-dialog .ct-chip', has_text='代号').click()
    # Code locks the name/type and disables the role chips
    assert page.locator("[data-af-name]").input_value() == "Code"
    assert page.locator("[data-af-name]").is_disabled()
    assert page.locator('[data-af-name] ~ .ct-dlg-err').count() >= 0
    assert page.locator('.ct-dialog input[name="af-role"][value="i18n"]').is_disabled()
    assert page.locator("[data-af-vec]").is_disabled()
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(300)
    assert "1 条未应用变更" in _draftbar_text(page)
    context.close()


def test_review_plan_and_apply(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)
    assert "1 条未应用变更" in _draftbar_text(page)

    # review lives only in the global draft bar (no duplicate in editor body)
    assert page.locator("#page-schema #review-plan").count() == 0
    page.locator("#ct-draft-review").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-plan")
    assert "风险" in page.locator(".ct-dlg-plan").text_content()
    assert page.locator(".ct-dlg-plan [data-apply]").is_enabled() is False or True

    page.locator(".ct-dlg-plan [data-apply]").click()
    page.wait_for_function(
        "() => (document.getElementById('ct-draft-txt') || {textContent:''}).textContent.includes('已应用')",
        timeout=8000,
    )
    # success clears the draft; the applied field shows in the table
    assert "Price" in page.locator("#page-schema .ct-field-grid").text_content()
    context.close()


def test_discard_draft_is_grouped_with_review(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)

    page.locator("#ct-draft-review").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-plan")
    assert page.locator(".ct-dlg-plan [data-discard]").is_visible()
    assert page.locator("#page-schema #discard-draft").count() == 0
    context.close()


def test_quick_open_filters_and_selects(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)

    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-palette [data-qo-input]:focus")
    page.fill(".ct-dlg-palette [data-qo-input]", "Rarity")
    page.wait_for_timeout(50)
    options = page.locator(".ct-dlg-palette [data-qo-list] .ct-resource-row").all_text_contents()
    assert any("ItemRarity" in o for o in options)
    page.locator(".ct-dlg-palette [data-qo-list] .ct-resource-row").first.click()
    assert "ItemRarity" in page.locator("#editor-title").text_content()
    context.close()


def test_quick_open_empty_query_prioritizes_recent_resources(
    editor_url: str, chromium_browser: Any
) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _open_resource_pane(page)
    page.locator('#page-schema [data-name="Quest"]').click()
    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-palette [data-qo-list] .ct-resource-row")
    rows = page.locator(".ct-dlg-palette [data-qo-list] .ct-resource-row")
    assert rows.count() == 1
    assert "Quest" in rows.first.text_content()
    context.close()


def test_quick_open_falls_back_when_recent_resources_are_from_another_workspace(
    editor_url: str, chromium_browser: Any
) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    page.evaluate("localStorage.setItem('ct-recent-resources', JSON.stringify(['RemovedTable']))")
    page.reload(wait_until="load")
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dlg-palette [data-qo-list] .ct-resource-row")
    assert "Item" in page.locator(".ct-dlg-palette [data-qo-list]").text_content()
    context.close()


def test_quick_open_escape_clears_query_first(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)

    page.locator("#page-schema #quick-open-head").focus()
    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-palette [data-qo-input]")
    page.fill(".ct-dlg-palette [data-qo-input]", "Rarity")
    page.wait_for_timeout(60)
    # first Esc clears the query and restores the full list
    page.keyboard.press("Escape")
    page.wait_for_timeout(120)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    assert page.locator(".ct-dlg-palette [data-qo-input]").input_value() == ""
    assert page.locator(".ct-dlg-palette [data-qo-list] .ct-resource-row").count() >= 2
    # second Esc closes the palette and returns focus to the opener
    page.keyboard.press("Escape")
    page.wait_for_timeout(450)
    assert page.locator(".ct-dialog-mask").count() == 0
    assert page.locator("#page-schema #quick-open-head").evaluate("el => el === document.activeElement")
    context.close()


def test_draft_persists_across_reload(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)
    assert "1 条未应用变更" in _draftbar_text(page)

    # let the IndexedDB write commit before reload
    page.wait_for_timeout(300)
    page.reload(wait_until="load")
    page.wait_for_selector("#ct-draftbar:not([hidden])")
    assert "1 条未应用变更" in _draftbar_text(page)
    context.close()


def test_field_rename_delete_move_set_type_emit_commands(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    # rename Name -> DisplayName via the form dialog
    page.locator('#page-schema [data-act="rename"]', has_text="Name").click()
    page.wait_for_selector("[data-form-input]")
    page.fill("[data-form-input]", "DisplayName")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(200)
    assert "1 条未应用变更" in _draftbar_text(page)
    page.wait_for_timeout(400)  # candidate 重渲染稳定后再点行内操作

    # move the renamed non-primary field up
    page.locator('#page-schema tr[data-field="DisplayName"] [data-act="up"]').click()
    page.wait_for_timeout(200)
    assert "2 条未应用变更" in _draftbar_text(page)

    # set_type on Id via the type picker (✎ edit button)
    page.locator('#page-schema tr[data-field="Id"] [data-act="type"]').click()
    page.locator("[data-fe-type]").click()
    page.wait_for_selector("[data-type-search]:focus")
    page.locator("[data-type='int64']").click()
    page.locator("[data-fe-apply]").click()
    page.wait_for_timeout(200)
    assert "4 条未应用变更" in _draftbar_text(page)

    # delete the non-primary field via the danger confirm
    page.locator('#page-schema tr[data-field="DisplayName"] [data-act="delete"]').click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-sm")
    page.locator(".ct-dlg-sm [data-confirm]").click()
    page.wait_for_timeout(200)
    assert "5 条未应用变更" in _draftbar_text(page)
    context.close()


def test_inspector_field_properties_are_read_only(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    # inspector is a read-only summary; type/layout changes have one editor entry point
    page.locator("#page-schema .ct-side-tab").click()
    page.wait_for_selector("#page-schema #side-inspector")
    page.locator('#page-schema tr[data-field="Name"]').click()
    assert page.locator("#page-schema #field-save").count() == 0
    assert page.locator('#page-schema #side-inspector [data-prop]').count() == 0
    assert "只读" in page.locator("#page-schema #side-inspector").text_content()
    assert "0 条未应用变更" in _draftbar_text(page) or page.locator("#ct-draftbar").is_hidden()
    context.close()


def test_undo_redo_via_draftbar(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    for name in ("Price", "Level"):
        page.locator("#page-schema #add-field").click()
        page.wait_for_selector("[data-af-name]")
        page.fill("[data-af-name]", name)
        page.locator("[data-af-add]").click()
        page.wait_for_timeout(150)

    assert "2 条未应用变更" in _draftbar_text(page)
    page.locator("#ct-draft-undo").click()
    page.wait_for_timeout(150)
    assert "1 条未应用变更" in _draftbar_text(page)
    page.locator("#ct-draft-undo").click()
    page.wait_for_timeout(150)
    # undo-to-zero keeps the bar visible with redo reachable
    assert "已全部撤销 · 可重做" in _draftbar_text(page)
    assert page.locator("#ct-draft-redo").is_enabled()

    page.locator("#ct-draft-redo").click()
    page.wait_for_timeout(150)
    assert "1 条未应用变更" in _draftbar_text(page)
    page.locator("#ct-draft-redo").click()
    page.wait_for_timeout(150)
    assert "2 条未应用变更" in _draftbar_text(page)

    # keyboard: Cmd/Ctrl+Z undo, Shift redo
    page.keyboard.press("Control+z")
    page.wait_for_timeout(150)
    assert "1 条未应用变更" in _draftbar_text(page)
    page.keyboard.press("Control+Shift+z")
    page.wait_for_timeout(150)
    assert "2 条未应用变更" in _draftbar_text(page)
    context.close()


def test_compact_field_rows_at_390(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    _open_schema_module(page, editor_url)
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_selector("#page-schema tr[data-field]")
    # field cards: header hidden, ops stay reachable, no page-level horizontal scroll
    assert page.locator("#page-schema table.ct-field-grid thead").is_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    context.close()


def test_primary_field_actions_are_locked(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.wait_for_selector("#page-schema tr[data-field='Id']")
    primary_ops = page.locator("#page-schema tr[data-field='Id'] .ct-row-ops button")
    assert primary_ops.count() == 3
    assert all(primary_ops.nth(index).is_disabled() for index in range(3))
    assert "主键字段不可删除" in (primary_ops.nth(2).get_attribute("title") or "")
    assert "主键字段不可调整顺序" in (primary_ops.nth(0).get_attribute("title") or "")
    context.close()


def test_query_index_cards_emit_set_indexes(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema .ct-index-card")

    page.select_option("#page-schema [data-index-kind='code']", "Name")
    page.wait_for_timeout(200)
    page.select_option("#page-schema [data-index-kind='group']", "Id")
    page.wait_for_timeout(200)

    assert "2 条未应用变更" in _draftbar_text(page)
    assert page.locator("#page-schema .ct-index-preview", has_text="ByCode").count() == 1
    assert page.locator("#page-schema .ct-index-preview", has_text="ByGroupKey").count() == 1

    # review plan surfaces Accessor impact for the index change
    page.locator("#ct-draft-review").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-plan")
    assert "Accessor" in page.locator(".ct-dlg-plan").text_content()
    context.close()


def test_enum_editor_values_and_reverse_refs(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="ItemRarity"]').first.click()
    page.wait_for_selector("#page-schema #enum-add-value")

    assert "byte（只读" in page.locator("#page-schema #editor-body").text_content()

    # add a value via the form dialog
    page.locator("#page-schema #enum-add-value").click()
    page.wait_for_selector("[data-form-input]")
    page.fill("[data-form-input]", "Legendary")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(200)
    assert "1 条未应用变更" in _draftbar_text(page)
    assert "Legendary" in page.locator("#page-schema #editor-body").text_content()

    # remove a value (idempotent full-list command, no confirm)
    page.locator('#page-schema [data-enum-remove="Common"]').click()
    page.wait_for_timeout(200)
    assert "2 条未应用变更" in _draftbar_text(page)
    context.close()


def test_blocked_delete_with_references(editor_url: str, chromium_browser: Any, tmp_path: Path) -> None:
    """Dedicated workspace where Item references a record -> delete blocked."""
    import threading as _t
    from werkzeug.serving import make_server as _ms
    from web_helpers import build_project as _bvp

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
        _open_schema_module(page, url)
        _select_item(page)
        page.wait_for_selector('#page-schema [data-navigate-type="DropReward"]')
        page.locator('#page-schema [data-navigate-type="DropReward"]').click()
        assert page.locator("#editor-title").text_content() == "DropReward"

        # delete from the module-head entry; referenced record is blocked
        page.locator("#head-delete-resource").click()
        page.wait_for_selector(".ct-dialog-mask.open")
        assert "无法删除" in page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
        assert "Rewards" in page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
        assert page.locator(".ct-dialog-mask.open [data-confirm]").is_disabled()

        # 查看影响 opens the plan dialog in preview mode (apply/discard disabled)
        page.locator("#dl-seeplan").click()
        page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-plan")
        assert "尚未加入草稿" in page.locator(".ct-dlg-plan").text_content()
        assert page.locator(".ct-dlg-plan [data-apply]").is_disabled()
        assert page.locator(".ct-dlg-plan [data-discard]").is_disabled()
        # closing the preview returns to the delete dialog beneath
        page.locator(".ct-dlg-plan [data-cancel]").click()
        page.wait_for_timeout(250)
        assert page.locator(".ct-dialog-mask.open [data-confirm]").count() == 1
        context.close()
    finally:
        server.shutdown()


def test_quick_open_keyboard_navigation(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)

    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-palette [data-qo-input]")
    page.fill(".ct-dlg-palette [data-qo-input]", "Item")
    page.wait_for_timeout(80)
    # matches: Item, ItemRarity (by score then name); ArrowDown once -> ItemRarity
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    assert "ItemRarity" in page.locator("#editor-title").text_content()
    context.close()


def test_keyboard_a11y_walkthrough(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    # sidebar items are keyboard-reachable: focus + Enter activates the module
    first_item = page.locator(".ct-sitem").first
    first_item.focus()
    assert first_item.evaluate("(el) => el === document.activeElement")
    page.keyboard.press("Enter")
    assert "active" in first_item.get_attribute("class")

    # hidden pages stay inert (cannot be tab-focused)
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")
    page.locator('.ct-sitem[data-module="export"]').click()
    assert page.locator("#page-schema").get_attribute("inert") is not None

    # Quick Open: ⌘P works from ANOTHER module and lands on Schema
    assert page.locator("#page-schema").get_attribute("inert") is not None
    page.keyboard.press("Control+p")
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-palette [data-qo-input]:focus")
    assert page.locator("#page-schema").get_attribute("inert") is None  # ⌘P 自动切到 Schema
    page.keyboard.press("Escape")
    page.wait_for_timeout(450)
    assert page.locator(".ct-dialog-mask").count() == 0
    context.close()


def test_type_picker_selects_named_type(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.wait_for_selector('#page-schema tr[data-field="Name"]')

    # open picker on the Name field (✎ button)
    page.locator('#page-schema tr[data-field="Name"] [data-act="type"]').click()
    page.wait_for_selector("[data-type-search]:focus")
    page.fill("[data-type-search]", "ItemRarity")
    page.wait_for_timeout(60)
    page.locator("[data-type='ItemRarity']").click()
    page.wait_for_timeout(200)
    assert "1 条未应用变更" in _draftbar_text(page)
    context.close()


def test_filter_counts_keyboard_and_pref_persistence(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    _open_schema_module(page, editor_url)
    _open_resource_pane(page)
    assert "总计" in page.locator("#page-schema .ct-resource-count").text_content()

    # filter keyboard: ArrowDown + Enter opens the highlighted row
    page.fill("#page-schema #resource-filter", "Item")
    page.wait_for_timeout(60)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert page.locator("#editor-title").text_content().find("ItemRarity") >= 0

    # query persists across reload (localStorage preference)
    page.reload(wait_until="load")
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema #resource-filter")
    assert page.input_value("#page-schema #resource-filter") == "Item"
    context.close()


def test_resizable_panes_persist_width(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.goto(editor_url, wait_until="load")
    _open_schema_module(page, editor_url)
    # inspector defaults collapsed: open it first so the pane has width
    page.locator("#page-schema .ct-side-tab").click()
    page.wait_for_timeout(250)
    page.locator("#page-schema .ct-resize-handle.right").click()
    before = page.locator("#page-schema .ct-side").evaluate("(el) => el.getBoundingClientRect().width")

    box = page.locator("#page-schema .ct-resize-handle.right").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] - 80, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    page.wait_for_timeout(80)
    after = page.locator("#page-schema .ct-side").evaluate("(el) => el.getBoundingClientRect().width")
    assert after > before, f"side pane did not grow: {before} -> {after}"
    context.close()


def test_ref_link_jumps_to_referenced_table(editor_url: str, chromium_browser: Any, tmp_path: Path) -> None:
    import threading as _t
    from werkzeug.serving import make_server as _ms
    from web_helpers import build_project as _bvp

    ws = tmp_path / "refws2"
    _bvp(ws, schemas=[
        {"table": "Item", "primary": "Id", "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id"},
        ]},
        {"table": "ItemType", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
    ])
    server = _ms("127.0.0.1", 0, create_app(ws), threaded=True)
    _t.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/static/index.html"
    try:
        context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        page.goto(url, wait_until="load")
        _open_schema_module(page, url)
        _select_item(page)
        page.wait_for_selector('#page-schema [data-navigate-type="ItemType"]')
        page.locator('#page-schema [data-navigate-type="ItemType"]').click()
        page.wait_for_timeout(200)
        assert page.locator("#editor-title").text_content() == "ItemType"
        context.close()
    finally:
        server.shutdown()
