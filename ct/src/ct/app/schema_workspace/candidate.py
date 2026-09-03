"""Candidate Workspace construction and full validation (6.3)."""

from __future__ import annotations

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
    RecordResource,
    SchemaResource,
    TableResource,
    named_references,
)
from ct.schema.type_expression import NamedType, VectorType


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
        # role boundaries enforced even when commands bypass model validators
        if isinstance(resource, RecordResource):
            for field in resource.fields:
                if field.i18n:
                    issues.append(
                        CandidateIssue("首版 i18n 仅允许 Table 顶层 string 字段", location=f"{owner}/{field.name}")
                    )
                if field.server_only:
                    issues.append(
                        CandidateIssue("首版 server_only 仅允许 Table 顶层字段", location=f"{owner}/{field.name}")
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
