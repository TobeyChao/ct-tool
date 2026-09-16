"""Browser tests for structured resource creation (tasks 3.1-3.4)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")


def _build(root: Path) -> Path:
    from web_helpers import build_project

    return build_project(
        root,
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32", "comment": "主键"},
                    {"name": "Name", "type": "string", "comment": "名称"},
                ],
            }
        ],
    )


@pytest.fixture
def create_server(tmp_path) -> Iterator[tuple[str, Path]]:
    workspace = _build(tmp_path / "ws")
    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/static/index.html", workspace
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


def _open_schema(page, url: str) -> None:
    page.goto(url, wait_until="load")
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")


def _open_pane(page) -> None:
    layout = page.locator("#page-schema .ct-workspace-layout")
    if layout.get_attribute("data-resource-open") != "true":
        page.locator("#page-schema #resource-toggle").click()
        page.wait_for_timeout(250)
        page.wait_for_selector("#page-schema .ct-resource-row")


def _close_dialog(page) -> None:
    """逐层取消所有打开中的弹窗（类型/引用选择器会叠在表单之上）。"""
    while page.locator(".ct-dialog-mask.open").count():
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)


def _wait_draftbar(page, text: str, timeout: int = 8000) -> None:
    page.wait_for_function(
        "(t) => { const el = document.getElementById('ct-draft-txt');"
        " return el && (el.textContent || '').includes(t); }",
        arg=text,
        timeout=timeout,
    )


def _create(page, kind: str, name: str, *, field: str = "", type_name: str = "", item: str = "") -> None:
    """通过头部入口完成一次创建（类别、名称，以及首字段/首项）。"""
    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    page.locator(f'[data-cr-kind="{kind}"]').click()
    page.fill("[data-cr-name]", name)
    if kind == "record":
        page.fill("[data-cr-field-name]", field)
        if type_name:
            page.locator("[data-cr-field-type]").click()
            page.wait_for_selector(f"[data-type-list] [data-type='{type_name}']")
            page.locator(f"[data-type-list] [data-type='{type_name}']").click()
            page.wait_for_timeout(100)
    if kind == "enum":
        page.fill("[data-cr-item-name]", item)
    page.locator("[data-submit]").click()
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)


def test_creation_entries_and_table_form(create_server, chromium_browser) -> None:
    url, workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    # 头部入口 + 分组入口（预选类别）
    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    assert page.locator('[data-cr-kind="table"]').get_attribute("class").find("active") >= 0
    _close_dialog(page)

    _open_pane(page)
    page.locator('#page-schema [data-create-kind="enum"]').click()
    page.wait_for_selector("[data-cr-name]")
    assert page.locator('[data-cr-kind="enum"]').get_attribute("class").find("active") >= 0
    assert page.locator("[data-cr-item]").is_visible()
    assert not page.locator("[data-cr-field]").is_visible()
    _close_dialog(page)

    # Table：固定 Id 主键、无需填首个字段
    _create(page, "table", "Quest")
    _wait_draftbar(page, "1 个资源有未保存修改")
    page.wait_for_selector('#page-schema .ct-resource-row[data-name="Quest"]')
    assert "Quest" in page.locator("#editor-title").text_content()
    grid = page.locator("#page-schema .ct-field-grid").text_content()
    assert "Id" in grid and "int32" in grid
    # 草稿而已：YAML 还没写
    assert not (workspace / "config" / "schemas" / "Quest.yaml").exists()
    context.close()


def test_create_from_empty_workspace(tmp_path, chromium_browser) -> None:
    from web_helpers import build_project

    workspace = build_project(tmp_path / "empty")
    server = make_server("127.0.0.1", 0, create_app(workspace), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/static/index.html"
        context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
        page = context.new_page()
        page.goto(url, wait_until="load")
        page.locator('.ct-sitem[data-module="schema"]').click()
        page.wait_for_selector("#page-schema .ct-workspace-layout")
        layout = page.locator("#page-schema .ct-workspace-layout")
        if layout.get_attribute("data-resource-open") != "true":
            page.locator("#page-schema #resource-toggle").click()
            page.wait_for_timeout(250)
        page.wait_for_selector("#page-schema #empty-create-resource")
        page.locator("#page-schema #empty-create-resource").click()
        page.wait_for_selector("[data-cr-name]")
        page.locator('[data-cr-kind="record"]').click()
        page.fill("[data-cr-name]", "DropReward")
        page.fill("[data-cr-field-name]", "Min")
        page.locator("[data-submit]").click()
        page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)
        _wait_draftbar(page, "1 个资源有未保存修改")
        assert page.locator("#editor-title").text_content() == "DropReward"
        context.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_forms_require_first_content_and_keep_input(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    # Record 缺首字段
    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    page.locator('[data-cr-kind="record"]').click()
    page.fill("[data-cr-name]", "DropReward")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(300)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    assert "首个字段" in page.locator("[data-cr-err]").text_content()
    assert page.locator("#ct-draftbar").is_hidden()

    # Enum 缺首项
    page.locator('[data-cr-kind="enum"]').click()
    page.fill("[data-cr-name]", "ItemRarity")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(300)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    assert "枚举项" in page.locator("[data-cr-err]").text_content()
    assert page.locator("#ct-draftbar").is_hidden()
    context.close()


def test_invalid_and_duplicate_names_add_no_command(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    # 非法名称
    page.fill("[data-cr-name]", "bad_name")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(250)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    assert page.locator("[data-cr-name]").input_value() == "bad_name"
    assert page.locator("#ct-draftbar").is_hidden()

    # 与已有资源重名（跨类别）
    page.fill("[data-cr-name]", "Item")
    page.locator('[data-cr-kind="enum"]').click()
    page.fill("[data-cr-item-name]", "Common")
    page.locator("[data-submit]").click()
    page.wait_for_timeout(250)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    assert "已被占用" in page.locator("[data-cr-err]").text_content()
    assert page.locator("#ct-draftbar").is_hidden()

    # 取消不增加命令
    _close_dialog(page)
    assert page.locator("#ct-draftbar").is_hidden()
    context.close()


def test_double_submit_adds_exactly_one_command(create_server, chromium_browser) -> None:
    url, workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    page.locator('[data-cr-kind="table"]').click()
    page.fill("[data-cr-name]", "Quest")
    # 同一个提交瞬间点两次：第二次必须被 submitting 守卫吞掉
    page.locator("[data-submit]").dispatch_event("click")
    page.locator("[data-submit]").dispatch_event("click")
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)
    _wait_draftbar(page, "1 个资源有未保存修改")
    page.wait_for_timeout(400)
    _open_pane(page)
    assert page.locator('#page-schema .ct-resource-row[data-name="Quest"]').count() == 1
    assert (page.locator("#page-schema .ct-resource-row").count()) == 2  # Item + Quest
    context.close()


def test_create_and_reference_without_saving(create_server, chromium_browser) -> None:
    url, workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    # Enum → Record（用新 Enum 当字段类型）→ Table（引用新 Record + ref 到新 Table）
    _create(page, "enum", "ItemRarity", item="Common")
    _wait_draftbar(page, "1 个资源有未保存修改")
    _create(page, "record", "DropReward", field="Rarity", type_name="ItemRarity")
    _wait_draftbar(page, "2 个资源有未保存修改")

    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    page.locator('[data-cr-kind="table"]').click()
    page.fill("[data-cr-name]", "Quest")
    page.locator("[data-submit]").click()
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)
    _wait_draftbar(page, "3 个资源有未保存修改")

    # 已有资源（Item）引用刚创建的类型与表：无需中间保存
    _open_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Item'")
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "Reward")
    page.locator("[data-af-type]").click()
    page.wait_for_selector("[data-type-list] [data-type='DropReward']")
    page.locator("[data-type-list] [data-type='DropReward']").click()
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(400)
    assert page.locator(".ct-dialog-mask").count() == 0, "字段预检失败导致弹窗未关闭"

    # 新 Table 只能作为 ref 目标出现（类型列表里没有 Quest）
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.fill("[data-af-name]", "QuestId")
    page.locator('.ct-dialog .ct-chip', has_text="引用").click()
    page.wait_for_selector("[data-ref-list] [data-ref='Quest.Id']")
    # 引用列表来自候选：刚创建的 Table 立即可选
    refs = [row.get_attribute("data-ref") for row in page.locator("[data-ref-list] [data-ref]").all()]
    assert "Quest.Id" in refs and "Item.Id" in refs
    # ref 是主键外键：引用列表只列主键，普通字段（Item.Name）不再可选
    assert "Item.Name" not in refs
    page.locator("[data-ref-list] [data-ref='Quest.Id']").click()
    page.locator("[data-af-add]").click()
    page.wait_for_timeout(300)

    grid = page.locator("#page-schema .ct-field-grid").text_content()
    names = page.evaluate(
        "() => [...document.querySelectorAll('#page-schema [data-field]')].map(e => e.dataset.field)"
    )
    assert "Reward" in grid and "QuestId" in grid, names

    # 类型选择器里 Table 不作为具名类型出现
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    page.locator("[data-af-type]").click()
    page.wait_for_selector("[data-type-list] [data-type='DropReward']")
    types = page.locator("[data-type-list] [data-type]").all_text_contents()
    assert any("DropReward" in text for text in types)
    assert not any(text.strip().startswith("Quest") for text in types)
    _close_dialog(page)

    # Quick Open 与计数来自候选（未保存也能找到）
    _open_pane(page)
    page.keyboard.press("Control+p")
    page.wait_for_selector("[data-qo-input]")
    page.fill("[data-qo-input]", "ItemRarity")
    page.wait_for_timeout(200)
    assert page.locator("[data-qo-list] [data-qo='ItemRarity']").count() >= 1
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert "4 总计" in page.locator("#resource-summary").text_content()
    assert not (workspace / "config" / "types" / "ItemRarity.yaml").exists()
    context.close()


def test_selection_follows_creation_and_falls_back_on_undo(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)
    _open_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Item'")

    _create(page, "table", "Quest")
    _wait_draftbar(page, "1 个资源有未保存修改")
    assert page.locator("#editor-title").text_content() == "Quest"

    # 撤销创建：选择退回最近仍存在的资源
    page.locator("#ct-draft-undo").click()
    page.wait_for_timeout(400)
    assert page.locator("#editor-title").text_content() == "Item"
    assert page.locator("#ct-draftbar").is_hidden() or "无未保存修改" in page.locator("#ct-draft-txt").text_content()

    # 重做：资源回到列表并可再次打开
    page.locator("#ct-draft-redo").click()
    _wait_draftbar(page, "1 个资源有未保存修改")
    _open_pane(page)
    assert page.locator('#page-schema .ct-resource-row[data-name="Quest"]').count() == 1
    context.close()


def test_created_draft_survives_refresh(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)
    _create(page, "enum", "ItemRarity", item="Common")
    _wait_draftbar(page, "1 个资源有未保存修改")
    page.wait_for_timeout(400)

    page.reload(wait_until="load")
    _open_schema(page, url)
    _wait_draftbar(page, "1 个资源有未保存修改")
    _open_pane(page)
    assert page.locator('#page-schema .ct-resource-row[data-name="ItemRarity"]').count() == 1
    context.close()


def test_unsaved_table_explains_template_requires_save(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)
    _create(page, "table", "Quest")
    _wait_draftbar(page, "1 个资源有未保存修改")

    # 新建（未保存）的 Table：明确说明先保存，且不提供模板生成入口
    page.wait_for_selector("#template-unsaved")
    assert "保存后才能生成模板" in page.locator("#template-unsaved").text_content()
    assert page.locator('.banner-gen-template[data-table="Quest"]').count() == 0
    note = page.locator("#template-note")
    assert note.count() == 0 or "Quest" not in (note.text_content() or "")

    # 保存后：入口变成模板待更新（若表模板缺失）
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    page.wait_for_timeout(300)
    assert page.locator("#template-unsaved").count() == 0
    page.wait_for_selector('.banner-gen-template[data-table="Quest"]')
    assert "Quest" in page.locator("#template-note").text_content()
    context.close()


def test_template_entry_survives_reload(create_server, chromium_browser) -> None:
    """保存新表后不更新模板，刷新页面（新会话）横幅入口依然存在且可用。"""
    url, workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)
    _create(page, "table", "Quest")
    _wait_draftbar(page, "1 个资源有未保存修改")
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    page.wait_for_selector('.banner-gen-template[data-table="Quest"]')

    # 刷新 = 丢弃全部会话内记忆（lastSavedTables 等），横幅必须由工作区状态重建
    page.reload(wait_until="load")
    _open_schema(page, url)
    page.wait_for_selector('.banner-gen-template[data-table="Quest"]')
    assert "Quest" in page.locator("#template-note").text_content()

    # 入口真实可用：点击后模板落盘，该表的入口收敛
    page.locator('.banner-gen-template[data-table="Quest"]').click()
    page.wait_for_selector('.banner-gen-template[data-table="Quest"]', state="detached")
    assert (workspace / "excel" / "Quest.xlsx").exists()

    # 模板生成进日志页的「模板」分类：该分类不再是「有按钮没人产出」的空壳
    page.locator('.ct-sitem[data-module="logs"]').click()
    page.wait_for_selector("#page-logs [data-module='模板']")
    page.locator("#page-logs [data-module='模板']").click()
    page.locator("#page-logs tr", has_text="生成模板：Quest").first.wait_for(timeout=3_000)
    context.close()


def test_record_and_enum_have_no_template_entry(create_server, chromium_browser) -> None:
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)
    _create(page, "enum", "ItemRarity", item="Common")
    _wait_draftbar(page, "1 个资源有未保存修改")
    page.locator("#ct-draft-save").click()
    page.wait_for_function(
        "() => { const bar = document.getElementById('ct-draftbar'); return !bar || bar.hidden; }",
        timeout=10000,
    )
    page.wait_for_timeout(400)
    # Enum 不是表：既没有“尚未保存”的模板提示，也没有针对它的模板入口
    assert page.locator("#template-unsaved").count() == 0
    assert page.locator('.banner-gen-template[data-table="ItemRarity"]').count() == 0
    page.wait_for_selector('#page-schema .ct-resource-row[data-name="ItemRarity"]')
    context.close()


def test_create_flow_keyboard_and_narrow_viewport(create_server, chromium_browser) -> None:
    """390px 窄屏 + 纯键盘：入口可达、初始焦点正确、Esc 取消不留命令、无横向溢出。"""
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(url, wait_until="load")
    page.locator("#ct-hamb").click()
    page.wait_for_timeout(250)
    page.locator('.ct-sitem[data-module="schema"]').click()
    page.wait_for_selector("#page-schema .ct-resource-row")

    # 头部入口可聚焦并打开表单，初始焦点在名称输入框
    page.locator("#page-schema #head-create-resource").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("[data-cr-name]")
    assert page.locator("[data-cr-name]").evaluate("el => el === document.activeElement")
    assert "active" in page.locator('[data-cr-kind="table"]').get_attribute("class")

    # Esc 取消：不加命令、不留草稿
    page.keyboard.press("Escape")
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)
    assert page.locator("#ct-draftbar").is_hidden()
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")

    # 键盘完成一次创建：窄屏表单可用
    page.locator("#page-schema #head-create-resource").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("[data-cr-name]")
    page.keyboard.type("Quest")
    page.keyboard.press("Enter")  # 焦点仍在输入框：回车不提交（表单无隐式提交）
    page.wait_for_timeout(200)
    assert page.locator(".ct-dialog-mask.open").count() == 1
    page.locator("[data-submit]").click()
    page.wait_for_selector(".ct-dialog-mask", state="detached", timeout=8000)
    _wait_draftbar(page, "1 个资源有未保存修改")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    context.close()


def test_record_ref_entry_removed_and_primary_rename_blocked(
    create_server, chromium_browser
) -> None:
    """ref 是表级主键外键：Record 不再有引用入口；表主键字段不可改名。"""
    url, _workspace = create_server
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    _open_schema(page, url)

    # 新增 Record：首字段不再提供「引用…」入口
    page.locator("#page-schema #head-create-resource").click()
    page.wait_for_selector("[data-cr-name]")
    page.locator('[data-cr-kind="record"]').click()
    assert page.locator("[data-cr-ref]").count() == 0
    _close_dialog(page)

    # Record 添加字段：引用约束不提供入口
    _create(page, "record", "DropReward", field="Min")
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'DropReward'")
    page.locator("#page-schema #add-field").click()
    page.wait_for_selector("[data-af-name]")
    assert page.locator("[data-af-ref]").is_disabled()
    _close_dialog(page)

    # Table 字段表：主键不可改名，普通字段仍可改名
    _open_pane(page)
    page.locator('#page-schema .ct-resource-row[data-name="Item"]').first.click()
    page.wait_for_function("() => document.querySelector('#editor-title').textContent === 'Item'")
    primary_rename = page.locator('#page-schema tr[data-field="Id"] [data-act="rename"]')
    assert primary_rename.is_disabled()
    assert primary_rename.get_attribute("title") == "主键字段不可改名"
    normal_rename = page.locator('#page-schema tr[data-field="Name"] [data-act="rename"]')
    assert normal_rename.is_enabled()
    context.close()
