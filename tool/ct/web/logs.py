"""面板日志缓冲：按模块采集内存日志，供日志页筛选展示。"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class LogRecord:
    time: str
    module: str
    level: str
    message: str


class LogBuffer:
    """线程安全的内存环形日志缓冲。"""

    def __init__(self, maxlen: int = 2000) -> None:
        self._records: deque[LogRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, module: str, level: str, message: str) -> None:
        with self._lock:
            self._records.append(
                LogRecord(
                    time=time.strftime("%H:%M:%S"),
                    module=module,
                    level=level,
                    message=message,
                )
            )

    def snapshot(self, module: str | None = None) -> list[dict]:
        with self._lock:
            records = list(self._records)
        if module and module != "all":
            records = [r for r in records if r.module == module]
        return [
            {"time": r.time, "module": r.module, "level": r.level, "message": r.message}
            for r in records
        ]


class PanelLogHandler(logging.Handler):
    """把标准 logging 记录转发到面板缓冲（按 logger 名推断模块）。"""

    _MODULE_HINTS = (
        ("i18n", "i18n"),
        ("template", "模板"),
        ("export", "导出"),
        ("validate", "校验"),
    )

    def __init__(self, buffer: LogBuffer, logger_names: Iterable[str] = ()) -> None:
        super().__init__()
        self._buffer = buffer
        self._logger_names = set(logger_names)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name or ""
            module = "系统"
            for fragment, label in self._MODULE_HINTS:
                if fragment in name:
                    module = label
                    break
            level = record.levelname
            self._buffer.add(module, level, record.getMessage())
        except Exception:
            self.handleError(record)


log_buffer = LogBuffer()
