"""Shared canonical workspace builders for web tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def build_project(
    root: Path,
    *,
    schemas: list[dict[str, Any]] | None = None,
    types: list[dict[str, Any]] | None = None,
) -> Path:
    """Build a minimal  workspace (config + optional schemas/types)."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "schemas").mkdir(parents=True, exist_ok=True)
    (root / "config" / "types").mkdir(parents=True, exist_ok=True)
    write_yaml(
        root / "config" / "global.yaml",
        {
            "primary_lang": "zh",
            "secondary_langs": ["en"],
        },
    )
    for schema in schemas or []:
        write_yaml(root / "config" / "schemas" / f"{schema['table']}.yaml", schema)
    for type_def in types or []:
        write_yaml(root / "config" / "types" / f"{type_def['name']}.yaml", type_def)
    return root


CUTOVER_SCHEMAS = {
    "Item": {
        "table": "Item",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32", "comment": "道具唯一ID，禁止修改"},
            {"name": "Name", "type": "string", "i18n": True, "comment": "道具名称（多语言）"},
            {"name": "Price", "type": "float", "comment": "售价（金币），0=不可出售"},
            {"name": "Rarity", "type": "ItemRarity", "comment": "稀有度"},
            {"name": "ItemTypeId", "type": "int32", "ref": "ItemType.Id", "comment": "道具类型，关联 ItemType.Id"},
            {"name": "DropRange", "type": "ItemDropRange", "comment": "掉落范围"},
            {"name": "Tags", "type": "vector<int32>", "separator": ",", "comment": "标签列表，逗号分隔"},
            {"name": "IsActive", "type": "bool", "server_only": True, "comment": "是否启用（仅服务端）"},
        ],
    },
    "ItemType": {
        "table": "ItemType",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32", "comment": "类型唯一ID，禁止修改"},
            {"name": "Name", "type": "string", "i18n": True, "comment": "类型名称（多语言）"},
            {"name": "Code", "type": "string", "comment": "类型代码，程序引用用"},
        ],
    },
    "Quest": {
        "table": "Quest",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32", "comment": "任务唯一ID，禁止修改"},
            {"name": "Title", "type": "string", "i18n": True, "comment": "任务标题（多语言）"},
            {"name": "Description", "type": "string", "i18n": True, "comment": "任务描述（多语言）"},
            {"name": "RewardItemId", "type": "int32", "ref": "Item.Id", "comment": "奖励道具ID，关联 Item.Id"},
            {"name": "RequiredLevel", "type": "int32", "comment": "接取等级要求"},
        ],
    },
    "UIConfig": {
        "table": "UIConfig",
        "primary": "Id",
        "fields": [
            {"name": "Id", "type": "int32", "comment": "界面唯一 ID（行主键）"},
            {"name": "Layer", "type": "UIConfigLayer", "comment": "UI 层级"},
            {"name": "ResourceKey", "type": "string", "comment": "Addressables 资源 key"},
            {"name": "BlocksRaycast", "type": "bool", "comment": "Overlay 专用：是否拦截输入"},
            {"name": "Stack", "type": "bool", "comment": "Page 专用：是否入历史栈"},
        ],
    },
}

CUTOVER_TYPES = [
    {"kind": "enum", "name": "ItemRarity", "values": ["common", "rare", "epic"], "comment": "稀有度"},
    {"kind": "record", "name": "ItemDropRange", "comment": "掉落范围", "fields": [
        {"name": "Min", "type": "int32", "comment": "掉落数量下限"},
        {"name": "Max", "type": "int32", "comment": "掉落数量上限"},
    ]},
    {"kind": "enum", "name": "UIConfigLayer", "values": ["Page", "Modal", "Panel", "Overlay"], "comment": "UI 层级"},
]


def convert_cutover_workspace(root: Path) -> None:
    """Convert the legacy repository_cutover fixture schemas to canonical
    (identity Excel: same column order). The tool is canonical-only."""
    schema_dir = root / "config" / "schemas"
    for path in schema_dir.glob("*.yaml"):
        path.unlink()
    for name, schema in CUTOVER_SCHEMAS.items():
        write_yaml(schema_dir / f"{name}.yaml", schema)
    for type_def in CUTOVER_TYPES:
        write_yaml(root / "config" / "types" / f"{type_def['name']}.yaml", type_def)
