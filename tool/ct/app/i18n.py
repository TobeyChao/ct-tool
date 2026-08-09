"""i18n 用例编排（搬移函数 8.1）。

把 cli 中为 sync 准备行数据的编排下沉到应用层；CLI 只渲染提示。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ct.config import GlobalConfig
from ct.excel.reader import read_excel
from ct.schema.models import TableSchema
from ct.validate.errors import ValidationIssue


@dataclass(frozen=True)
class ReadRowsResult:
    rows_by_table: dict[str, list[dict]] = field(default_factory=dict)
    issues_by_table: dict[str, list[ValidationIssue]] = field(default_factory=dict)
    missing: list[tuple[str, Path]] = field(default_factory=list)


def read_i18n_rows(
    cfg: GlobalConfig,
    schemas: list[TableSchema],
    *,
    table: str | None = None,
) -> ReadRowsResult:
    """读取 i18n 表的 Excel 行数据；缺失文件记入 missing 不中断。

    只读取 `table` 指定（或全部）的 i18n 表，保证缺失文件的提示范围
    与现 CLI 一致。
    """
    excel_dir = cfg.resolve("excel_dir")
    result = ReadRowsResult()
    for schema in schemas:
        if not schema.has_i18n:
            continue
        if table and schema.table != table:
            continue
        xlsx_path = excel_dir / schema.resolved_excel_file
        if not xlsx_path.exists():
            result.missing.append((schema.table, xlsx_path))
            continue
        parsed = read_excel(xlsx_path, schema)
        result.rows_by_table[schema.table] = parsed.rows
        result.issues_by_table[schema.table] = parsed.issues
    return result
