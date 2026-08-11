"""`ct status` 用例：数据变更与模板漂移分类（搬移函数 8.1）。

把 cli.status() 的分类逻辑下沉到应用层，返回结构化报告；CLI 只负责
按现状文本渲染。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ct.app.workspace import Workspace
from ct.cache.state import CacheState
from ct.excel.diff import get_changed_tables
from ct.excel.template import read_template_metadata
from ct.schema.hashing import compute_schema_hash


@dataclass(frozen=True)
class StatusReport:
    """各表状态分类。组内顺序 = ws.order（拓扑顺序）。"""

    changed: list[str] = field(default_factory=list)    # 数据变更（待导出）
    drifted: list[str] = field(default_factory=list)    # 模板已过时
    untracked: list[str] = field(default_factory=list)  # legacy 文件无元数据
    missing: list[str] = field(default_factory=list)    # Excel 文件缺失

    @property
    def has_anything(self) -> bool:
        return bool(self.changed or self.drifted or self.untracked or self.missing)


def compute_status(ws: Workspace, cache: CacheState) -> StatusReport:
    """按拓扑顺序分类各表的模板/数据状态。

    分组语义与现 CLI 完全一致：缺失文件 → 无元数据（legacy）→
    schema hash 与模板元数据不一致（漂移）；changed 由 Excel hash 与
    缓存比对得出。
    """
    excel_dir = ws.resolve("excel_dir")
    changed_set = set(get_changed_tables(ws.schemas, cache, excel_dir))

    drifted: list[str] = []
    untracked: list[str] = []
    missing: list[str] = []
    for s in ws.schemas:
        xlsx_path = excel_dir / s.resolved_excel_file
        if not xlsx_path.exists():
            missing.append(s.table)
            continue
        current_hash = compute_schema_hash(s)
        # 真源：Excel 模板元数据里的 ct_schema_hash（生成模板时写入）
        meta = read_template_metadata(xlsx_path)
        if meta is None:
            untracked.append(s.table)
            continue
        if meta.schema_hash != current_hash:
            drifted.append(s.table)

    return StatusReport(
        changed=[s.table for s in ws.schemas if s.table in changed_set],
        drifted=drifted,
        untracked=untracked,
        missing=missing,
    )
