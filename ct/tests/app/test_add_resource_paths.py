"""Creation paths, collisions and preflight checks (task 2.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.app.canonical_commands import canonical_gen_template
from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import candidate_hash, merge_indexes
from ct.app.schema_workspace.commands_reducer import Command, DraftLog
from ct.app.schema_workspace.save import plan_yaml_save, publish_yaml_save
from ct.web.app import create_app

from _helpers import build_project, write_yaml


def _root(tmp_path: Path, *, schemas_dir: str = "config/schemas", types_dir: str = "config/types") -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {"table": "Item", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}
        ],
    )
    write_yaml(
        root / "config" / "global.yaml",
        {
            "primary_lang": "zh",
            "secondary_langs": ["en"],
            "schemas_dir": schemas_dir,
            "types_dir": types_dir,
        },
    )
    for source, target in (
        (root / "config" / "schemas" / "Item.yaml", root / schemas_dir / "Item.yaml"),
    ):
        if source.parent != target.parent:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            source.unlink()
            source.parent.rmdir()
    (root / "config" / "types").mkdir(parents=True, exist_ok=True)
    return root


EXTERNAL_RECORD = (
    "kind: record\nname: Other\nfields:\n  - {name: Amount, type: int32}\n"
)


def _add(kind: str, resource: dict) -> Command:
    return Command("add_resource", {"kind": kind, "resource": resource})


def _candidate(workspace: CanonicalWorkspace, commands: list[Command]) -> str:
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for command in commands:
        log.execute(command)
    resources, indexes = log.current()
    return candidate_hash(resources, indexes)


def test_creation_honors_configured_directories(tmp_path: Path) -> None:
    root = _root(tmp_path, schemas_dir="config/tables", types_dir="config/kinds")
    workspace = CanonicalWorkspace.load(root)
    commands = [
        _add("enum", {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": ""}]}),
        _add("table", {"table": "Quest", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]}),
    ]
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    for command in commands:
        log.execute(command)
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert {path.name for path in plan.writes} == {"ItemRarity.yaml", "Quest.yaml"}
    assert (root / "config" / "kinds" / "ItemRarity.yaml") in plan.writes
    assert (root / "config" / "tables" / "Quest.yaml") in plan.writes

    publish_yaml_save(root, plan)
    reloaded = CanonicalWorkspace.load(root)
    assert {"enum:ItemRarity", "table:Quest"} <= {
        resource.resource_id for resource in reloaded.resources.resources
    }
    assert not (root / "config" / "schemas").exists()


def test_case_folded_path_collision_is_a_conflict(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add("record", {"kind": "record", "name": "Reward", "fields": [{"name": "Amount", "type": "int32"}]})
    )
    log.execute(
        _add("record", {"kind": "record", "name": "REWARD", "fields": [{"name": "Amount", "type": "int32"}]})
    )
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert plan.blocked
    assert any("大小写" in conflict for conflict in plan.conflicts)


@pytest.mark.parametrize("excel_file", ["Quest.xlsx", "QUEST.xlsx", "./Quest.xlsx"])
def test_new_table_cannot_share_an_existing_tables_workbook(tmp_path: Path, excel_file: str) -> None:
    root = _root(tmp_path)
    write_yaml(root / "config/schemas/Item.yaml", {
        "table": "Item", "primary": "Id", "excel_file": excel_file,
        "fields": [{"name": "Id", "type": "int32"}],
    })
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    command = {
        "type": "add_resource",
        "payload": {"kind": "table", "resource": {
            "table": "Quest", "primary": "Id",
            "fields": [{"name": "Id", "type": "int32"}],
        }},
    }
    candidate = client.post("/api/schema-workspace/candidate", json={"commands": [command]}).get_json()["data"]
    before = (root / "config/schemas/Item.yaml").read_bytes()
    response = client.post("/api/schema-workspace/save", json={
        "schemaRevision": revision, "candidateHash": candidate["candidateHash"],
        "commands": [command],
    })
    assert response.status_code == 409
    body = response.get_json()
    assert body["conflict"]["kind"] == "target"
    assert "table:Item" in body["error"] and "table:Quest" in body["error"]
    assert not (root / "config/schemas/Quest.yaml").exists()
    assert (root / "config/schemas/Item.yaml").read_bytes() == before


def test_existing_workbook_for_a_new_table_is_reported_as_a_note(tmp_path: Path) -> None:
    root = _root(tmp_path)
    workbook = root / "excel" / "Quest.xlsx"
    workbook.parent.mkdir(parents=True, exist_ok=True)
    workbook.write_bytes(b"orphan-workbook")

    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    commands = [
        {
            "type": "add_resource",
            "payload": {
                "kind": "table",
                "resource": {
                    "table": "Quest",
                    "primary": "Id",
                    "fields": [{"name": "Id", "type": "int32"}],
                },
            },
        }
    ]
    workspace = CanonicalWorkspace.load(root)
    resp = client.post(
        "/api/schema-workspace/save",
        json={
            "schemaRevision": revision,
            "commands": commands,
            "candidateHash": _candidate(workspace, [Command(item["type"], item["payload"]) for item in commands]),
        },
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["notes"] and "Quest" in data["notes"][0]
    # 保存不碰工作簿；显式更新模板时缺少 manifest 会拒绝（无损预检）
    assert workbook.read_bytes() == b"orphan-workbook"
    with pytest.raises(ValueError, match="缺少布局 manifest"):
        canonical_gen_template(root, table_filter="Quest")


def test_external_target_created_before_publish_is_a_conflict(tmp_path: Path) -> None:
    root = _root(tmp_path)
    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    commands = [
        {
            "type": "add_resource",
            "payload": {
                "kind": "record",
                "resource": {
                    "kind": "record",
                    "name": "Extra",
                    "fields": [{"name": "Amount", "type": "int32"}],
                },
            },
        }
    ]
    workspace = CanonicalWorkspace.load(root)
    candidate = _candidate(workspace, [Command(item["type"], item["payload"]) for item in commands])

    import ct.web.schema_workspace_api as api_module

    real_plan = api_module.plan_yaml_save

    def plan_then_external_create(workspace_arg, resources_arg, **kwargs):
        # 计划生成之后、发布前复核之前，外部进程抢先创建了目标文件
        plan = real_plan(workspace_arg, resources_arg, **kwargs)
        (root / "config" / "types" / "Extra.yaml").write_text(
            EXTERNAL_RECORD, encoding="utf-8"
        )
        return plan

    api_module.plan_yaml_save = plan_then_external_create
    try:
        resp = client.post(
            "/api/schema-workspace/save",
            json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
        )
    finally:
        api_module.plan_yaml_save = real_plan

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["conflict"]["kind"] in {"target", "schema-revision"}
    assert "Other" in (root / "config" / "types" / "Extra.yaml").read_text(encoding="utf-8")


def test_external_yaml_at_a_new_target_blocks_the_save(tmp_path: Path) -> None:
    root = _root(tmp_path)
    target = root / "config" / "types" / "Extra.yaml"
    target.write_text(EXTERNAL_RECORD, encoding="utf-8")

    client = create_app(root).test_client()
    revision = client.get("/api/schema-workspace").get_json()["data"]["schemaRevision"]
    commands = [
        {
            "type": "add_resource",
            "payload": {
                "kind": "record",
                "resource": {
                    "kind": "record",
                    "name": "Extra",
                    "fields": [{"name": "Amount", "type": "int32"}],
                },
            },
        }
    ]
    workspace = CanonicalWorkspace.load(root)
    candidate = _candidate(workspace, [Command(item["type"], item["payload"]) for item in commands])
    resp = client.post(
        "/api/schema-workspace/save",
        json={"schemaRevision": revision, "commands": commands, "candidateHash": candidate},
    )
    assert resp.status_code == 409
    assert "Other" in target.read_text(encoding="utf-8")


def test_new_resource_cannot_take_over_a_kept_resources_source_file(tmp_path: Path) -> None:
    """自定义来源文件名：新资源的默认路径撞上仍在的资源的源文件时必须冲突。"""
    root = _root(tmp_path)
    # Other 资源存在，但源文件是自定义名 Extra.yaml
    (root / "config" / "types" / "Extra.yaml").write_text(
        "kind: record\nname: Other\nfields:\n  - {name: Amount, type: int32}\n",
        encoding="utf-8",
    )
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(
        _add("record", {"kind": "record", "name": "Extra", "fields": [{"name": "Amount", "type": "int32"}]})
    )
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert plan.blocked
    # 两个资源抢同一个文件：冲突消息必须点出路径和两个资源 id
    conflict = plan.conflicts[0]
    assert "Extra.yaml" in conflict
    assert "record:Other" in conflict and "record:Extra" in conflict
    assert "Other" in (root / "config" / "types" / "Extra.yaml").read_text(encoding="utf-8")


def test_deleted_resource_frees_its_source_path_for_a_new_one(tmp_path: Path) -> None:
    """被删除的资源不再占用路径：新资源可以接管（不是静默覆盖）。"""
    root = _root(tmp_path)
    (root / "config" / "types" / "Extra.yaml").write_text(
        "kind: record\nname: Other\nfields:\n  - {name: Amount, type: int32}\n",
        encoding="utf-8",
    )
    workspace = CanonicalWorkspace.load(root)
    log = DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))
    log.execute(Command("delete_resource", {"name": "record:Other"}))
    log.execute(
        _add("record", {"kind": "record", "name": "Extra", "fields": [{"name": "Amount", "type": "int32"}]})
    )
    plan = plan_yaml_save(workspace, merge_indexes(*log.current()))
    assert not plan.blocked
    assert [path.name for path in plan.writes] == ["Extra.yaml"]
    publish_yaml_save(root, plan)
    reloaded = CanonicalWorkspace.load(root)
    assert "record:Extra" in {resource.resource_id for resource in reloaded.resources.resources}
    assert "record:Other" not in {resource.resource_id for resource in reloaded.resources.resources}
