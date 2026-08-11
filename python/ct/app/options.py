"""用例参数对象：把一组结伴出现的参数收拢为值对象。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExportOptions:
    """导出用例的输入参数（对应 CLI 的 export 选项）。"""

    all_tables: bool = False
    table: str | None = None
    lang: str | None = None
    verbose: bool = False
