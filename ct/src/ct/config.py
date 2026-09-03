from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class DeployTarget(BaseModel):
    """单个部署目标：产物子目录 → Unity 工程内目标目录。

    路径语义：
    - source 相对 project_root（与 GlobalConfig.resolve 一致）
    - dest 相对 unity_project（Unity 工程根目录）
    """

    source: str
    dest: str


class DeployConfig(BaseModel):
    """部署配置：把导出产物同步到 Unity 工程 Assets。

    未配置或未启用时（enabled=False），导表行为与未引入 deploy 前完全一致。
    """

    enabled: bool = False
    unity_project: str = ""
    targets: list[DeployTarget] = []
    build_targets: list[DeployTarget] = []

    def all_targets(self, *, for_build: bool) -> list[DeployTarget]:
        """常规目标 + （--for-build 时）构建目标。"""
        if for_build:
            return [*self.targets, *self.build_targets]
        return self.targets


class GlobalConfig(BaseModel):
    primary_lang: str
    secondary_langs: list[str] = []
    schema_format: str = "yaml"
    schemas_dir: str = "config/schemas"
    types_dir: str = "config/types"
    excel_dir: str = "excel"
    output_dir: str = "output"
    cache_dir: str = "cache"
    i18n_dir: str = "i18n"
    deploy: DeployConfig = DeployConfig()

    # 运行时注入，不从 YAML 读取
    project_root: Path = Path(".")

    @field_validator("primary_lang")
    @classmethod
    def _non_empty_lang(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("primary_lang 不能为空")
        return v.strip()

    def resolve(self, name: str) -> Path:
        return self.project_root / getattr(self, name)

    @property
    def unity_project_root(self) -> Path | None:
        """解析后的 Unity 工程根目录；未配置时返回 None。"""
        if not self.deploy.unity_project:
            return None
        p = Path(self.deploy.unity_project)
        return (p if p.is_absolute() else self.project_root / p).resolve()

    def resolve_deploy_targets(
        self, *, for_build: bool = False
    ) -> list[tuple[Path, Path]]:
        """展开 deploy 目标为 (source, dest) 绝对路径对；未配置/未启用返回空列表。"""
        if not self.deploy.enabled:
            return []
        unity_root = self.unity_project_root
        if unity_root is None:
            return []
        return [
            (self.project_root / t.source, unity_root / t.dest)
            for t in self.deploy.all_targets(for_build=for_build)
        ]

    @property
    def all_langs(self) -> list[str]:
        return [self.primary_lang] + self.secondary_langs


def load_config(project_root: Path | None = None) -> GlobalConfig:
    root = (project_root or Path(".")).resolve()
    config_path = root / "config" / "global.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return GlobalConfig(project_root=root, **data)
