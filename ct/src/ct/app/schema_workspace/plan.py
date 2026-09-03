"""Change Plan: risk classification and per-artifact impact records (6.4/6.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ct.app.schema_workspace.candidate import CandidateIssue
from ct.cache.fingerprints import schema_fingerprint
from ct.excel.layout import Layout, build_layout
from ct.excel.planning import PlanIssue, plan_excel_migration
from ct.schema.indexes import QueryIndex
from ct.schema.resources import RecordResource, SchemaResource, TableResource


@dataclass(frozen=True)
class Impact:
    artifact: str  # Schema | Excel | FBS | Binary | Accessor
    table: str
    action: str  # generate | rebuild | migrate | blocked
    detail: str = ""


@dataclass(frozen=True)
class ChangePlan:
    issues: tuple[CandidateIssue | PlanIssue, ...] = field(default_factory=tuple)
    impacts: tuple[Impact, ...] = field(default_factory=tuple)
    risk: str = "safe"  # safe | data-dependent | destructive | incompatible | dependency-breaking

    @property
    def blocked(self) -> bool:
        return any(getattr(issue, "kind", "warning") == "blocker" for issue in self.issues)


def _table_map(resources: tuple[SchemaResource, ...]) -> dict[str, TableResource]:
    return {
        resource.table: resource
        for resource in resources
        if isinstance(resource, TableResource)
    }


def _records(resources: tuple[SchemaResource, ...]) -> dict[str, RecordResource]:
    return {
        resource.name: resource
        for resource in resources
        if isinstance(resource, RecordResource)
    }


def _fps(table: TableResource, records, indexes: tuple[QueryIndex, ...]):
    dependencies = []
    for reference in table.fields:
        name = _ref_name(reference)
        if name and name in records:
            dependencies.append(
                records[name].model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
            )
    return schema_fingerprint(
        table.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True),
        dependencies,
        [{"kind": index.kind, "field": index.field} for index in indexes],
        codegen_version="1.0",
    )


def _ref_name(field) -> str | None:
    from ct.schema.type_expression import NamedType, VectorType

    expr = field.type_expr
    if isinstance(expr, NamedType):
        return expr.name
    if isinstance(expr, VectorType) and isinstance(expr.element, NamedType):
        return expr.element.name
    return None


def build_change_plan(
    old_resources: tuple[SchemaResource, ...],
    new_resources: tuple[SchemaResource, ...],
    *,
    old_indexes: dict[str, tuple[QueryIndex, ...]],
    new_indexes: dict[str, tuple[QueryIndex, ...]],
    excel_dir=None,
    layouts: dict[str, tuple[Layout, Layout]] | None = None,
) -> ChangePlan:
    old_tables = _table_map(old_resources)
    new_tables = _table_map(new_resources)
    old_records = _records(old_resources)
    new_records = _records(new_resources)

    impacts: list[Impact] = []
    issues: list[Any] = []

    old_shared = {r.resource_id: r for r in old_resources if not isinstance(r, TableResource)}
    new_shared = {r.resource_id: r for r in new_resources if not isinstance(r, TableResource)}
    changed_shared = [
        resource_id
        for resource_id in old_shared
        if new_shared.get(resource_id) != old_shared[resource_id]
    ]

    all_tables = set(old_tables) | set(new_tables)
    for table in sorted(all_tables):
        old_table = old_tables.get(table)
        new_table = new_tables.get(table)
        if new_table is None:
            impacts.append(Impact("Schema", table, "delete"))
            continue
        if old_table is None:
            impacts.append(Impact("Schema", table, "generate"))
            impacts.append(Impact("Excel", table, "generate"))
            continue

        old_schema = _fps(old_table, old_records, old_indexes.get(old_table.resource_id, ()))
        new_schema = _fps(new_table, new_records, new_indexes.get(new_table.resource_id, ()))
        schema_changed = old_schema != new_schema
        data_changed = schema_changed  # data artifacts follow schema at resource level
        index_changed = old_indexes.get(old_table.resource_id, ()) != new_indexes.get(new_table.resource_id, ())

        if schema_changed or index_changed:
            impacts.append(Impact("Schema", table, "rebuild"))
            impacts.append(Impact("FBS", table, "rebuild"))
            impacts.append(Impact("Accessor", table, "rebuild"))
        if data_changed:
            impacts.append(Impact("Binary", table, "rebuild"))
        if table in new_tables:
            impacts.append(Impact("Excel", table, "migrate" if schema_changed or index_changed else "keep"))

        # Excel data migration risk scan
        if excel_dir is not None and table in old_tables and table in new_tables:
            layouts_pair = layouts.get(table) if layouts else None
            if layouts_pair is not None:
                old_layout, new_layout = layouts_pair
                excel_path = excel_dir / (new_table.excel_file or f"{new_table.table}.xlsx")
                plan = plan_excel_migration(old_layout, new_layout, excel_path)
                issues.extend(plan.issues)
                if plan.blocked:
                    impacts.append(Impact("Excel", table, "blocked"))

    # dependency-breaking risk
    risk = "safe"
    if changed_shared:
        risk = "dependency-breaking"
    if any(getattr(issue, "kind", "") == "blocker" for issue in issues):
        risk = "destructive" if risk != "dependency-breaking" else risk
    elif any(issue.kind == "untracked" for issue in issues if isinstance(issue, PlanIssue)):
        risk = "data-dependent"

    return ChangePlan(
        issues=tuple(issues),
        impacts=tuple(impacts),
        risk=risk,
    )
