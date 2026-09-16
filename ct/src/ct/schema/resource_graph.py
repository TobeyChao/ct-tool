"""Deterministic dependency graph and reverse references for canonical resources.

Two edge families are analysed:

- named-type edges: a Table/Record field whose Type Expression references a
  named Record/Enum (transitively through ``vector<...>``);
- cross-table ``ref`` edges: a Table field ``ref: Target.Primary`` (a primary-key
  foreign key; ``_validated_ref_target`` is the single place that enforces both
  segments).

Only the canonical resource graph is analysed here; no raw type-string
parsing happens at this layer (consumers already hold TypeExpression nodes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ct.schema.resources import (
    FieldDef,
    RecordResource,
    SchemaResource,
    TableResource,
    named_references,
)
from ct.schema.type_expression import VectorType


@dataclass(frozen=True)
class Reference:
    owner: str  # owner resource id, e.g. "table:Item"
    field_path: str  # canonical field path, e.g. "table:Item/Rewards"
    kind: str  # "named" | "ref"


def named_dependency_edges(
    resources: Iterable[SchemaResource],
) -> dict[str, tuple[str, ...]]:
    """Map a resource id to the sorted record/enum ids it references."""
    graph: dict[str, list[str]] = {}
    for resource in resources:
        owners = [resource.resource_id]
        if isinstance(resource, (TableResource, RecordResource)):
            for field in resource.fields:
                for reference in named_references(field.type_expr):
                    owners.append(reference.resource_id)
        graph[resource.resource_id] = sorted(set(owners[1:]))
    return {key: tuple(values) for key, values in sorted(graph.items())}


def _validated_ref_target(
    owner: str, field: FieldDef, tables: dict[str, TableResource]
) -> TableResource:
    """Resolve ``field.ref`` to its target table, enforcing the primary-key rule.

    ``ref`` declares a foreign key, so it is spelled ``Target.Primary`` and both
    segments are checked here. Every other consumer keys off the table segment
    alone (``ByID`` accessor, value gate against the target primary-key set), so
    an unchecked field segment would silently turn a typo — or a non-primary
    target — into an FK that no gate ever verifies.
    """
    ref = field.ref or ""
    target_table, _, target_field = ref.partition(".")
    target = tables.get(f"table:{target_table}")
    if target is None:
        raise ValueError(
            f"{owner}/{field.name}: 引用的表 '{target_table}' 不存在"
        )
    if target_field != target.primary:
        raise ValueError(
            f"{owner}/{field.name}: ref 目标必须是目标表主键 "
            f"'{target_table}.{target.primary}'（当前 '{ref}'）"
        )
    return target


def cross_table_ref_edges(
    resources: Iterable[SchemaResource],
) -> dict[str, tuple[str, ...]]:
    """Map a table resource id to the sorted target table ids it references."""
    resources = tuple(resources)
    tables = {
        resource.resource_id: resource
        for resource in resources
        if isinstance(resource, TableResource)
    }
    edges: dict[str, list[str]] = {}
    for resource in resources:
        if not isinstance(resource, TableResource):
            continue
        targets: list[str] = []
        for field in resource.fields:
            if not field.ref:
                continue
            targets.append(
                _validated_ref_target(resource.resource_id, field, tables).resource_id
            )
        edges[resource.resource_id] = tuple(sorted(set(targets)))
    return {key: values for key, values in sorted(edges.items())}


def reverse_references(
    resources: Iterable[SchemaResource],
) -> dict[str, tuple[Reference, ...]]:
    """Map a resource id to every place that references it.

    Pure query over the given resources: it does not validate ``ref`` targets
    (``cross_table_ref_edges`` owns that, and every load/candidate path runs the
    topological order first).
    """
    references: dict[str, list[Reference]] = {}
    for resource in resources:
        owner = resource.resource_id
        if isinstance(resource, (TableResource, RecordResource)):
            for field in resource.fields:
                field_path = f"{owner}/{field.name}"
                for reference in named_references(field.type_expr):
                    references.setdefault(reference.resource_id, []).append(
                        Reference(owner, field_path, "named")
                    )
        if isinstance(resource, TableResource):
            for field in resource.fields:
                if not field.ref:
                    continue
                target_table, _, target_field = field.ref.partition(".")
                references.setdefault(f"table:{target_table}", []).append(
                    Reference(owner, f"{owner}/{field.name}", "ref")
                )
                if target_field:
                    references.setdefault(
                        f"table:{target_table}/{target_field}", []
                    ).append(Reference(owner, f"{owner}/{field.name}", "ref"))
    return {
        key: tuple(sorted(values, key=lambda reference: (reference.owner, reference.field_path)))
        for key, values in sorted(references.items())
    }


def _topological_order(
    graph: dict[str, tuple[str, ...]],
    nodes: list[str],
) -> list[str]:
    """Deterministic Kahn topological order; raises on cycle with a path."""
    in_degree: dict[str, int] = {node: 0 for node in nodes}
    dependents: dict[str, list[str]] = {node: [] for node in nodes}
    for node in nodes:
        for dependency in graph.get(node, ()):
            if dependency not in in_degree:
                raise ValueError(
                    f"依赖目标 '{dependency}' 不在资源图中（{node}）"
                )
            in_degree[node] += 1
            dependents[dependency].append(node)

    ready = sorted(node for node in nodes if in_degree[node] == 0)
    result: list[str] = []
    while ready:
        node = ready.pop(0)
        result.append(node)
        for dependent in sorted(dependents[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
                ready.sort()

    if len(result) != len(nodes):
        remaining = sorted(node for node in nodes if node not in result)
        cycle_path = " → ".join(remaining)
        raise ValueError(f"检测到循环依赖: {cycle_path}")
    return result


def resource_topological_order(
    resources: Iterable[SchemaResource],
    *,
    named_graph: dict[str, tuple[str, ...]],
) -> list[str]:
    """Deterministic resource order for emission (named deps first).

    Named resources are emitted before the Tables that depend on them; Tables
    retain their cross-table ``ref`` order so a referenced Table comes first.
    """
    resources = tuple(resources)
    named_nodes = [resource.resource_id for resource in resources]
    named_order = _topological_order(named_graph, named_nodes)

    ref_graph = cross_table_ref_edges(resources)
    table_nodes = [
        resource.resource_id
        for resource in resources
        if isinstance(resource, TableResource)
    ]
    table_order = _topological_order(ref_graph, table_nodes)

    named_ids = {
        resource.resource_id
        for resource in resources
        if not isinstance(resource, TableResource)
    }
    ordered_named = [node for node in named_order if node in named_ids]
    return [*ordered_named, *table_order]


@dataclass(frozen=True)
class DeletionBlocker:
    """A resource/field that is still referenced and therefore not deletable."""

    target: str  # resource id or canonical field path being deleted
    reason: str
    references: tuple[Reference, ...]

    def render(self) -> str:
        use_sites = ", ".join(reference.field_path for reference in self.references)
        return f"无法删除 {self.target}（{self.reason}）: {use_sites}"


def deletion_blockers(
    target: str,
    reverse: dict[str, tuple[Reference, ...]],
) -> tuple[DeletionBlocker, ...]:
    """Return a blocker with every use site when *target* is still referenced."""
    references = reverse.get(target)
    if not references:
        return ()
    return (
        DeletionBlocker(
            target=target,
            reason="仍被引用",
            references=references,
        ),
    )


def require_deletable(
    target: str,
    reverse: dict[str, tuple[Reference, ...]],
) -> None:
    blockers = deletion_blockers(target, reverse)
    if blockers:
        raise ValueError("; ".join(blocker.render() for blocker in blockers))
