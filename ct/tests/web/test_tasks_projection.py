"""任务栏投影（右下角）：running 持续投影，error 只停留 ERROR_HOLD_SECONDS。

回归背景：导出失败后 error 状态永不过期，右下角错误卡片无法消失
（既无自动隐藏也无关闭按钮）。现在关闭状态由服务端记账
（``dismiss_global`` / ``POST /api/tasks/<id>/dismiss``）：
刷新页面不复活，新一次 ``start()`` 重置标记，下一次失败照常提示。
``started_at`` 仅用于标识运行次序，前端不再自行记录关闭状态。
"""

from __future__ import annotations

import time
from pathlib import Path

from ct.web.app import create_app
from ct.web.tasks import ERROR_HOLD_SECONDS, CanonicalExportTask, canonical_export_task

from web_helpers import build_project


def _client(tmp_path: Path):
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32", "comment": "a"}],
            }
        ],
    )
    return create_app(root).test_client(), root


def _error_task(root: Path, *, settled_age: float) -> CanonicalExportTask:
    """构造一个 root 上刚失败（或早已失败）的任务，不真正起线程。"""
    task = CanonicalExportTask()
    task.root = root.resolve()
    task.status = "error"
    task.message = "校验未通过，导出中止"
    task._settled_at = time.monotonic() - settled_age
    return task


def test_running_task_stays_projected(tmp_path: Path) -> None:
    task = CanonicalExportTask()
    task.root = tmp_path.resolve()
    task.status = "running"
    task.message = "导出进行中…"

    projected = task.global_task(tmp_path)

    assert projected is not None
    assert projected["status"] == "running"


def test_fresh_error_is_projected_with_started_at(tmp_path: Path) -> None:
    task = _error_task(tmp_path, settled_age=0.0)

    projected = task.global_task(tmp_path)

    assert projected is not None
    assert projected["status"] == "error"
    assert "started_at" in projected


def test_expired_error_leaves_taskbar(tmp_path: Path) -> None:
    task = _error_task(tmp_path, settled_age=ERROR_HOLD_SECONDS + 1.0)

    assert task.global_task(tmp_path) is None


def test_fail_marks_settle_time_for_new_run(tmp_path: Path) -> None:
    task = _error_task(tmp_path, settled_age=ERROR_HOLD_SECONDS + 1.0)
    assert task.global_task(tmp_path) is None

    # 新一次导出：重置计时后再次失败，错误重新可见
    task.status = "running"
    task._settled_at = None
    task._fail("导出异常: boom")

    assert task.global_task(tmp_path) is not None


def _wait_for_status(task: CanonicalExportTask, status: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if task.status == status:
            return
        time.sleep(0.02)
    raise AssertionError(f"任务未在 {timeout}s 内进入 {status}（当前 {task.status}）")


def test_dismissed_error_leaves_taskbar_until_next_run(tmp_path: Path) -> None:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32", "comment": "a"}],
            }
        ],
    )
    (root / "config" / "global.yaml").unlink()  # 让导出真实失败
    task = CanonicalExportTask()

    task.start(root)
    _wait_for_status(task, "error")
    assert task.global_task(root) is not None

    assert task.dismiss_global() is True
    assert task.global_task(root) is None

    # 新一次 start()：服务端重置关闭标记，下一次失败照常提示
    task.start(root)
    _wait_for_status(task, "error")
    assert task.global_task(root) is not None


def test_dismiss_is_rejected_while_running(tmp_path: Path) -> None:
    task = CanonicalExportTask()
    task.root = tmp_path.resolve()
    task.status = "running"
    task.message = "导出进行中…"

    assert task.dismiss_global() is False
    assert task.global_task(tmp_path) is not None


def test_tasks_dismiss_endpoint_hides_error(tmp_path: Path, monkeypatch) -> None:
    client, root = _client(tmp_path)
    monkeypatch.setattr(canonical_export_task, "root", root.resolve())
    monkeypatch.setattr(canonical_export_task, "status", "error")
    monkeypatch.setattr(canonical_export_task, "message", "校验未通过，导出中止")
    monkeypatch.setattr(canonical_export_task, "_settled_at", time.monotonic())
    monkeypatch.setattr(canonical_export_task, "_dismissed", False)

    resp = client.post("/api/tasks/canonical-export/dismiss")

    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"dismissed": True}
    tasks = client.get("/api/tasks").get_json()["data"]
    assert all(t["id"] != "canonical-export" for t in tasks)


def test_tasks_dismiss_endpoint_rejects_unknown_id(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    resp = client.post("/api/tasks/nope/dismiss")

    assert resp.status_code == 404
    assert "未知任务" in resp.get_json()["error"]


def test_tasks_endpoint_drops_expired_error(tmp_path: Path, monkeypatch) -> None:
    client, root = _client(tmp_path)
    monkeypatch.setattr(canonical_export_task, "root", root.resolve())
    monkeypatch.setattr(canonical_export_task, "status", "error")
    monkeypatch.setattr(canonical_export_task, "message", "校验未通过，导出中止")
    monkeypatch.setattr(
        canonical_export_task, "_settled_at", time.monotonic() - (ERROR_HOLD_SECONDS + 5.0)
    )

    resp = client.get("/api/tasks")

    assert resp.status_code == 200
    assert all(t["id"] != "canonical-export" for t in resp.get_json()["data"])


def test_tasks_endpoint_keeps_fresh_error(tmp_path: Path, monkeypatch) -> None:
    client, root = _client(tmp_path)
    monkeypatch.setattr(canonical_export_task, "root", root.resolve())
    monkeypatch.setattr(canonical_export_task, "status", "error")
    monkeypatch.setattr(canonical_export_task, "message", "校验未通过，导出中止")
    monkeypatch.setattr(canonical_export_task, "_settled_at", time.monotonic())
    monkeypatch.setattr(canonical_export_task, "_started_at", 123.456)

    resp = client.get("/api/tasks")

    assert resp.status_code == 200
    projected = next(t for t in resp.get_json()["data"] if t["id"] == "canonical-export")
    assert projected["status"] == "error"
    assert projected["started_at"] == 123.456
