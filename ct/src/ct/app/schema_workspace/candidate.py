"""Candidate Workspace construction and full validation (6.3)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ct.schema.indexes import QueryIndex, validate_indexes
from ct.schema.name_validation import generated_name_conflicts
from ct.schema.resource_graph import (
    named_dependency_edges,
    resource_topological_order,
)
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    SchemaResource,
    TableResource,
    named_references,
    resource_to_data,
)
from ct.schema.type_expression import NamedType, VectorType

CANDIDATE_FORMAT = "workspace-candidate/1"


def _resolve_named(
    type_expr,
    by_name: dict[str, SchemaResource],
):
    """Rewrite unresolved NamedType nodes to their concrete kind-prefixed id."""
    if isinstance(type_expr, NamedType):
        if type_expr.expected_kind is not None and ":" in type_expr.resource_id:
            return type_expr
        target = by_name.get(type_expr.name)
        if target is None:
            return type_expr
        kind = "record" if isinstance(target, RecordResource) else "enum"
        return NamedType(resource_id=f"{kind}:{type_expr.name}", expected_kind=kind)
    if isinstance(type_expr, VectorType):
        return VectorType(element=_resolve_named(type_expr.element, by_name))
    return type_expr


def merge_indexes(
    resources: tuple[SchemaResource, ...],
    indexes: dict[str, tuple[QueryIndex, ...]],
) -> tuple[SchemaResource, ...]:
    """把草稿里的索引**并进 Table 资源**。

    索引原本只存在于编辑器的草稿字典里，落盘时被丢弃 —— 于是编辑器里设的索引从来
    没有到达 YAML/导出器。并进资源后，持久化、加载、导出走同一条数据通路
    （``save.plan_yaml_save`` 写出的就是并进索引后的资源）。
    """
    merged: list[SchemaResource] = []
    for resource in resources:
        if isinstance(resource, TableResource):
            merged.append(
                resource.model_copy(update={"indexes": tuple(indexes.get(resource.resource_id, ()))})
            )
        else:
            merged.append(resource)
    return tuple(merged)


def _resolve_candidate_resources(
    resources: tuple[SchemaResource, ...],
    by_name: dict[str, SchemaResource],
) -> tuple[SchemaResource, ...]:
    """Return resources with named references resolved against the candidate set."""
    resolved: list[SchemaResource] = []
    for resource in resources:
        if isinstance(resource, (TableResource, RecordResource)):
            fields = [
                field.model_copy(update={"type_expr": _resolve_named(field.type_expr, by_name)})
                for field in resource.fields
            ]
            resolved.append(resource.model_copy(update={"fields": fields}))
        else:
            resolved.append(resource)
    return tuple(resolved)


@dataclass(frozen=True)
class CandidateIssue:
    message: str
    location: str = ""  # resource id or canonical field path
    kind: str = "blocker"

    def render(self) -> str:
        return f"{self.message}（{self.location}）" if self.location else self.message


def candidate_hash(
    resources: tuple[SchemaResource, ...],
    indexes: dict[str, tuple[QueryIndex, ...]],
) -> str:
    """Deterministic identity of a candidate, used for optimistic concurrency.

    Built from the canonical persistence representation with resources sorted by
    identity, so browser-side command order or object key order cannot change it,
    while every structural change necessarily does.
    """
    merged = merge_indexes(resources, indexes)
    payload = {
        "format": CANDIDATE_FORMAT,
        "resources": [
            resource_to_data(resource)
            for resource in sorted(merged, key=lambda item: item.resource_id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_candidate(
    resources: tuple[SchemaResource, ...],
    indexes: dict[str, tuple[QueryIndex, ...]],
) -> tuple[CandidateIssue, ...]:
    """Run the full candidate validation, returning precise issues."""
    issues: list[CandidateIssue] = []

    by_name: dict[str, SchemaResource] = {}
    for resource in resources:
        previous = by_name.get(resource.name)
        if previous is not None:
            issues.append(
                CandidateIssue(
                    f"资源名 '{resource.name}' 重复",
                    location=f"{previous.resource_id} ↔ {resource.resource_id}",
                )
            )
        by_name[resource.name] = resource

    resolved_resources = _resolve_candidate_resources(resources, by_name)
    resolved_by_id = {r.resource_id: r for r in resolved_resources}

    for conflict in generated_name_conflicts(resolved_resources):
        issues.append(
            CandidateIssue(
                conflict.render(),
                location=", ".join(conflict.locations),
            )
        )

    # named references resolve to a concrete kind and target
    for resource in resolved_resources:
        owner = resource.resource_id
        if isinstance(resource, (TableResource, RecordResource)):
            # Validate fields individually first. Pydantic skips a parent
            # model's ``after`` validator when a nested field fails, so doing
            # this separately prevents one bad field from hiding other role
            # and shape errors in the same draft.
            for field in resource.fields:
                try:
                    FieldDef.model_validate(
                        field.model_dump(mode="python", by_alias=True)
                    )
                except (TypeError, ValueError) as exc:
                    issues.append(
                        CandidateIssue(str(exc), location=f"{owner}/{field.name}")
                    )
            if isinstance(resource, TableResource):
                primary = next(
                    (field for field in resource.fields if field.name == resource.primary),
                    None,
                )
                if primary is not None and primary.server_only:
                    issues.append(
                        CandidateIssue(
                            f"表 {resource.table}: 主键字段 '{resource.primary}' 不能标记 server_only",
                            location=f"{owner}/{resource.primary}",
                        )
                    )
            # Draft mutations use frozen-model_copy for responsiveness, which
            # intentionally does not rerun Pydantic model validators. Rebuild
            # each resource here so set_property/set_type cannot bypass the
            # same field/table invariants enforced when YAML is loaded.
            try:
                type(resource).model_validate(
                    resource.model_dump(mode="python", by_alias=True)
                )
            except (TypeError, ValueError) as exc:
                issues.append(CandidateIssue(str(exc), location=owner))
            for field in resource.fields:
                for reference in named_references(field.type_expr):
                    target = by_name.get(reference.name)
                    if target is None:
                        issues.append(
                            CandidateIssue(
                                f"具名类型 '{reference.name}' 不存在",
                                location=f"{owner}/{field.name}",
                            )
                        )
                        continue
                    if isinstance(target, TableResource):
                        issues.append(
                            CandidateIssue(
                                f"字段类型不能直接引用 Table '{target.name}'",
                                location=f"{owner}/{field.name}",
                            )
                        )
                    elif reference.expected_kind is not None:
                        actual = "record" if isinstance(target, RecordResource) else "enum"
                        if reference.expected_kind != actual:
                            issues.append(
                                CandidateIssue(
                                    f"期望 {reference.expected_kind}，实际为 {actual}",
                                    location=f"{owner}/{field.name}",
                                )
                            )
    # dependency cycles (over the resolved resource graph)
    if resolved_resources:
        try:
            resource_topological_order(
                resolved_resources,
                named_graph=named_dependency_edges(resolved_resources),
            )
        except ValueError as exc:
            issues.append(CandidateIssue(str(exc)))

    # index validation per table
    for table in resources:
        if isinstance(table, TableResource):
            table_indexes = indexes.get(table.resource_id, ())
            try:
                validate_indexes(table, table_indexes)
            except ValueError as exc:
                issues.append(
                    CandidateIssue(str(exc), location=table.resource_id)
                )

    return tuple(issues)
