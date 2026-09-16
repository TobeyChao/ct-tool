"""面板日志缓冲：按模块采集内存日志，供日志页筛选展示。

模块名的唯一来源在这里。写入方二选一：

- 任务/壳层代码显式声明：``log_buffer.add(MODULE_EXPORT, LEVEL_INFO, ...)``；
- 库层代码按 logger 命名归类：``ct.web.i18n`` → ``i18n``（见 ``LOGGER_MODULE_HINTS``）。

日志页的分类按钮（``static/js/modules/logs.js`` 的 ``MODULES``）必须与
``PANEL_MODULES`` 一致，由 ``ct/tests/web/test_logs.py`` 守门。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

#: 面板日志模块（与前端分类按钮一一对应，不含 frontend 的「全部模块」）。
MODULE_EXPORT = "导出"
MODULE_VALIDATE = "校验"
MODULE_I18N = "i18n"
MODULE_TEMPLATE = "模板"
MODULE_SYSTEM = "系统"
PANEL_MODULES = (
    MODULE_EXPORT,
    MODULE_VALIDATE,
    MODULE_I18N,
    MODULE_TEMPLATE,
    MODULE_SYSTEM,
)

#: 面板级别（前端筛选按钮是 INFO/WARN/ERROR，不含 DEBUG）。
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"

#: stdlib ``LogRecord.levelname`` → 面板级别。stdlib 报 ``WARNING``，面板筛选
#: 按钮写的是 ``WARN``；不归一化就会出现「筛 WARN 筛不到」的记录。
_LEVEL_ALIASES = {
    "WARNING": LEVEL_WARN,
    "CRITICAL": LEVEL_ERROR,
    "FATAL": LEVEL_ERROR,
}

#: logger 名片段 → 模块。按命名归类，避免每个调用点重复传模块名。
LOGGER_MODULE_HINTS = (
    ("i18n", MODULE_I18N),
    ("template", MODULE_TEMPLATE),
    ("export", MODULE_EXPORT),
    ("validate", MODULE_VALIDATE),
)


def module_for_logger(name: str) -> str:
    """logger 名 → 面板模块；未命中片段表的落到「系统」。"""
    lowered = (name or "").lower()
    for fragment, module in LOGGER_MODULE_HINTS:
        if fragment in lowered:
            return module
    return MODULE_SYSTEM


def normalize_level(levelname: str) -> str:
    """``logging`` 级别名 → 面板级别名。"""
    name = (levelname or "").upper()
    return _LEVEL_ALIASES.get(name, name or LEVEL_INFO)


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
                    level=normalize_level(level),
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

    def restore(self, entries: list[dict]) -> None:
        """用 ``snapshot()`` 返回的条目覆盖当前缓冲（失败注入后复原用）。"""
        with self._lock:
            self._records.clear()
            for entry in entries:
                self._records.append(
                    LogRecord(
                        time=entry["time"],
                        module=entry["module"],
                        level=entry["level"],
                        message=entry["message"],
                    )
                )


class PanelLogHandler(logging.Handler):
    """把标准 logging 记录转发到面板缓冲（按 logger 名推断模块）。

    DEBUG 及以下不进面板：面板是给策划看的运行日志，DEBUG 属于 CLI
    ``--verbose`` 的开发排查逃生门（见 ``ct.cli._friendly_exit``）。
    """

    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.INFO:
                return
            self.buffer.add(
                module_for_logger(record.name),
                normalize_level(record.levelname),
                record.getMessage(),
            )
        except Exception:
            self.handleError(record)


def attach_panel_handler(
    logger: logging.Logger, buffer: LogBuffer | None = None
) -> PanelLogHandler:
    """把面板 handler 挂到 ``logger`` 上，重复调用不重复转发。

    ``create_app`` 会被反复调用（测试、多工作区），无条件 ``addHandler`` 会让
    每条记录被转发 N 次；这里按「已挂同缓冲的 handler」判定幂等。

    面板要看到 INFO 级步骤日志，而 ``ct`` logger 默认继承 root 的 WARNING，
    因此只在下限高于 INFO 时把它降到 INFO（已显式设成 DEBUG 的不动）。
    """
    target = buffer if buffer is not None else log_buffer
    if logger.getEffectiveLevel() > logging.INFO:
        logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if isinstance(handler, PanelLogHandler) and handler.buffer is target:
            return handler
    handler = PanelLogHandler(target)
    logger.addHandler(handler)
    return handler


log_buffer = LogBuffer()
