"""导出后台任务：单任务互斥，进度可查询、可取消。"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from ct.app.events import CancelToken, ProgressReporter
from ct.app.export import ExportPipeline, ExportValidationError
from ct.app.options import ExportOptions
from ct.app.workspace import Workspace
from ct.cache.state import load_cache
from ct.web.history import append_history, make_entry
from ct.web.logs import log_buffer


@dataclass
class ExportTaskState:
    """当前导出任务的内存状态（一次只允许一个任务）。"""

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

    _token: CancelToken = field(default_factory=CancelToken, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def running(self) -> bool:
        return self.status == "running"

    def start(self, root: Path, forced: bool) -> None:
        with self._lock:
            if self.status == "running":
                raise RuntimeError("已有导出任务进行中")
            self.status = "running"
            self.forced = forced
            self.step_index = -1
            self.step_name = ""
            self.steps = [
                "解析校验",
                "i18n sync",
                "JSON",
                "FBS",
                "Accessor",
                "Bundle",
                "Deploy",
            ]
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

    # ---- 内部：后台线程执行 ----
    def _run(self, root: Path, forced: bool) -> None:
        try:
            ws = Workspace.load(root)
            if not ws.schemas:
                self._fail("未找到任何 schema")
                return

            cache = load_cache(ws.resolve("cache_dir"))
            reporter = PanelProgressReporter(self)
            opts = ExportOptions(all_tables=True, verbose=False)
            try:
                result = ExportPipeline().run(
                    ws, opts, cache, ws.order, reporter, self._token
                )
            except ExportValidationError as e:
                lines = [issue.render() for issue in e.issues]
                for line in lines:
                    log_buffer.add("校验", "ERROR", line)
                self._fail("校验未通过，导出中止", lines)
                return

            if result.cancelled:
                with self._lock:
                    self.status = "cancelled"
                    self.cancelled = True
                    self.message = "导出已取消（未提交新缓存）"
                    self.elapsed = result.elapsed
                log_buffer.add("导出", "WARN", "导出已取消")
                return

            entry = make_entry(
                scope="全部表 × 全量语言",
                result="成功",
                tables=result.tables_exported,
                elapsed=result.elapsed,
                forced=forced,
            )
            append_history(ws.resolve("cache_dir"), entry)
            with self._lock:
                self.status = "done"
                self.message = (
                    f"导出完成：{result.tables_exported} 张表 · "
                    f"{round(result.elapsed, 2)}s"
                )
                self.tables_exported = result.tables_exported
                self.elapsed = result.elapsed
            log_buffer.add(
                "导出",
                "INFO",
                f"导出完成：{result.tables_exported} 张表（{round(result.elapsed, 2)}s）",
            )
        except Exception as e:  # noqa: BLE001
            log_buffer.add("系统", "ERROR", f"导出异常: {e}")
            self._fail(f"导出异常: {e}")

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


class PanelProgressReporter:
    """把管道事件转发到任务状态与日志缓冲。"""

    def __init__(self, task: ExportTaskState) -> None:
        self._task = task

    def step_started(self, step: str) -> None:
        self._task._set_step(step)

    def step_finished(self, step: str) -> None:
        self._task._finish_step()

    def log(self, line: str, *, err: bool = False) -> None:
        log_buffer.add("导出", "ERROR" if err else "INFO", line)


export_task = ExportTaskState()
