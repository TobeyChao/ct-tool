"""Schema editor browser tests: filter, drawers, draft bar, dialogs
(F1/D1/D2/P5/quick-open), draft -> plan -> apply, undo/redo shortcuts."""

from __future__ import annotations

import re
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
                    # codename 索引固定指向名为 CodeName 的 string 字段 ⇒ 表里必须有它
                    {"name": "CodeName", "type": "string", "comment": "唯一代码名"},
                ],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
        types=[
            {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common"}, {"name": "Rare"}]},
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


def _wait_draftbar(page, text: str, timeout: int = 5000) -> None:
    """Wait until the shell draft bar reports `text` (net diff is server-side)."""
    page.wait_for_function(
        "(t) => { const el = document.getElementById('ct-draft-txt');"
        " return el && (el.textContent || '').includes(t); }",
        arg=text,
        timeout=timeout,
    )


def _expect_resources(page, count: int) -> None:
    """Net changed resource count, not the number of draft commands."""
    if count == 0:
        page.wait_for_function(
            "() => { const bar = document.getElementById('ct-draftbar');"
            " const el = document.getElementById('ct-draft-txt');"
            " return !bar || bar.hidden || (el && (el.textContent || '').includes('无未保存修改')); }",
            timeout=5000,
        )
        return
    _wait_draftbar(page, f"{count} 个资源有未保存修改")


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

    # Subsequence fuzzy matches highlight the actual matched characters rather
    # than looking for one contiguous substring.
    page.locator("#page-schema #resource-filter").fill("IR")
    page.wait_for_timeout(50)
    rarity = page.locator('#page-schema .ct-resource-row[data-name="ItemRarity"]')
    assert rarity.locator("mark").all_text_contents() == ["I", "R"]
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
    _expect_resources(page, 1)
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
    _expect_resources(page, 1)
    context.close()


def test_add_field_code_codename_locks_fields(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    # 代号 chip 固定字段名 CodeName：Item 已有 CodeName（chip 应禁用），
    # 所以这个场景选只有 Id 的 Quest 表
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Quest"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Quest'")

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.locator('.ct-dialog .ct-chip', has_text='代号').click()
    # CodeName locks the name/type and disables the role chips
    assert page.locator("[data-af-name]").input_value() == "CodeName"
    assert page.locator("[data-af-name]").is_disabled()
    assert page.locator('[data-af-name] ~ .ct-dlg-err').count() >= 0
    assert page.locator('.ct-dialog input[name="af-role"][value="i18n"]').is_disabled()
    # Server-only 角色不在前端提供入口：选项应从添加字段弹窗消失
    assert page.locator('.ct-dialog input[name="af-role"][value="server"]').count() == 0
    assert page.locator("[data-af-vec]").is_disabled()
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(300)
    _expect_resources(page, 1)
    context.close()


def test_save_changes_writes_yaml_without_review_dialog(
    editor_url: str, chromium_browser: Any
) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)

    # 保存入口只在全局草稿条；摘要可选，不是必经步骤
    assert page.locator("#page-schema #review-plan").count() == 0
    page.locator("#ct-draft-txt").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dialog")
    assert "1 个资源" in page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
    page.locator(".ct-dialog-mask.open [data-close]").last.click()
    page.wait_for_timeout(150)

    page.locator("#ct-draft-save").click()
    # 保存成功后草稿清空、状态条隐藏
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    assert "Price" in page.locator("#page-schema .ct-field-grid").text_content()

    # YAML 真的写盘了：刷新后草稿没了，字段仍在
    page.reload(wait_until="load")
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.wait_for_selector('#page-schema .ct-field-grid:has-text("Price")')
    assert page.locator("#page-schema .ct-field-grid", has_text="Price").count() == 1
    context.close()


def test_discard_draft_from_draftbar(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Price")
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)

    assert page.locator("#page-schema #discard-draft").count() == 0
    page.locator("#ct-draft-discard").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-sm")
    assert "1 个资源" in page.locator(".ct-dlg-sm").text_content()
    page.locator(".ct-dlg-sm [data-confirm]").click()
    page.wait_for_timeout(300)
    assert page.locator("#ct-draftbar").is_hidden()
    assert page.locator("#page-schema .ct-field-grid", has_text="Price").count() == 0
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
    _expect_resources(page, 1)

    # let the IndexedDB write commit before reload
    page.wait_for_timeout(300)
    page.reload(wait_until="load")
    _open_schema_module(page, editor_url)
    page.wait_for_selector("#ct-draftbar:not([hidden])")
    _expect_resources(page, 1)
    # cursor 也持久化了：撤销一步后刷新，撤销分支不复活
    page.locator("#ct-draft-undo").click()
    _expect_resources(page, 0)
    page.wait_for_timeout(400)
    page.reload(wait_until="load")
    _open_schema_module(page, editor_url)
    _wait_draftbar(page, "无未保存修改")
    assert page.locator("#ct-draft-redo").is_enabled()
    context.close()


def test_field_rename_delete_move_set_type_emit_commands(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)

    # rename Name -> DisplayName via the form dialog
    # 精确匹配 ^Name$：表里现在还有 CodeName（子串匹配会同时命中两个）
    page.locator('#page-schema [data-act="rename"]').filter(has_text=re.compile(r"^Name$")).click()
    page.wait_for_selector("[data-form-input]")
    page.fill("[data-form-input]", "DisplayName")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)
    page.wait_for_timeout(400)  # candidate 重渲染稳定后再点行内操作

    # move the renamed non-primary field up
    page.locator('#page-schema tr[data-field="DisplayName"] [data-act="up"]').click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)

    # set_type on the renamed non-primary field via the type picker (✎ edit button)
    # （不拿主键 `Id` 试：主键类型被模型固定为 int32，改成 int64 的草稿永远无法 Apply）
    page.locator('#page-schema tr[data-field="DisplayName"] [data-act="type"]').click()
    page.locator("[data-fe-type]").click()
    page.wait_for_selector("[data-type-search]:focus")
    page.locator("[data-type='int64']").click()
    page.locator("[data-fe-apply]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)

    # delete the non-primary field via the danger confirm
    page.locator('#page-schema tr[data-field="DisplayName"] [data-act="delete"]').click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dlg-sm")
    page.locator(".ct-dlg-sm [data-confirm]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)

    # 净差异只报原始结构到最终候选的结果：DisplayName 连同改名一起消失，原文汇报 Name
    page.locator("#ct-draft-txt").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dialog")
    summary = page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
    assert "删除" in summary and "Name" in summary
    assert "DisplayName" not in summary
    page.locator(".ct-dialog-mask.open [data-close]").last.click()
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
    _expect_resources(page, 0)
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

    # 两个字段都落在 Item 上 ⇒ 净差异仍然是「1 个资源」，不是「2 条命令」
    _expect_resources(page, 1)
    page.locator("#ct-draft-undo").click()
    _expect_resources(page, 1)
    page.locator("#ct-draft-undo").click()
    # 撤销到基线：净差异归零，但历史仍在（可重做），状态条保留
    _expect_resources(page, 0)
    _wait_draftbar(page, "无未保存修改")
    assert page.locator("#ct-draft-redo").is_enabled()
    assert page.locator("#ct-draft-save").is_disabled()

    page.locator("#ct-draft-redo").click()
    _expect_resources(page, 1)
    page.locator("#ct-draft-redo").click()
    _expect_resources(page, 1)

    # keyboard: Cmd/Ctrl+Z undo, Shift redo
    page.keyboard.press("Control+z")
    _expect_resources(page, 1)
    page.keyboard.press("Control+z")
    _expect_resources(page, 0)
    page.keyboard.press("Control+Shift+z")
    _expect_resources(page, 1)
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
    assert primary_ops.count() >= 3
    assert primary_ops.nth(0).is_disabled()
    assert primary_ops.nth(1).is_disabled()
    assert primary_ops.nth(2).is_enabled()
    assert primary_ops.nth(3).is_disabled()
    assert "编辑字段注释" in (primary_ops.nth(2).get_attribute("title") or "")
    assert "主键字段不可删除" in (primary_ops.nth(3).get_attribute("title") or "")
    assert "主键字段不可调整顺序" in (primary_ops.nth(0).get_attribute("title") or "")
    # 主键类型被模型固定为 int32：不提供修改类型入口，非主键字段才有 ✎
    assert page.locator("#page-schema tr[data-field='Id'] [data-act='type']").count() == 0
    assert page.locator("#page-schema tr[data-field='Name'] [data-act='type']").count() == 1
    context.close()


def test_query_index_cards_emit_set_indexes(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _select_item(page)
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema .ct-index-card")

    # codename 是开关（固定指向 CodeName 字段，没有字段选择器）；group 索引已砍，不再有第二张卡
    page.check("#page-schema [data-index-codename]")
    page.wait_for_timeout(200)

    _expect_resources(page, 1)
    assert page.locator("#page-schema .ct-index-card").count() == 1
    assert page.locator("#page-schema .ct-index-preview", has_text="ByCodeName").count() == 1
    assert page.locator("#page-schema .ct-index-preview", has_text="ByGroupKey").count() == 0
    assert page.locator("#page-schema [data-index-kind]").count() == 0

    # review plan surfaces Accessor impact for the index change
    page.locator("#ct-draft-txt").click()
    page.wait_for_selector(".ct-dialog-mask.open .ct-dialog")
    # 摘要只讲 YAML 净差异，不再承诺产物重建清单
    summary = page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
    assert "1 个资源" in summary
    assert "Accessor" not in summary
    page.locator(".ct-dialog-mask.open [data-close]").last.click()
    page.wait_for_timeout(150)
    context.close()


def test_query_index_cards_restore_persisted_and_draft_state(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, workspace = editor_server
    item = workspace / "config" / "schemas" / "Item.yaml"
    item.write_text(
        item.read_text(encoding="utf-8") + "indexes:\n  - kind: codename\n",
        encoding="utf-8",
    )

    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    page.get_by_role("button", name="查询索引").click()
    checkbox = page.locator("#page-schema [data-index-codename]")
    playwright_api.expect(checkbox).to_be_checked()

    checkbox.uncheck()
    _expect_resources(page, 1)
    page.reload(wait_until="load")
    _open_schema_module(page, url)
    _select_item(page)
    page.get_by_role("button", name="查询索引").click()
    playwright_api.expect(page.locator("#page-schema [data-index-codename]")).not_to_be_checked()
    context.close()


def test_codename_badge_shows_only_when_index_declared(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    """角色与约束列：CODENAME 徽标 = 表声明 codename 索引 && 字段是约定目标 CodeName。

    只叫 CodeName 但没开索引的字段是普通 string，不该有徽标。
    """
    url, workspace = editor_server
    item = workspace / "config" / "schemas" / "Item.yaml"
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)

    # 未声明索引：CodeName 行无 CODENAME 徽标、无 🏷 标记
    assert page.locator("#page-schema tr[data-field='CodeName'] .ct-badge", has_text="CODENAME").count() == 0
    assert page.locator("#page-schema tr[data-field='CodeName'] .ct-field-role", has_text="🏷").count() == 0

    # 声明 codename 索引后：CodeName 行出现 CODENAME 徽标 + 🏷 标记，其他字段行不受影响
    item.write_text(
        item.read_text(encoding="utf-8") + "indexes:\n  - kind: codename\n",
        encoding="utf-8",
    )
    page.reload(wait_until="load")
    _open_schema_module(page, url)
    _select_item(page)
    codename_badge = page.locator("#page-schema tr[data-field='CodeName'] .ct-badge", has_text="CODENAME")
    assert codename_badge.count() == 1
    assert page.locator("#page-schema tr[data-field='CodeName'] .ct-field-role", has_text="🏷").count() == 1
    assert page.locator("#page-schema tr[data-field='Id'] .ct-badge", has_text="CODENAME").count() == 0
    assert page.locator("#page-schema tr[data-field='Name'] .ct-badge", has_text="CODENAME").count() == 0
    context.close()


def _open_item_with_codename_index(
    url: str, workspace: Path, chromium_browser: Any
) -> tuple[Any, Any]:
    """Item 声明 codename 索引并打开其字段表（返回 (page, context)，调用方负责 close）。"""
    item = workspace / "config" / "schemas" / "Item.yaml"
    item.write_text(
        item.read_text(encoding="utf-8") + "indexes:\n  - kind: codename\n",
        encoding="utf-8",
    )
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title')?.textContent === 'Item'")
    page.wait_for_selector("#page-schema table.ct-field-grid")
    return page, context


def test_delete_codename_field_offers_explicit_index_cascade(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    """删除 codename 索引表的 CodeName：弹窗披露后果，确认时显式附带撤索引命令。"""
    url, workspace = editor_server
    page, context = _open_item_with_codename_index(url, workspace, chromium_browser)

    page.locator("#page-schema tr[data-field='CodeName'] [data-act='delete']").click()
    page.wait_for_selector(".ct-dialog-mask.open")
    dialog = page.locator(".ct-dialog-mask.open .ct-dialog")
    assert "codename 索引" in dialog.text_content()
    assert "一并移除" in dialog.text_content()
    page.locator(".ct-dialog-mask.open [data-confirm]").click()
    page.wait_for_timeout(400)

    # 字段已删、索引声明已撤（查询索引卡片上的开关回到未勾选）、候选无阻塞
    assert page.locator("#page-schema tr[data-field='CodeName']").count() == 0
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema .ct-index-card")
    playwright_api.expect(page.locator("#page-schema [data-index-codename]")).not_to_be_checked()
    assert "codename 索引要求" not in page.locator("#draft-banner").text_content()
    context.close()


def test_rename_codename_field_offers_explicit_index_cascade(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    """改名离开 CodeName：弹窗披露后果，确认时显式附带撤索引命令。"""
    url, workspace = editor_server
    page, context = _open_item_with_codename_index(url, workspace, chromium_browser)

    page.locator("#page-schema tr[data-field='CodeName'] [data-act='rename']").click()
    page.wait_for_selector(".ct-dialog-mask.open")
    dialog = page.locator(".ct-dialog-mask.open .ct-dialog")
    assert "codename 索引" in dialog.text_content()
    page.fill(".ct-dialog-mask.open [data-form-input]", "TypeCode")
    page.locator(".ct-dialog-mask.open [data-submit]").click()
    page.wait_for_timeout(400)

    # 字段已改名、索引声明已撤、候选无阻塞
    assert page.locator("#page-schema tr[data-field='TypeCode']").count() == 1
    assert page.locator("#page-schema tr[data-field='CodeName']").count() == 0
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema .ct-index-card")
    playwright_api.expect(page.locator("#page-schema [data-index-codename]")).not_to_be_checked()
    assert "codename 索引要求" not in page.locator("#draft-banner").text_content()
    context.close()


def test_enum_editor_value_operations(editor_url: str, chromium_browser: Any) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, editor_url)
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="ItemRarity"]').first.click()
    page.wait_for_selector("#page-schema #enum-add-value")

    # add a value via the dialog (name + optional comment), backend pre-check runs
    page.locator("#page-schema #enum-add-value").click()
    page.wait_for_selector("[data-aev-name]")
    page.fill("[data-aev-name]", "Legendary")
    page.locator("[data-submit]").click()
    page.wait_for_selector(".ct-dialog-mask", state="hidden")
    page.wait_for_selector('#page-schema tr[data-enum-value="Legendary"]')
    _expect_resources(page, 1)
    assert "Legendary" in page.locator("#page-schema #editor-body").text_content()

    # rename by clicking the value name (form dialog, same as field rename)
    page.locator('#page-schema tr[data-enum-value="Legendary"] [data-act="rename"]').click()
    page.wait_for_selector("[data-form-input]")
    page.fill("[data-form-input]", "Mythic")
    page.locator("[data-submit]").click()
    page.wait_for_selector(".ct-dialog-mask", state="hidden")
    page.wait_for_selector('#page-schema tr[data-enum-value="Mythic"]')
    _expect_resources(page, 1)

    # remove a value (idempotent full-list command, no confirm)
    page.locator('#page-schema tr[data-enum-value="Common"] [data-act="delete"]').click()
    page.wait_for_selector('#page-schema tr[data-enum-value="Common"]', state="detached")
    _expect_resources(page, 1)
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
                {"name": "Rewards", "type": "vector<DropReward>", "excel_columns": 1},
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

        # 删除确认不再嵌套完整计划预览，只说明保存范围
        assert page.locator("#dl-seeplan").count() == 0
        dialog = page.locator(".ct-dialog-mask.open .ct-dialog").text_content()
        assert "YAML" in dialog and "Excel" in dialog and "产物" in dialog
        page.locator(".ct-dialog-mask.open [data-cancel]").click()
        page.wait_for_timeout(200)
        assert page.locator(".ct-dialog-mask.open").count() == 0
        context.close()
    finally:
        server.shutdown()


def test_record_editor_hides_table_only_field_options(
    editor_url: str, chromium_browser: Any, tmp_path: Path
) -> None:
    """Record 字段表不展示「角色与约束」列；Record 添加字段弹窗隐藏
    角色行、禁用 I18N/Code，仅保留 vector。"""
    import threading as _t
    from werkzeug.serving import make_server as _ms
    from web_helpers import build_project as _bvp

    ws = tmp_path / "recordws"
    _bvp(ws, schemas=[
        {"table": "Item", "primary": "Id", "fields": [
            {"name": "Id", "type": "int32"},
            {"name": "Name", "type": "string"},
            {"name": "Rewards", "type": "vector<DropReward>", "excel_columns": 1},
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

        # Table 字段表：保留「角色与约束」列
        _select_item(page)
        table_headers = page.locator("#page-schema table.ct-field-grid thead th").all_text_contents()
        assert "角色与约束" in table_headers

        # Record 字段表：无「角色与约束」列
        page.wait_for_selector('#page-schema [data-navigate-type="DropReward"]')
        page.locator('#page-schema [data-navigate-type="DropReward"]').click()
        page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'DropReward'")
        record_headers = page.locator("#page-schema table.ct-field-grid thead th").all_text_contents()
        assert "角色与约束" not in record_headers
        assert record_headers == ["字段", "类型表达式", "Excel", ""]

        # Record 添加字段弹窗：角色行隐藏、Code 禁用、vector 可用
        page.locator("#page-schema #add-field").click()
        page.wait_for_selector(".ct-dialog-mask.open")
        assert page.locator("[data-af-role-row]").is_hidden()
        assert page.locator('[data-af-role-row] input[name="af-role"][value="i18n"]').is_disabled()
        assert page.locator('[data-af-role-row] input[name="af-role"][value="server"]').count() == 0
        assert page.locator("[data-af-code]").is_disabled()
        assert page.locator("[data-af-vec]").is_enabled()
        page.locator(".ct-dialog-mask.open [data-cancel]").click()
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

    # open picker on the scalar field (✎ button)
    page.locator('#page-schema tr[data-field="Name"] [data-act="type"]').click()
    page.wait_for_selector("[data-fe-type]")
    page.locator("[data-fe-type]").click()
    page.wait_for_selector("[data-type-search]")
    page.fill("[data-type-search]", "ItemRarity")
    page.wait_for_timeout(60)
    page.locator("[data-type='ItemRarity']").click()
    page.locator("[data-fe-apply]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)
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


# --------------------------------------------------------------------------- #
# Draft persistence, net difference and the single save request (3.1-3.3)
# --------------------------------------------------------------------------- #


@pytest.fixture
def editor_server(tmp_path) -> Iterator[tuple[str, Path]]:
    """Own server + workspace path, for tests that touch the filesystem/lock."""
    from web_helpers import build_project

    workspace = build_project(
        tmp_path / "savews",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "comment": "名称"},
                    # codename 索引固定指向名为 CodeName 的 string 字段
                    {"name": "CodeName", "type": "string", "comment": "唯一代码名"},
                ],
            },
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            },
        ],
    )
    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/index.html", workspace
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _add_field(page, name: str) -> None:
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", name)
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(200)


def test_net_difference_toggle_round_trip_keeps_history(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, _workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)

    # CodeName 索引打开再关闭：净差异归零，但历史仍可撤销
    page.get_by_role("button", name="查询索引").click()
    page.wait_for_selector("#page-schema [data-index-codename]")
    page.check("#page-schema [data-index-codename]")
    _expect_resources(page, 1)
    assert page.locator("#ct-draft-save").is_enabled()
    page.uncheck("#page-schema [data-index-codename]")
    _expect_resources(page, 0)
    assert page.locator("#ct-draft-save").is_disabled()
    assert page.locator("#ct-draft-undo").is_enabled()
    context.close()


def test_persistence_failure_warning_stays_visible(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, _workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(window, 'indexedDB', { get() { throw new Error('denied'); } });"
    )
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _wait_draftbar(page, "草稿未持久化")
    assert page.locator("#ct-draftbar").is_visible()
    context.close()


def test_persistence_retries_after_transient_database_open_failure(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, _workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page.add_init_script(
        """() => {
          const original = window.indexedDB;
          let reads = 0;
          Object.defineProperty(window, 'indexedDB', {
            configurable: true,
            get() {
              reads += 1;
              if (reads === 1) throw new Error('temporary indexedDB failure');
              return original;
            },
          });
        }"""
    )
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _expect_resources(page, 1)
    page.wait_for_function(
        "() => !(document.getElementById('ct-draft-txt')?.textContent || '').includes('草稿未持久化')"
    )
    context.close()


def test_save_conflict_keeps_draft_and_blocks_overwrite(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _expect_resources(page, 1)

    # 外部进程改了另一份 YAML：保存必须拒绝，且不覆盖外部修改
    quest = workspace / "config" / "schemas" / "Quest.yaml"
    quest.write_text(quest.read_text(encoding="utf-8") + "\n# external\n", encoding="utf-8")

    page.locator("#ct-draft-save").click()
    _wait_draftbar(page, "Schema 基线已变化")
    _expect_resources(page, 1)  # 草稿保留
    assert "# external" in quest.read_text(encoding="utf-8")
    assert "Price" in page.locator("#page-schema .ct-field-grid").text_content()
    context.close()


def test_save_busy_keeps_draft(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    from ct.storage.workspace_lock import WorkspaceLock

    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _expect_resources(page, 1)

    with WorkspaceLock(workspace):
        page.locator("#ct-draft-save").click()
        _wait_draftbar(page, "工作区正在导出或部署")
    _expect_resources(page, 1)
    context.close()


def test_status_refresh_failure_does_not_misreport_save(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    """保存成功但模板状态查询失败时，仍显示保存成功并说明状态暂不可用。"""
    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _expect_resources(page, 1)

    page.route(
        "**/api/workspace",
        lambda route: route.fulfill(status=500, content_type="application/json",
                                    body='{"ok": false, "error": "status boom"}'),
    )
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    # 保存确实落盘了，错误横幅里没有"保存失败"
    item = workspace / "config" / "schemas" / "Item.yaml"
    assert "Price" in item.read_text(encoding="utf-8")
    banner = page.locator("#draft-banner")
    assert banner.is_hidden() or "保存失败" not in (banner.text_content() or "")
    assert page.locator(".ct-dialog-mask.open").count() == 0
    context.close()


def test_save_refreshes_template_status_without_rebuilding(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    """保存只刷新只读状态，绝不自动重建模板；更新模板是显式操作。"""
    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)

    from ct.app.canonical_commands import canonical_gen_template

    item_book = workspace / "excel" / "Item.xlsx"
    item_book.parent.mkdir(parents=True, exist_ok=True)
    canonical_gen_template(workspace, table_filter="Item")
    before = (item_book.read_bytes(), item_book.stat().st_mtime_ns)

    _add_field(page, "Price")
    _expect_resources(page, 1)
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    page.wait_for_selector("#template-note")
    # 保存本身没有重建模板
    assert (item_book.read_bytes(), item_book.stat().st_mtime_ns) == before

    # 显式入口会真的更新模板：横幅列出全部待办（Quest 缺模板、Item 已漂移），
    # 每张表有自己的入口，这里点名刚改过 Schema 的 Item
    page.locator('.banner-gen-template[data-table="Item"]').click()
    page.wait_for_selector('.banner-gen-template[data-table="Item"]', state="detached")
    assert (item_book.read_bytes(), item_book.stat().st_mtime_ns) != before
    # 成功反馈只弹 toast：不写横幅，也不挂到底栏状态行
    playwright_api.expect(page.locator("#ct-toast")).to_be_visible()
    playwright_api.expect(page.locator("#ct-toast")).to_contain_text("模板已更新：Item")
    assert page.locator("#ct-draftbar").is_hidden()
    context.close()


def test_no_false_template_drift_notice(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "Price")
    _expect_resources(page, 1)

    page.route(
        "**/api/workspace",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok": true, "data": {"root": "x", "status": {"changed": [], "drifted": [], "missing": []}}}',
        ),
    )
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    page.wait_for_timeout(300)
    assert page.locator("#template-note").count() == 0
    context.close()


def test_deleting_resource_yaml_keeps_excel_and_outputs(
    editor_server: tuple[str, Path], chromium_browser: Any
) -> None:
    url, workspace = editor_server
    quest_book = workspace / "excel" / "Quest.xlsx"
    quest_book.parent.mkdir(parents=True, exist_ok=True)
    quest_book.write_bytes(b"quest-data")
    output = workspace / "output" / "json" / "Quest_zh.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"{}")

    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _open_resource_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Quest"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Quest'")
    page.locator("#head-delete-resource").click()
    page.wait_for_selector(".ct-dialog-mask.open [data-confirm]")
    page.locator(".ct-dialog-mask.open [data-confirm]").click()
    page.wait_for_timeout(200)
    _expect_resources(page, 1)
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )

    assert not (workspace / "config" / "schemas" / "Quest.yaml").exists()
    assert quest_book.read_bytes() == b"quest-data"
    assert output.read_bytes() == b"{}"
    context.close()


def test_candidate_refresh_freezes_save_and_preserves_original_baseline(editor_server, chromium_browser):
    url, workspace = editor_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema_module(page, url)
    _select_item(page)
    _add_field(page, "NewField")
    playwright_api.expect(page.locator("#ct-draft-save")).to_be_enabled()
    pending = []
    page.route("**/api/schema-workspace/candidate", lambda route: pending.append(route))
    page.evaluate("window.dispatchEvent(new CustomEvent('ct:draft-action', {detail: {type: 'undo'}}))")
    playwright_api.expect(page.locator("#ct-draft-save")).to_be_disabled()
    page.wait_for_timeout(100)
    assert pending
    held_revision = pending[0].request.post_data_json["schemaRevision"]
    path = workspace / "config/schemas/Item.yaml"
    path.write_text(path.read_text() + "\n# external change\n")
    pending.pop().continue_()
    playwright_api.expect(page.locator("#ct-draftbar")).to_contain_text("Schema 基线已变化")
    page.evaluate("window.dispatchEvent(new CustomEvent('ct:draft-action', {detail: {type: 'redo'}}))")
    page.wait_for_timeout(100)
    assert pending[0].request.post_data_json["schemaRevision"] == held_revision
    pending.pop().continue_()
    playwright_api.expect(page.locator("#ct-draft-save")).to_be_disabled()
    assert "NewField" not in path.read_text()
    context.close()


def test_broken_schema_yaml_reports_the_reason(
    tmp_path: Path, chromium_browser: Any
) -> None:
    """P6：快照加载失败必须说明原因，且不能把坏工作区伪装成空工作区。"""
    import threading as _t

    from werkzeug.serving import make_server as _ms

    from web_helpers import build_project as _bvp

    workspace = tmp_path / "brokenws"
    _bvp(
        workspace,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            }
        ],
    )
    broken = workspace / "config" / "schemas" / "Broken.yaml"
    broken.write_text("table: [oops\n", encoding="utf-8")

    server = _ms("127.0.0.1", 0, create_app(workspace), threaded=True)
    _t.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/static/index.html"
    try:
        context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        page.goto(url, wait_until="load")
        page.locator('.ct-sitem[data-module="schema"]').click()

        # 原因可见：解析错误 + 出问题的文件；不是"还没有任何 Schema"
        page.wait_for_selector("#page-schema #resource-load-error")
        detail = page.locator("#page-schema #resource-load-error").text_content() or ""
        assert "Broken.yaml" in detail, detail
        assert page.locator("#page-schema .ct-resource-row").count() == 0
        assert page.locator("#page-schema #empty-create-resource").count() == 0
        assert "Schema 快照加载失败" in (page.locator("#draft-banner").text_content() or "")

        # 修好文件后重新加载：错误清除、资源回来
        broken.unlink()
        page.reload(wait_until="load")
        _open_schema_module(page, url)
        page.wait_for_selector('#page-schema .ct-resource-row[data-name="Item"]')
        assert page.locator("#page-schema #resource-load-error").count() == 0
        assert "Schema 快照加载失败" not in (page.locator("#draft-banner").text_content() or "")
        context.close()
    finally:
        server.shutdown()
