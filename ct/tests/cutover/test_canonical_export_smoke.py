"""Canonical cutover pipeline smoke: convert legacy fixture -> canonical,
run canonical export, and assert the artifact tree is produced (FBS/binary/
accessors) plus the background task reports phases/history. The live gd stays
legacy until the coordinated cutover (13.x)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from ct.app.canonical_export import run_canonical_export

FIXTURE = Path(__file__).parents[2] / "tests/fixtures/repository_cutover/workspace"


def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _convert_schemas_to_canonical(root: Path) -> None:
    """One-shot mechanical conversion of the legacy 4 schemas (identity Excel)."""
    schemas = {
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
    types = [
        {"kind": "enum", "name": "ItemRarity", "values": ["common", "rare", "epic"], "comment": "稀有度"},
        {"kind": "record", "name": "ItemDropRange", "comment": "掉落范围", "fields": [
            {"name": "Min", "type": "int32", "comment": "掉落数量下限"},
            {"name": "Max", "type": "int32", "comment": "掉落数量上限"},
        ]},
        {"kind": "enum", "name": "UIConfigLayer", "values": ["Page", "Modal", "Panel", "Overlay"], "comment": "UI 层级"},
    ]
    # clear legacy schemas, write canonical
    schema_dir = root / "config" / "schemas"
    for path in schema_dir.glob("*.yaml"):
        path.unlink()
    for name, schema in schemas.items():
        _write_yaml(schema_dir / f"{name}.yaml", schema)
    for type_def in types:
        _write_yaml(root / "config" / "types" / f"{type_def['name']}.yaml", type_def)


def test_canonical_export_writes_fbs_binary_accessors(tmp_path: Path) -> None:
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    _convert_schemas_to_canonical(workspace)

    run_canonical_export(workspace)
    fbs = workspace / "output" / "fbs"
    assert (fbs / "types.fbs").exists()
    assert "enum ItemRarity : byte" in (fbs / "types.fbs").read_text(encoding="utf-8")
    assert (fbs / "Item.fbs").exists()
    binary = workspace / "output" / "binary"
    for lang in ("zh", "en", "ja"):
        assert (binary / f"data_{lang}.bin").exists()
    generated = workspace / "output" / "generated"
    assert (generated / "csharp" / "ItemAccessor.cs").exists()
    assert (generated / "lua" / "ItemAccessor.lua").exists()


def test_canonical_export_task_reports_phases_and_history(tmp_path: Path) -> None:
    import time

    from ct.web.tasks import canonical_export_task

    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    _convert_schemas_to_canonical(workspace)

    try:
        canonical_export_task.start(workspace, forced=False)
        deadline = time.time() + 20
        steps_seen: list[str] = []
        last: dict = {}
        while time.time() < deadline:
            last = canonical_export_task.progress()
            if last["step_name"]:
                steps_seen.append(last["step_name"])
            if last["status"] != "running":
                break
            time.sleep(0.02)
        assert last.get("status") == "done", last
        assert last["tables_exported"] == 4
        assert last["step_index"] == len(last["steps"]) - 1
        assert last["forced"] is False
        # full phase list is reported; the export is fast, so only assert the
        # complete steps list plus the observed final step (no polling-granularity flake)
        assert last["steps"] == ["解析校验", "JSON", "Accessor", "FBS", "Bundle"]
        assert "Bundle" in steps_seen
        # history entry written to the workspace cache
        history = json.loads(
            (workspace / "cache" / "panel_history.json").read_text(encoding="utf-8")
        )
        assert history[-1]["result"] == "成功"
        assert history[-1]["tables"] == 4
    finally:
        canonical_export_task.status = "idle"
