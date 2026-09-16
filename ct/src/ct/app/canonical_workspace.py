"""组合根（canonical ）：配置 + 一个 canonical 资源图。

CLI / Web / Excel / 校验 / 生成器统一消费本对象暴露的
``ResourceWorkspace`` 与确定性顺序；legacy 组合根经 cutover 移除。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ct.config import GlobalConfig, load_config
from ct.schema.resource_graph import (
    Reference,
    named_dependency_edges,
    resource_topological_order,
    reverse_references,
)
from ct.schema.resource_repository import ResourceWorkspace, YamlResourceRepository


@dataclass(frozen=True)
class CanonicalWorkspace:
    """单个项目目录的只读 canonical 快照（配置 + 资源图）。"""

    root: Path
    config: GlobalConfig
    resources: ResourceWorkspace
    table_order: tuple[str, ...]
    reverse_refs: dict[str, tuple[Reference, ...]]

    @classmethod
    def load(
        cls,
        project_root: Path | None = None,
        *,
        contents: "Mapping[Path, bytes] | None" = None,
        config: GlobalConfig | None = None,
    ) -> "CanonicalWorkspace":
        """加载工作区。

        ``contents`` 给定时，schema/types 都**从捕获到的字节**解析（不 glob、
        不读盘）；``config`` 允许复用已从捕获内容解析好的配置对象。
        """
        if config is None:
            config = load_config(project_root)
        repository = YamlResourceRepository(
            config.resolve("schemas_dir"),
            config.resolve("types_dir"),
            contents=contents,
        )
        resources = repository.load()
        # 索引随 Table 资源加载；这里做一次 schema 级校验（字段存在、类型允许、非 i18n）
        from ct.schema.indexes import validate_indexes

        for table in resources.tables:
            validate_indexes(table, table.indexes)
        named_graph = named_dependency_edges(resources.resources)
        order = resource_topological_order(resources.resources, named_graph=named_graph)
        reverse = reverse_references(resources.resources)
        return cls(
            root=config.project_root,
            config=config,
            resources=resources,
            table_order=tuple(node for node in order if node.startswith("table:")),
            reverse_refs=reverse,
        )

    def resolve(self, name: str) -> Path:
        return self.config.resolve(name)

    @property
    def tables(self) -> tuple:
        return self.resources.tables

    @property
    def indexes(self) -> dict[str, tuple]:
        """表 id → 查询索引声明（当前仅 CodeName）。"""
        return {table.resource_id: table.indexes for table in self.resources.tables}

    @property
    def records(self) -> tuple:
        return self.resources.records

    @property
    def enums(self) -> tuple:
        return self.resources.enums
