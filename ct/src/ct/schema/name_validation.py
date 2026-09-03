"""Global resource and generated FlatBuffers symbol validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ct.schema.resources import (
    RecordResource,
    SchemaResource,
    TableResource,
)


@dataclass(frozen=True)
class GeneratedNameConflict:
    name: str
    locations: tuple[str, ...]
    reason: str

    def render(self) -> str:
        return f"生成名称 '{self.name}' {self.reason}: " + ", ".join(self.locations)


def generated_name_conflicts(
    resources: Iterable[SchemaResource],
) -> tuple[GeneratedNameConflict, ...]:
    resources = tuple(resources)
    symbols: dict[str, list[str]] = {}

    def add_symbol(name: str, location: str) -> None:
        symbols.setdefault(name, []).append(location)

    tables = [resource for resource in resources if isinstance(resource, TableResource)]
    for resource in resources:
        add_symbol(resource.name, resource.resource_id)
        if isinstance(resource, TableResource):
            add_symbol(f"{resource.name}Table", f"{resource.resource_id}#container")
            if any(field.i18n for field in resource.fields):
                add_symbol(
                    f"{resource.name}I18nEntry",
                    f"{resource.resource_id}#i18n-entry",
                )
                add_symbol(
                    f"{resource.name}I18nTable",
                    f"{resource.resource_id}#i18n-table",
                )

    if tables:
        add_symbol("IndexEntry", "generated:index")
        add_symbol("BundledTable", "generated:bundle-entry")
        add_symbol("DataBundle", "generated:bundle-root")

    conflicts: list[GeneratedNameConflict] = []
    for name, locations in sorted(symbols.items()):
        if len(locations) > 1:
            conflicts.append(
                GeneratedNameConflict(
                    name=name,
                    locations=tuple(sorted(locations)),
                    reason="由多个类型生成",
                )
            )

    for resource in resources:
        if not isinstance(resource, (TableResource, RecordResource)):
            continue
        for field in resource.fields:
            type_locations = symbols.get(field.name)
            if not type_locations:
                continue
            conflicts.append(
                GeneratedNameConflict(
                    name=field.name,
                    locations=(
                        f"{resource.resource_id}/{field.name}",
                        *tuple(sorted(type_locations)),
                    ),
                    reason="同时用作字段名与 FlatBuffers 类型名",
                )
            )

    return tuple(conflicts)


def require_valid_generated_names(resources: Iterable[SchemaResource]) -> None:
    conflicts = generated_name_conflicts(resources)
    if conflicts:
        raise ValueError("; ".join(conflict.render() for conflict in conflicts))
