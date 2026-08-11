from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class GlobalConfig(BaseModel):
    primary_lang: str
    secondary_langs: list[str] = []
    schema_format: str = "yaml"
    flatc_path: str = "tools/flatc"
    schemas_dir: str = "config/schemas"
    excel_dir: str = "excel"
    output_dir: str = "output"
    cache_dir: str = "cache"
    i18n_dir: str = "i18n"

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
