"""组合根：把项目根、配置与拓扑排序后的 schema 收拢为一个对象。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ct.config import GlobalConfig, load_config
from ct.schema.loader import sort_schemas
from ct.schema.models import TableSchema
from ct.schema.repository import create_repository


@dataclass(frozen=True)
class Workspace:
    """单个项目目录的只读快照（配置 + schema），供所有用例使用。

    每个命令/请求按需 ``Workspace.load(root)`` 重新加载，避免全局单例的
    陈旧问题；加载成本对本地小文件集可忽略。
    """

    root: Path
    config: GlobalConfig
    schemas: list[TableSchema]  # 已按 ref 依赖拓扑排序
    schema_map: dict[str, TableSchema]

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Workspace":
        config = load_config(project_root)
        repository = create_repository(
            config.resolve("schemas_dir"), config.schema_format
        )
        schemas, _ = sort_schemas(repository.load_all())
        schema_map = {s.table: s for s in schemas}
        return cls(
            root=config.project_root,
            config=config,
            schemas=schemas,
            schema_map=schema_map,
        )

    def resolve(self, name: str) -> Path:
        return self.config.resolve(name)

    @property
    def order(self) -> list[str]:
        """按拓扑顺序的表名列表（与 schemas 一一对应）。"""
        return [s.table for s in self.schemas]
