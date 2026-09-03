"""组合根（canonical v4）：配置 + 一个 canonical 资源图。

CLI / Web / Excel / 校验 / 生成器在 v4 路径统一消费本对象暴露的
``ResourceWorkspace`` 与确定性顺序；旧 ``Workspace`` 仅保留给 cutover
之前的只读 legacy 入口，两者不混用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    def load(cls, project_root: Path | None = None) -> "CanonicalWorkspace":
        config = load_config(project_root)
        repository = YamlResourceRepository(
            config.resolve("schemas_dir"),
            config.resolve("types_dir"),
        )
        resources = repository.load()
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
    def records(self) -> tuple:
        return self.resources.records

    @property
    def enums(self) -> tuple:
        return self.resources.enums
