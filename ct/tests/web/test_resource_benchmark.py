"""Resource-list render benchmarks (11.5): DOM node budget + render latency."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml
from werkzeug.serving import make_server

from ct.web.app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")

def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture(scope="module")
def bench_url(tmp_path_factory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("bench") / "gd"
    (root / "config").mkdir(parents=True, exist_ok=True)
    _write_yaml(root / "config" / "global.yaml", {"primary_lang": "zh"})
    (root / "config" / "types").mkdir(parents=True, exist_ok=True)
    _write_yaml(
        root / "config" / "schemas" / "Table.yaml",
        {"table": "Table", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
    )
    server = make_server("127.0.0.1", 0, create_app(root), threaded=True)
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


@pytest.mark.parametrize("count", [100, 1_000, 10_000])
def test_resources_render_within_budget(bench_url: str, chromium_browser: Any, count: int) -> None:
    context = chromium_browser.new_context(viewport={"width": 1600, "height": 900})
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    digits = max(4, len(str(count - 1)))
    resources = [
        {
            "kind": "table",
            "name": f"Table{i:0{digits}d}",
            "resourceId": f"table:Table{i:0{digits}d}",
            "primary": "Id",
            "fields": [{"name": "Id", "type": "int32"}],
        }
        for i in range(count)
    ]
    page.route(
        "**/api/schema-workspace",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "data": {"revision": "benchmark", "resources": resources, "reverseRefs": {}},
            }),
        ),
    )
    page.goto(bench_url, wait_until="load")
    started = page.evaluate("() => performance.now()")
    page.get_by_role("tab", name="Schema").click()
    page.wait_for_timeout(100)
    assert page_errors == []
    page.wait_for_selector("#page-schema .ct-vlist-window", timeout=5_000)
    page.wait_for_function(
        "() => document.querySelectorAll('#page-schema .ct-resource-row').length > 0",
        timeout=20000,
    )
    first_paint_ms = page.evaluate("() => performance.now()") - started

    # virtual list: only the visible window is in the DOM (constant), regardless of N
    visible_rows = page.locator("#page-schema .ct-resource-row").count()
    dom_nodes = page.evaluate("() => document.querySelectorAll('*').length")

    assert 0 < visible_rows < 100, f"虚拟列表窗口应远小于资源总数，实际 {visible_rows}"
    assert dom_nodes < 8_000, f"DOM 节点过多: {dom_nodes}"
    assert first_paint_ms < 5_000, f"首屏渲染过慢: {first_paint_ms:.0f}ms"

    # query latency includes fuzzy scoring and a virtual-window repaint
    target = f"Table{count - 1:0{digits}d}"
    query_started = page.evaluate("() => performance.now()")
    page.fill("#page-schema #resource-filter", target)
    page.wait_for_selector(f'#page-schema [data-name="{target}"]')
    query_ms = page.evaluate("() => performance.now()") - query_started
    assert query_ms < 2_000, f"搜索响应过慢: {query_ms:.0f}ms"
    page.fill("#page-schema #resource-filter", "")
    # scrolling reveals more rows (window slides, total height preserved)
    list_el = page.locator("#page-schema #resource-list")
    before = page.evaluate(
        "() => document.querySelector('#page-schema .ct-vlist-window').children.length"
    )
    list_el.evaluate("(el) => { el.scrollTop = el.scrollHeight; el.dispatchEvent(new Event('scroll')); }")
    page.wait_for_timeout(120)
    after = page.evaluate(
        "() => document.querySelector('#page-schema .ct-vlist-window').children.length"
    )
    assert after > 0  # window remains populated after deep scroll
    assert page.locator("#page-schema .ct-resource-row", has_text=target).count() == 1

    # Quick Open uses the same fixed-row window and searches the full resource set.
    page.keyboard.press("Control+p")
    page.fill("#page-schema #quick-open-input", target)
    page.wait_for_selector(f'#page-schema [data-qo="{target}"]')
    assert page.locator("#page-schema #quick-open-list .ct-resource-row").count() < 100

    heap = page.evaluate("() => performance.memory ? performance.memory.usedJSHeapSize : null")
    print(
        f"resources={count} first_paint_ms={first_paint_ms:.1f} query_ms={query_ms:.1f} "
        f"dom_nodes={dom_nodes} visible_rows={visible_rows} heap_bytes={heap}"
    )
    context.close()
