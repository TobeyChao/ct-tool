"""End-to-end verification for created resources (tasks 4.2-4.3)."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from flatbuffers import encode, number_types as ntypes
from flatbuffers.table import Table

from ct.app.canonical_commands import CanonicalValidationError, canonical_validate
from ct.app.canonical_commands import canonical_gen_template
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.exporting.models import ExportRequest
from ct.app.exporting.service import run_export
from ct.app.schema_workspace.candidate import candidate_hash
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.web.app import create_app

from _helpers import build_project, make_workbook, set_cell


def _root(tmp_path: Path) -> Path:
    return build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "comment": "名称"},
                ],
            }
        ],
    )


def _candidate(root: Path, commands: list[dict]) -> str:
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for item in commands:
        log.execute(Command(item["type"], item.get("payload") or {}))
    resources, indexes = log.current()
    return candidate_hash(resources, indexes)


def _save(client, root: Path, commands: list[dict]) -> dict:
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    resp = client.post(
        "/api/schema-workspace/save",
        json={
            "schemaRevision": revision,
            "commands": commands,
            "candidateHash": _candidate(root, commands),
        },
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]


def _add(kind: str, resource: dict) -> dict:
    return {"type": "add_resource", "payload": {"kind": kind, "resource": resource}}


def _add_field(owner: str, field: dict) -> dict:
    return {"type": "add_field", "payload": {"owner": owner, "field": field}}


def _bundle_table(bundle: bytes, table: str) -> bytes:
    """从 DataBundle 中取出某张表的 bytes。"""
    buf = memoryview(bundle)
    u16 = lambda o: struct.unpack_from("<H", buf, o)[0]
    i32 = lambda o: struct.unpack_from("<i", buf, o)[0]
    root = i32(0)
    vt = root - i32(root)
    vec = root + u16(vt + 4)
    vec += i32(vec)
    base, count = vec + 4, i32(vec)
    for index in range(count):
        element = base + index * 4
        entry = element + i32(element)
        evt = entry - i32(entry)
        name_off = entry + u16(evt + 4)
        name_off += i32(name_off)
        name = bytes(buf[name_off + 4:name_off + 4 + i32(name_off)]).decode()
        if name != table:
            continue
        data_off = entry + u16(evt + 6)
        data_off += i32(data_off)
        return bytes(buf[data_off + 4:data_off + 4 + i32(data_off)])
    raise AssertionError(f"bundle 中没有 {table}")


def _quest_rows(data: bytes) -> list[dict]:
    """读取新表 Quest（Id int32 / Rarity enum byte / Reward record）的二进制行。"""
    buf = memoryview(data)
    u32 = ntypes.UOffsetTFlags.packer_type
    root = encode.Get(u32, buf, 0)
    container = Table(buf, root)
    items = container.Offset(4)
    count = container.VectorLen(items)
    start = container.Vector(items)
    rows = []
    for index in range(count):
        element = start + 4 * index
        pos = element + encode.Get(u32, buf, element)
        row = Table(buf, pos)

        def scalar(table, slot, flags, default=0):
            offset = table.Offset(4 + 2 * slot)
            return default if offset == 0 else table.Get(flags, table.Pos + offset)

        reward = None
        reward_offset = row.Offset(4 + 2 * 2)
        if reward_offset:
            child = row.Pos + reward_offset
            child += encode.Get(u32, buf, child)
            record = Table(buf, child)
            reward = {
                "Min": scalar(record, 0, ntypes.Int32Flags),
                "Max": scalar(record, 1, ntypes.Int32Flags),
            }
        rows.append(
            {
                "Id": scalar(row, 0, ntypes.Int32Flags),
                "Rarity": scalar(row, 1, ntypes.Int8Flags),
                "Reward": reward,
            }
        )
    return rows


def test_create_related_resources_then_template_data_and_export(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()

    # ---- 保存 #1：三类关联资源（Table 引用新建的 Record / Enum）
    creations = [
        _add(
            "enum",
            {
                "kind": "enum",
                "name": "ItemRarity",
                "values": [
                    {"name": "Common", "comment": "普通"},
                    {"name": "Rare", "comment": "稀有"},
                ],
            },
        ),
        _add(
            "record",
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [
                    {"name": "Min", "type": "int32"},
                    {"name": "Max", "type": "int32"},
                ],
            },
        ),
        _add(
            "table",
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Rarity", "type": "ItemRarity"},
                    {"name": "Reward", "type": "DropReward"},
                ],
            },
        ),
    ]
    data = _save(client, root, creations)
    assert {Path(path).name for path in data["written"]} == {
        "DropReward.yaml",
        "ItemRarity.yaml",
        "Quest.yaml",
    }

    canonical_gen_template(root, all_tables=True)
    make_workbook(root, "Quest", [[1, "Rare", 3, 5]])
    make_workbook(root, "Item", [[1, "铁剑"]])
    assert canonical_validate(root) == []
    run_export(ExportRequest(root=root, forced=True))

    manifests = root / "excel" / "layout_manifests"
    manifests_before = {p.name: p.read_bytes() for p in manifests.glob("*.json")}
    artifacts_before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "output").rglob("*")
        if path.is_file()
    }
    ledger = root / "cache" / "state.json"
    ledger_before = ledger.read_bytes()

    # ---- 保存 #2：已有表引用新增类型（保存只改 YAML，不动 Excel/产物/账本）
    workbook_before = (root / "excel" / "Item.xlsx").read_bytes()
    data2 = _save(client, root, [_add_field("table:Item", {"name": "Rarity", "type": "ItemRarity"})])
    assert {Path(path).name for path in data2["written"]} == {"Item.yaml"}
    assert (root / "excel" / "Item.xlsx").read_bytes() == workbook_before
    assert {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "output").rglob("*")
        if path.is_file()
    } == artifacts_before
    assert ledger.read_bytes() == ledger_before

    # 模板没更新 ⇒ 读取闸门拒绝导出，且不刷新 manifest/产物/账本
    with pytest.raises(CanonicalValidationError) as excinfo:
        run_export(ExportRequest(root=root, forced=True))
    assert any(issue.table == "Item" for issue in excinfo.value.issues)
    assert {p.name: p.read_bytes() for p in manifests.glob("*.json")} == manifests_before
    assert {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "output").rglob("*")
        if path.is_file()
    } == artifacts_before
    assert ledger.read_bytes() == ledger_before

    # ---- 显式更新模板 + 填数据 → 校验与导出成功
    canonical_gen_template(root, all_tables=True)
    set_cell(root, "Item", 1, 3, "Common")
    assert canonical_validate(root) == []
    run_export(ExportRequest(root=root, forced=True))

    quest_json = json.loads((root / "output" / "json" / "Quest_zh.json").read_text("utf-8"))
    assert quest_json["Quests"][0] == {
        "Id": 1,
        "Rarity": "Rare",
        "Reward": {"Min": 3, "Max": 5},
    }
    item_json = json.loads((root / "output" / "json" / "Item_zh.json").read_text("utf-8"))
    assert item_json["Items"][0]["Rarity"] == "Common"

    types_fbs = (root / "output" / "fbs" / "types.fbs").read_text("utf-8")
    assert "enum ItemRarity : byte" in types_fbs
    assert "table DropReward" in types_fbs
    quest_fbs = (root / "output" / "fbs" / "Quest.fbs").read_text("utf-8")
    assert "Rarity" in quest_fbs and "Reward" in quest_fbs

    bundle = (root / "output" / "binary" / "data_zh.bin").read_bytes()
    assert _quest_rows(_bundle_table(bundle, "Quest")) == [
        {"Id": 1, "Rarity": 1, "Reward": {"Min": 3, "Max": 5}}
    ]

    assert "ByID" in (
        root / "output" / "generated" / "csharp" / "QuestAccessor.cs"
    ).read_text("utf-8")
    assert (root / "output" / "generated" / "lua" / "QuestAccessor.lua").is_file()
    assert "ItemRarity" in (
        root / "output" / "generated" / "csharp" / "Enums.cs"
    ).read_text("utf-8")
    assert "ItemRarity" in (
        root / "output" / "generated" / "lua" / "Enums.lua"
    ).read_text("utf-8")


def test_unreferenced_types_reload_and_export_gate(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    commands = [
        _add(
            "record",
            {"kind": "record", "name": "Unused", "fields": [{"name": "Amount", "type": "int32"}]},
        ),
        _add(
            "enum",
            {"kind": "enum", "name": "UnusedEnum", "values": [{"name": "A", "comment": ""}]},
        ),
    ]
    _save(client, root, commands)

    reloaded = CanonicalWorkspace.load(root)
    ids = {resource.resource_id for resource in reloaded.resources.resources}
    assert {"record:Unused", "enum:UnusedEnum"} <= ids
    # 未被引用的类型不影响既有表导出
    canonical_gen_template(root, all_tables=True)
    make_workbook(root, "Item", [[1, "铁剑"]])
    assert canonical_validate(root) == []
    run_export(ExportRequest(root=root, forced=True))


def test_new_table_regressions_ref_i18n_server_only_and_codename(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    commands = [
        _add(
            "table",
            {"table": "ItemType", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        ),
        _add(
            "table",
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "CodeName", "type": "string"},
                    {"name": "Title", "type": "string", "i18n": True},
                    {"name": "Debug", "type": "int32", "server_only": True},
                    {"name": "TypeId", "type": "int32", "ref": "ItemType.Id"},
                ],
                "indexes": [{"kind": "codename"}],
            },
        ),
    ]
    _save(client, root, commands)
    canonical_gen_template(root, all_tables=True)
    make_workbook(root, "ItemType", [[1]])
    make_workbook(root, "Quest", [[1, "q_sword", "铁剑", 7, 1]])

    assert canonical_validate(root) == []
    run_export(ExportRequest(root=root, forced=True))

    # server_only 不进客户端 FBS/Binary，i18n 走稀疏侧表，CodeName 索引生成 API
    quest_fbs = (root / "output" / "fbs" / "Quest.fbs").read_text("utf-8")
    assert "Debug" not in quest_fbs
    names = _bundle_names((root / "output" / "binary" / "data_en.bin").read_bytes())
    assert "Quest_i18n" in names and "Quest" not in names
    accessor = (root / "output" / "generated" / "csharp" / "QuestAccessor.cs").read_text("utf-8")
    assert "ByCodeName" in accessor

    # 外键值越界：导出失败且既有产物/账本不变
    manifest_dir = root / "excel" / "layout_manifests"
    manifests_before = {p.name: p.read_bytes() for p in manifest_dir.glob("*.json")}
    artifacts_before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "output").rglob("*")
        if path.is_file()
    }
    ledger = root / "cache" / "state.json"
    ledger_before = ledger.read_bytes()
    set_cell(root, "Quest", 1, 5, 99)  # 只改数据，不重建模板
    with pytest.raises(CanonicalValidationError):
        run_export(ExportRequest(root=root, forced=True))
    assert {p.name: p.read_bytes() for p in manifest_dir.glob("*.json")} == manifests_before
    assert {
        str(path.relative_to(root)): path.read_bytes()
        for path in (root / "output").rglob("*")
        if path.is_file()
    } == artifacts_before
    assert ledger.read_bytes() == ledger_before


def _bundle_names(bundle: bytes) -> list[str]:
    buf = memoryview(bundle)
    u16 = lambda o: struct.unpack_from("<H", buf, o)[0]
    i32 = lambda o: struct.unpack_from("<i", buf, o)[0]
    root = i32(0)
    vt = root - i32(root)
    vec = root + u16(vt + 4)
    vec += i32(vec)
    base, count = vec + 4, i32(vec)
    names = []
    for index in range(count):
        element = base + index * 4
        entry = element + i32(element)
        evt = entry - i32(entry)
        name_off = entry + u16(evt + 4)
        name_off += i32(name_off)
        names.append(bytes(buf[name_off + 4:name_off + 4 + i32(name_off)]).decode())
    return names
