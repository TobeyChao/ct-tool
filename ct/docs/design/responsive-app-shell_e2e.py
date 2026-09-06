# -*- coding: utf-8 -*-
"""responsive-app-shell.html E2E 回归（含添加字段「角色 × 约束」互斥规则）。

用法（仓库根目录）:
    python3 -m http.server 8899          # 另起终端
    ct/.venv/bin/python ct/docs/design/responsive-app-shell_e2e.py --base http://127.0.0.1:8899

或直接运行（脚本自起临时 http 服务，端口自选）:
    ct/.venv/bin/python ct/docs/design/responsive-app-shell_e2e.py

依赖: playwright（ct/.venv 已装）。
覆盖: 既有交互路径回归 + fix-field-role-constraint-rules 的
      必填/主键勾选移除(2.1) / 代号字段 Code 锁定(2.2) /
      类型×角色联动(2.3) / 一表至多一个 Code(2.4) /
      非 vector 分隔符(2.5) 用例。
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = "ct/docs/design/responsive-app-shell.html"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + detail) if detail else "")


def _serve(root_dir: str):
    handler = http.server.SimpleHTTPRequestHandler
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return port, httpd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None, help="已有 http 服务地址（默认自起临时服务）")
    args = parser.parse_args()

    httpd = None
    if args.base:
        base = args.base
    else:
        port, httpd = _serve(".")
        base = f"http://127.0.0.1:{port}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/{ROOT}", wait_until="load")
        page.wait_for_timeout(400)

        def dbg():
            return page.evaluate("window.__dbg()")

        def clear_draft():
            page.evaluate("clearDraft()")

        def open_schema():
            page.click(".sitem[data-page='schema']")
            page.wait_for_timeout(200)

        # ---- 既有路径回归（B1/B7/C4/B3/B8） ----
        open_schema()
        page.click("#add-field")
        page.fill("#af-name", "Foo")
        page.click("#af-add")
        page.wait_for_timeout(200)
        check("reg-b1-draftbar", "1 条" in page.text_content("#draftbar-txt"), page.text_content("#draftbar-txt"))
        page.click("#draft-review")
        page.wait_for_timeout(300)
        check("reg-b1-impacts", page.locator(".impacts .impact").count() == 2, "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.click("#add-field")
        page.fill("#af-name", "Bar")
        page.click("#af-add")
        page.wait_for_timeout(200)
        page.click("#draft-undo")
        page.wait_for_timeout(200)
        check("reg-b7-cursor", "1 条" in page.text_content("#draftbar-txt"), "")
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'z',metaKey:true,bubbles:true,cancelable:true}))")
        page.wait_for_timeout(200)
        check("reg-c4-cmdz", dbg()["cursor"] == 0, str(dbg()["cursor"]))
        # reg-b7b 撤销归零:草稿栏保持可见(已全部撤销 · 可重做),重做按钮可达、审查禁用
        bar_hidden = page.evaluate("document.getElementById('draftbar').hidden")
        check("reg-b7b-bar-kept", not bar_hidden
              and "已全部撤销" in page.text_content("#draftbar-txt")
              and not page.evaluate("document.getElementById('draft-redo').disabled")
              and page.evaluate("document.getElementById('draft-review').disabled"), "")
        page.click("#draft-redo")
        page.wait_for_timeout(200)
        check("reg-b7b-redo-works", dbg()["cursor"] == 1
              and "1 条" in page.text_content("#draftbar-txt"), "")
        page.click("#draft-undo")
        page.wait_for_timeout(200)
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'z',metaKey:true,shiftKey:true,bubbles:true,cancelable:true}))")
        page.wait_for_timeout(200)
        clear_draft()

        # ---- 2.1 必填/主键移除 + ref 只读提示 + 草稿无 req/pk ----
        page.click("#add-field")
        page.wait_for_timeout(200)
        check("2.1-no-req-checkbox", page.locator("#af-req").count() == 0, "")
        check("2.1-no-pk-checkbox", page.locator("#af-pk").count() == 0, "")
        # ref 类型选择 → 只读提示出现（#af-msg）
        page.click("#af-type")
        page.wait_for_timeout(200)
        page.click(".dlg-row[data-v='ItemType.Id']")
        page.wait_for_timeout(200)
        check("2.1-ref-hint", page.locator("#af-msg").is_visible()
              and "ref 外键" in page.text_content("#af-msg"), page.text_content("#af-msg"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # 普通 scalar 提交 → 命令不含 req/pk/sep
        page.click("#add-field")
        page.fill("#af-name", "Plain")
        page.click("#af-add")
        page.wait_for_timeout(200)
        cmd = [c for c in dbg()["cmds"] if c.get("field") == "Plain"][-1]
        check("2.1-no-req-pk-in-cmd", "req" not in cmd and "pk" not in cmd, str(cmd))
        check("2.5-scalar-no-sep-in-cmd", "sep" not in cmd, str(cmd))
        clear_draft()

        # ---- 2.2 代号字段（Code）锁定：Item（无 Code）可添加 ----
        page.click("#add-field")
        page.wait_for_timeout(200)
        page.click("label.chip:has(#af-code)")
        page.wait_for_timeout(200)
        check("2.2-code-name-locked", page.locator("#af-name").input_value() == "Code"
              and page.locator("#af-name").is_disabled(), "")
        check("2.2-code-type-locked", page.text_content("#af-type-txt").strip() == "string"
              and page.locator("#af-type").is_disabled(), "")
        check("2.2-code-role-locked", page.locator("input[name='af-role'][value='i18n']").is_disabled()
              and page.locator("input[name='af-role'][value='server']").is_disabled(), "")
        check("2.2-code-msg", "Code 索引要求" in page.text_content("#af-msg"), page.text_content("#af-msg"))
        page.click("#af-add")
        page.wait_for_timeout(200)
        ok = any(c.get("field") == "Code" and c.get("fieldType") == "string" and c.get("role") == ""
                for c in dbg()["cmds"])
        check("2.2-code-cmd-ok", ok, str(dbg()["cmds"]))
        clear_draft()

        # ---- 2.3 类型 × 角色联动（I18N 仅 string） ----
        page.click("#add-field")
        page.wait_for_timeout(200)
        page.click("label.chip:has(input[name='af-role'][value='i18n'])")
        page.wait_for_timeout(200)
        page.click("#af-type")
        page.wait_for_timeout(300)
        rows = page.evaluate("[...document.querySelectorAll('.dlg-row')].map(b=>b.dataset.v)")
        check("2.3-i18n-only-string", rows == ["string"], str(rows))
        check("2.3-i18n-hint", "仅支持 string" in page.locator(".mask").last.locator(".dbody").text_content(), "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # 提交兜底：I18N + 非 string（默认 int32）→ 拦截、不入草稿
        page.fill("#af-name", "BadI18N")
        page.click("#af-add")
        page.wait_for_timeout(200)
        check("2.3-i18n-submit-blocked", page.locator("#af-msg").is_visible()
              and "仅支持 string" in page.text_content("#af-msg"), page.text_content("#af-msg"))
        check("2.3-i18n-no-draft", all(c.get("field") != "BadI18N" for c in dbg()["cmds"]), str(dbg()["cmds"]))
        # I18N + string 可提交
        page.click("#af-type")
        page.wait_for_timeout(300)
        page.click(".dlg-row[data-v='string']")
        page.wait_for_timeout(200)
        page.click("#af-add")
        page.wait_for_timeout(200)
        ok = any(c.get("field") == "BadI18N" and c.get("fieldType") == "string" and c.get("role") == "i18n"
                for c in dbg()["cmds"])
        check("2.3-i18n-string-ok", ok, str(dbg()["cmds"]))
        clear_draft()

        # ---- 2.4 一表至多一个 Code ----
        # ItemType 已有 Code：checkbox 禁用 + 静态提示；手动输入 Code 也被拦
        page.evaluate("document.querySelector('#tree .rrow[data-name=\"ItemType\"]').click()")
        page.wait_for_timeout(200)
        page.click("#add-field")
        page.wait_for_timeout(200)
        check("2.4-code-disabled", page.locator("#af-code").is_disabled(), "")
        check("2.4-code-already-hint", "该表已有代号字段 Code" in page.locator(".dbody").text_content(), "")
        page.fill("#af-name", "Code")
        page.click("#af-add")
        page.wait_for_timeout(200)
        check("2.4-code-manual-blocked", "一表至多一个" in page.text_content("#af-msg"), page.text_content("#af-msg"))
        check("2.4-code-no-draft", all(c.get("field") != "Code" for c in dbg()["cmds"]), str(dbg()["cmds"]))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # Item 上手动输入 Code + int32 → 必须为 string 拦截
        page.evaluate("document.querySelector('#tree .rrow[data-name=\"Item\"]').click()")
        page.wait_for_timeout(200)
        page.click("#add-field")
        page.fill("#af-name", "Code")
        page.click("#af-add")
        page.wait_for_timeout(200)
        check("2.4-code-type-guard", "必须为 string" in page.text_content("#af-msg"), page.text_content("#af-msg"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- 2.5 分隔符内置（无输入控件，命令不带 sep） ----
        page.click("#add-field")
        page.wait_for_timeout(200)
        check("2.5-no-sep-input", page.locator("#af-sep, #af-sep-row").count() == 0, "")

        # ---- 2.7 vector 修饰符 ----
        # 类型选择器无 vector 项
        page.click("#af-type")
        page.wait_for_timeout(200)
        type_rows = page.evaluate("[...document.querySelectorAll('.dlg-row')].map(b=>b.dataset.v)")
        check("2.7-no-vector-item", all(not r.startswith("vector") for r in type_rows), str(type_rows))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # T=标量 + vector → 变长 + 内置分隔符提示，提交 vector<int32>
        page.click("label.chip:has(#af-vec)")
        page.wait_for_timeout(200)
        check("2.7-vec-row-shown", page.locator("#af-vec-row").is_visible(), "")
        check("2.7-var-active", page.locator("#af-flavor-var").is_checked()
              and not page.locator("#af-flavor-fix").is_checked(), "")
        check("2.7-sep-note", page.locator("#af-sep-note").is_visible()
              and "内置" in page.text_content("#af-sep-note"), page.text_content("#af-sep-note"))
        check("2.7-cols-hidden", page.locator("#af-cols-row").is_hidden(), "")
        page.fill("#af-name", "TagList")
        page.click("#af-add")
        page.wait_for_timeout(200)
        cmd = [c for c in dbg()["cmds"] if c.get("field") == "TagList"][-1]
        check("2.7-scalar-vec-cmd", cmd.get("fieldType") == "vector<int32>" and "sep" not in cmd and "cols" not in cmd, str(cmd))
        clear_draft()
        # T=Enum + vector → 变长，提交 vector<ItemRarity>
        page.click("#add-field")
        page.click("#af-type")
        page.wait_for_timeout(200)
        page.click(".dlg-row[data-v='ItemRarity']")
        page.wait_for_timeout(200)
        page.click("label.chip:has(#af-vec)")
        page.wait_for_timeout(200)
        check("2.7-enum-var", page.locator("#af-flavor-var").evaluate("el=>!el.disabled")
              and page.locator("#af-sep-note").is_visible(), "")
        page.fill("#af-name", "RarityList")
        page.click("#af-add")
        page.wait_for_timeout(200)
        cmd = [c for c in dbg()["cmds"] if c.get("field") == "RarityList"][-1]
        check("2.7-enum-vec-cmd", cmd.get("fieldType") == "vector<ItemRarity>", str(cmd))
        clear_draft()
        # T=Record + vector → 仅定长，展开组数输入，提交 vector<ItemDropRange> + cols
        page.click("#add-field")
        page.click("#af-type")
        page.wait_for_timeout(200)
        page.click(".dlg-row[data-v='ItemDropRange']")
        page.wait_for_timeout(200)
        page.click("label.chip:has(#af-vec)")
        page.wait_for_timeout(200)
        check("2.7-record-fix-locked", page.locator("#af-flavor-var").is_disabled()
              and page.locator("#af-flavor-fix").is_checked(), "")
        check("2.7-record-cols", page.locator("#af-cols-row").is_visible()
              and page.locator("#af-sep-note").is_hidden(), "")
        page.fill("#af-name", "Rewards")
        page.click("#af-add")
        page.wait_for_timeout(200)
        cmd = [c for c in dbg()["cmds"] if c.get("field") == "Rewards"][-1]
        check("2.7-record-vec-cmd", cmd.get("fieldType") == "vector<ItemDropRange>" and cmd.get("cols") == "3", str(cmd))
        clear_draft()
        # T=ref → vector 禁用
        page.click("#add-field")
        page.click("#af-type")
        page.wait_for_timeout(200)
        page.click(".dlg-row[data-v='ItemType.Id']")
        page.wait_for_timeout(200)
        check("2.7-ref-vec-disabled", page.locator("#af-vec").is_disabled(), "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- 既有：B4/C5 删除预览 ----
        page.evaluate("document.querySelector('#tree .rrow[data-name=\"ItemType\"]').click()")
        page.wait_for_timeout(200)
        page.click("#del-res")
        page.wait_for_timeout(300)
        page.click("#dl-seeplan")
        page.wait_for_timeout(300)
        check("reg-b4-preview", page.locator(".mask").last.locator(".impacts .impact").count() == 4
              and page.locator(".mask").last.locator("#cp-apply").is_disabled(), "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---- 既有：B5 快速打开切页 / C9 链接跳转 ----
        page.click(".sitem[data-page='export']")
        page.wait_for_timeout(200)
        page.keyboard.press("Meta+p")
        page.wait_for_timeout(200)
        page.fill("#qo-search", "Quest")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        check("reg-b5-quickopen", page.evaluate("document.getElementById('page-schema').classList.contains('active')")
              and page.text_content(".rtitle h1").strip() == "Quest", "")
        page.evaluate("document.querySelector('#tree .rrow[data-name=\"Item\"]').click()")
        page.wait_for_timeout(200)
        page.click("button.tlink:has-text('ItemType.Id')")
        page.wait_for_timeout(400)
        check("reg-c9-link", page.text_content(".rtitle h1").strip() == "ItemType"
              and "未知" not in page.text_content(".rtitle .sub"), "")

        # ---- 既有：B2 过滤/列显隐切表重放 + C8 保存徽标 ----
        page.click(".sitem[data-page='i18n']")
        page.wait_for_timeout(300)
        page.click("#page-i18n .pill[data-status='stale']")
        page.wait_for_timeout(200)
        vis = page.evaluate("[...document.querySelectorAll('#tbody tr')].filter(t=>!t.hidden).map(t=>t.children[0].textContent.trim())")
        check("reg-b2-filter", vis == ["1003"], str(vis))
        page.click("#colvis-btn")
        page.wait_for_timeout(200)
        page.click("input[data-col='trans']")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.click("#pick-table")
        page.wait_for_timeout(300)
        page.click(".dlg-row[data-t='Quest']")
        page.wait_for_timeout(300)
        vis = page.evaluate("[...document.querySelectorAll('#tbody tr')].filter(t=>!t.hidden).map(t=>t.children[0].textContent.trim())")
        check("reg-b2-after-switch", vis == [] and page.evaluate(
            "document.querySelectorAll('#page-i18n thead th')[3].style.display === 'none'"), "")
        page.click("#page-i18n .pill[data-status='all']")
        page.wait_for_timeout(200)
        page.click("#colvis-btn")
        page.wait_for_timeout(200)
        page.click("input[data-col='trans']")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.click("#page-i18n .pill[data-status='missing']")
        page.wait_for_timeout(200)
        page.click("#tbody tr[data-status='missing'] .trans-prev")
        page.wait_for_timeout(200)
        page.fill("#tbody tr[data-status='missing'] textarea", "新译文")
        page.click("#tbody tr[data-status='missing'] .rops .btn-accent")
        page.wait_for_timeout(300)
        check("reg-c8-badge", page.evaluate(
            "[...document.querySelectorAll('#tbody tr')].find(t=>t.children[0].textContent.trim()==='2001')?.children[4].textContent.trim()") == "已译完", "")
        page.click("#page-i18n .pill[data-status='all']")
        page.wait_for_timeout(200)

        # ---- 既有：C10 转义 + B6 src-more resize + C2/C3 ----
        page.click("#tbody tr[data-status='translated'] .trans-prev")
        page.wait_for_timeout(200)
        page.fill("#tbody tr textarea", "</textarea><b>x</b>")
        page.click("#tbody tr .rops .btn-accent")
        page.wait_for_timeout(300)
        check("reg-c10-escape", page.evaluate("document.querySelectorAll('#tbody tr').length") == 2, "")
        page.click("#pick-table")
        page.wait_for_timeout(300)
        page.click(".dlg-row[data-t='Item']")
        page.wait_for_timeout(300)
        page.set_viewport_size({"width": 320, "height": 720})
        page.wait_for_timeout(500)
        small = page.evaluate("document.querySelectorAll('#tbody .src-more').length")
        page.set_viewport_size({"width": 1600, "height": 900})
        page.wait_for_timeout(500)
        large = page.evaluate("document.querySelectorAll('#tbody .src-more').length")
        check("reg-b6-srcmore", small >= 1 and large == 0, f"small={small} large={large}")
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(400)
        open_schema()
        page.click("#add-field")
        page.wait_for_timeout(300)
        ids = page.evaluate("[...document.querySelectorAll('.mask .dhead span[id]')].map(x=>x.id)")
        check("reg-c2-uniq-id", len(ids) == len(set(ids)), str(ids))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.evaluate("document.querySelector('.group[data-open=\"true\"] .group-toggle').click()")
        page.wait_for_timeout(300)
        check("reg-c3-inert", page.evaluate("document.querySelector('.group[data-open=\"false\"] .gbody').inert"), "")

        check("NO-CONSOLE-ERRORS", len(errors) == 0, str(errors[:3]))
        browser.close()

    if httpd:
        httpd.shutdown()
        httpd.server_close()

    fails = [r for r in results if not r[1]]
    print(f"\n===== SUMMARY: {len(results) - len(fails)}/{len(results)} passed =====")
    if fails:
        print("FAILED:", [r[0] for r in fails])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
