"""导出后台任务（canonical ）：单任务互斥，进度可查询、可取消。

``CanonicalExportTask`` 服务 canonical 工作区（``run_canonical_export``），
复用 :class:`_BaseTask` 的状态机（start/cancel/progress/step 上报）；legacy
导出任务已随 cutover 移除。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from ct.app.canonical_commands import CanonicalValidationError
from ct.app.canonical_export import CANONICAL_STEPS, run_canonical_export
from ct.app.events import CancelledError, CancelToken, ProgressReporter
from ct.config import load_config
from ct.web.history import append_history, make_entry
from ct.web.logs import log_buffer


@dataclass
class _BaseTask:
    """导出任务公共状态机（子类实现 export_steps + _run）。"""

    status: str = "idle"  # idle | running | done | cancelled | error
    forced: bool = False
    step_index: int = -1
    step_name: str = ""
    steps: list[str] = field(default_factory=list)
    message: str = ""
    errors: list[str] = field(default_factory=list)
    tables_exported: int = 0
    elapsed: float = 0.0
    cancelled: bool = False
    root: Path | None = field(default=None, repr=False)

    _token: CancelToken = field(default_factory=CancelToken, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def export_steps(self) -> list[str]:
        raise NotImplementedError

    @property
    def running(self) -> bool:
        return self.status == "running"

    def start(self, root: Path, forced: bool = False) -> None:
        with self._lock:
            if self.status == "running":
                raise RuntimeError("已有导出任务进行中")
            self.status = "running"
            self.root = root.resolve()
            self.forced = forced
            self.step_index = -1
            self.step_name = ""
            self.steps = list(self.export_steps)
            self.message = "导出进行中…"
            self.errors = []
            self.cancelled = False
            self._token = CancelToken()
            self._thread = threading.Thread(
                target=self._run, args=(root, forced), daemon=True
            )
            self._thread.start()

    def cancel(self) -> None:
        with self._lock:
            if self.status == "running":
                self._token.cancel()
                log_buffer.add("导出", "WARN", "收到取消请求，将在当前步骤结束后停止")

    def progress(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "forced": self.forced,
                "step_index": self.step_index,
                "step_name": self.step_name,
                "steps": list(self.steps),
                "message": self.message,
                "errors": list(self.errors),
                "tables_exported": self.tables_exported,
                "elapsed": round(self.elapsed, 2),
                "cancelled": self.cancelled,
            }

    def global_task(self, root: Path) -> dict | None:
        """Return the persistent shell projection for the active workspace."""
        with self._lock:
            if self.root != root.resolve() or self.status not in {"running", "error"}:
                return None
            message = self.message
            if self.step_name:
                message = f"{self.step_name} · {message}"
            return {
                "id": "canonical-export",
                "kind": "导出",
                "scope": "全部表 × 全量语言",
                "status": self.status,
                "message": message,
                "target": "/logs",
            }

    def _run(self, root: Path, forced: bool) -> None:
        raise NotImplementedError

    def _finish_cancelled(self) -> None:
        with self._lock:
            self.status = "cancelled"
            self.cancelled = True
            self.message = "导出已取消（未提交新缓存）"
        log_buffer.add("导出", "WARN", "导出已取消")

    def _finish_ok(
        self, *, cache_dir: Path, scope: str, tables: int, elapsed: float
    ) -> None:
        """完成态：写历史 + 置 done。"""
        entry = make_entry(
            scope=scope,
            result="成功",
            tables=tables,
            elapsed=elapsed,
            forced=self.forced,
        )
        append_history(cache_dir, entry)
        with self._lock:
            self.status = "done"
            self.message = f"导出完成：{tables} 张表 · {round(elapsed, 2)}s"
            self.tables_exported = tables
            self.elapsed = elapsed
        log_buffer.add(
            "导出", "INFO", f"导出完成：{tables} 张表（{round(elapsed, 2)}s）"
        )

    def _fail(self, message: str, errors: list[str] | None = None) -> None:
        with self._lock:
            self.status = "error"
            self.message = message
            if errors:
                self.errors = list(errors)

    def _set_step(self, step: str) -> None:
        with self._lock:
            self.step_index = self.steps.index(step) if step in self.steps else -1
            self.step_name = step
        log_buffer.add("导出", "INFO", f"步骤：{step}")

    def _finish_step(self) -> None:
        pass


@dataclass
class CanonicalExportTask(_BaseTask):
    """Canonical 导出任务（run_canonical_export，阶段化上报）。"""

    @property
    def export_steps(self) -> list[str]:
        return list(CANONICAL_STEPS)

    def _run(self, root: Path, forced: bool) -> None:
        try:
            try:
                result = run_canonical_export(
                    root,
                    forced=forced,
                    reporter=PanelProgressReporter(self),
                    cancel_token=self._token,
                )
            except CancelledError:
                self._finish_cancelled()
                return
            self._finish_ok(
                cache_dir=load_config(root).resolve("cache_dir"),
                scope="全部表 × 全量语言",
                tables=result["tables"],
                elapsed=result["elapsed"],
            )
        except FileNotFoundError as e:
            log_buffer.add("系统", "ERROR", f"导出异常: {e}")
            self._fail(f"文件不存在: {e}")
        except CanonicalValidationError as e:
            for issue in e.issues:
                log_buffer.add("校验", "ERROR", issue.render())
            self._fail("校验未通过，导出中止", [issue.render() for issue in e.issues])
        except Exception as e:  # noqa: BLE001
            log_buffer.add("系统", "ERROR", f"导出异常: {e}")
            self._fail(f"导出异常: {e}")


class PanelProgressReporter:
    """把管道事件转发到任务状态与日志缓冲。"""

    def __init__(self, task: _BaseTask) -> None:
        self._task = task

    def step_started(self, step: str) -> None:
        self._task._set_step(step)

    def step_finished(self, step: str) -> None:
        self._task._finish_step()

    def log(self, line: str, *, err: bool = False) -> None:
        log_buffer.add("导出", "ERROR" if err else "INFO", line)


# 模块级单例（Web 触发入口，与线程安全状态机绑定）
canonical_export_task = CanonicalExportTask()
