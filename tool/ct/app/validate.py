"""共享解析校验阶段（拆分阶段 6.11）。

把「读取 Excel → 类型校验 → 引用校验 → 收集 id 集合」从 export / validate
两个用例中提炼为单一阶段，返回结构化中间数据，两个用例各自只负责
展示层的输出差异（如 [parse] 日志、缺文件提示文案）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ct.app.workspace import Workspace
from ct.cache.state import CacheState
from ct.excel.reader import read_excel
from ct.validate.errors import Issue
from ct.validate.refs import validate_refs
from ct.validate.types import validate_table


@dataclass
class ParseValidateResult:
    """解析校验阶段的不可变中间数据。"""

    parsed_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    id_sets: dict[str, set[Any]] = field(default_factory=dict)
    errors: list[Issue] = field(default_factory=list)


def parse_and_validate(
    ws: Workspace,
    tables: list[str],
    cache: CacheState,
    excel_dir: Path,
    *,
    on_parse: Callable[[str], None] | None = None,
    on_missing: Callable[[str, Path], None] | None = None,
) -> ParseValidateResult:
    """按拓扑顺序解析并校验 *tables*。

    - 非目标表从缓存复用 id 集合（与现有 export / validate 语义一致）；
    - 缺失文件不中断，通过 ``on_missing`` 提示（文案由调用方决定）；
    - ``errors`` 保持现有字符串格式（阶段 E 再对象化）。
    """
    result = ParseValidateResult()

    # 解析目标表 + 从缓存收集未变化表的 id 集合
    for name in ws.order:
        if name not in tables:
            cached_ids = cache.tables.get(name)
            if cached_ids:
                result.id_sets[name] = set(cached_ids.ids)
            continue

        schema = ws.schema_map[name]
        xlsx_path = excel_dir / schema.resolved_excel_file
        if not xlsx_path.exists():
            if on_missing is not None:
                on_missing(name, xlsx_path)
            continue

        if on_parse is not None:
            on_parse(name)

        rows = read_excel(xlsx_path, schema)
        result.parsed_data[name] = rows
        pk = schema.primary
        result.id_sets[name] = {row[pk] for row in rows if pk in row}
        result.errors.extend(validate_table(rows, schema))

    # 引用校验（按拓扑顺序，只针对本次解析的表）
    for name in ws.order:
        if name not in result.parsed_data:
            continue
        schema = ws.schema_map[name]
        if schema.all_refs():
            result.errors.extend(
                validate_refs(result.parsed_data[name], schema, result.id_sets)
            )

    return result
