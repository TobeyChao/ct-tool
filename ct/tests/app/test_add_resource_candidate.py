"""Candidate-level validation for newly created resources (task 2.1)."""

from __future__ import annotations

from pathlib import Path

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.candidate import merge_indexes, validate_candidate
from ct.app.schema_workspace.commands_reducer import Command, DraftLog

from _helpers import build_project


def _workspace(tmp_path: Path, *, schemas: list[dict] | None = None, types: list[dict] | None = None):
    root = build_project(
        tmp_path / "gd",
        schemas=schemas
        or [
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string"},
                ],
            }
        ],
        types=types or [],
    )
    return root, CanonicalWorkspace.load(root)


def _log(workspace: CanonicalWorkspace) -> DraftLog:
    return DraftLog(workspace.resources.resources, base_indexes=dict(workspace.indexes))


def _add(kind: str, resource: dict) -> Command:
    return Command("add_resource", {"kind": kind, "resource": resource})


def _issues(log: DraftLog):
    resources, indexes = log.current()
    return validate_candidate(merge_indexes(resources, indexes), indexes)


def test_enum_record_table_chain_is_a_valid_candidate(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "enum",
            {"kind": "enum", "name": "ItemRarity", "values": [{"name": "Common", "comment": ""}]},
        )
    )
    log.execute(
        _add(
            "record",
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [
                    {"name": "Min", "type": "int32"},
                    {"name": "Rarity", "type": "ItemRarity"},
                ],
            },
        )
    )
    log.execute(
        _add(
            "table",
            {
                "table": "Quest",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Reward", "type": "DropReward"},
                    {"name": "Rarity", "type": "ItemRarity"},
                ],
            },
        )
    )
    assert _issues(log) == ()


def test_ref_to_a_newly_created_table_is_allowed(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "table",
            {"table": "ItemType", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        )
    )
    log.execute(
        _add(
            "table",
            {
                "table": "Drop",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "TypeId", "type": "int32", "ref": "ItemType.Id"},
                ],
            },
        )
    )
    assert _issues(log) == ()


def test_ref_to_a_non_primary_field_is_reported_with_location(tmp_path: Path) -> None:
    """候选校验同样只认目标表主键：ref 指向普通字段必须报错。"""
    _root, workspace = _workspace(tmp_path)  # Item 有 Id（主键）与 Name
    log = _log(workspace)
    log.execute(
        _add(
            "table",
            {
                "table": "Drop",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "TypeName", "type": "string", "ref": "Item.Name"},
                ],
            },
        )
    )
    issues = _issues(log)
    # 依赖图错误带 owner/字段路径前缀（与循环依赖一致，location 为空）
    assert any(
        "table:Drop/TypeName" in issue.message
        and "必须是目标表主键 'Item.Id'" in issue.message
        for issue in issues
    )


def test_missing_named_reference_is_reported_with_location(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {
                "kind": "record",
                "name": "DropReward",
                "fields": [{"name": "Rarity", "type": "MissingEnum"}],
            },
        )
    )
    issues = _issues(log)
    assert issues
    assert any("MissingEnum" in issue.message for issue in issues)
    assert any(issue.location == "record:DropReward/Rarity" for issue in issues)


def test_reference_to_a_new_table_as_field_type_is_rejected(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "table",
            {"table": "ItemType", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        )
    )
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "R", "fields": [{"name": "Type", "type": "ItemType"}]},
        )
    )
    issues = _issues(log)
    assert any("Table" in issue.message for issue in issues)


def test_dependency_cycle_between_new_records_is_reported(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "A", "fields": [{"name": "B", "type": "B"}]},
        )
    )
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "B", "fields": [{"name": "A", "type": "A"}]},
        )
    )
    issues = _issues(log)
    assert issues
    assert any("循环" in issue.message or "环" in issue.message for issue in issues)


def test_cross_category_duplicate_name_is_rejected(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "Item", "fields": [{"name": "Amount", "type": "int32"}]},
        )
    )
    issues = _issues(log)
    assert any("重复" in issue.message for issue in issues)


def test_generated_name_collision_is_reported(tmp_path: Path) -> None:
    """新 Record 的生成名撞上已有 Table 的容器名（ItemTable）。"""
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "record",
            {"kind": "record", "name": "ItemTable", "fields": [{"name": "Amount", "type": "int32"}]},
        )
    )
    issues = _issues(log)
    assert any("生成名称" in issue.message for issue in issues)


def test_two_new_enums_with_conflicting_generated_names(tmp_path: Path) -> None:
    _root, workspace = _workspace(tmp_path)
    log = _log(workspace)
    log.execute(
        _add(
            "table",
            {"table": "Item2", "primary": "Id", "fields": [{"name": "Id", "type": "int32"}]},
        )
    )
    log.execute(
        _add(
            "enum",
            {"kind": "enum", "name": "Item2", "values": [{"name": "Common", "comment": ""}]},
        )
    )
    issues = _issues(log)
    assert any("重复" in issue.message or "生成名称" in issue.message for issue in issues)
