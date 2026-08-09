"""导出管道的事件与取消原语。"""

from __future__ import annotations

from typing import Protocol


class CancelledError(Exception):
    """导出被取消时由 CancelToken 抛出，由管道捕获转为结果。"""


class CancelToken:
    """协作式取消标记：只在步与步/表与表之间检查。"""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledError()


class ProgressReporter(Protocol):
    """进度事件的接收方：CLI 打印文本，Web 侧记录到 job 日志。"""

    def step_started(self, step: str) -> None: ...

    def step_finished(self, step: str) -> None: ...

    def log(self, line: str, *, err: bool = False) -> None: ...
