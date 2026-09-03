"""Explicit rename commands that update every candidate reference atomically.

Renames are pure functions over frozen canonical resources: they return a new
resource tuple plus an old→new canonical-path mapping. Applying the inverse
rename restores the original workspace (undo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ct.schema.naming import validate_name
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    replace_field_type,
)
from ct.schema.type_expression import NamedType, TypeExpression, VectorType


@dataclass(frozen=True)
class RenameResult:
    resources: tuple[SchemaResource, ...]
    mapping: dict[str, str]  # old canonical path -> new canonical path

    @property
    def reverse_mapping(self) -> dict[str, str]:
        return {new_path: old_path for old_path, new_path in self.mapping.items()}


def _remap_named_references(
    type_expr: TypeExpression,
    name_map: dict[str, str],
) -> TypeExpression:
    """Rewrite every named reference whose resource name is in ``name_map``."""
    if isinstance(type_expr, NamedType):
        new_name = name_map.get(type_expr.name)
        if new_name is None or new_name == type_expr.name:
            return type_expr
        kind = type_expr.expected_kind
        resource_id = f"{kind}:{new_name}" if kind else new_name
        return NamedType(resource_id=resource_id, expected_kind=kind)
    if isinstance(type_expr, VectorType):
        return VectorType(element=_remap_named_references(type_expr.element, name_map))
    return type_expr


def _remap_resource(
    resource: SchemaResource,
    *,
    renamed: dict[str, str],
    ref_table_map: dict[str, str],
) -> SchemaResource:
    """Apply name/ref rewrites to one resource without mutating the input."""
    fields = getattr(resource, "fields", ())
    new_fields = [
        replace_field_type(field, _remap_named_references(field.type_expr, renamed))
        for field in fields
    ]
    # cross-table refs: "OldTable.Field" -> "NewTable.Field" when a table renames
    if isinstance(resource, TableResource):
        new_fields = [
            field.model_copy(
                update={
                    "ref": (
                        ref_table_map[field.ref.partition(".")[0]]
                        + field.ref[len(field.ref.partition(".")[0]):]
                        if field.ref and field.ref.partition(".")[0] in ref_table_map
                        else field.ref
                    )
                }
            )
            for field in new_fields
        ]

    renamed_id = renamed.get(resource.name)
    if isinstance(resource, TableResource) and renamed_id is not None:
        return resource.model_copy(update={"table": renamed_id, "fields": new_fields})
    if isinstance(resource, RecordResource) and renamed_id is not None:
        return resource.model_copy(update={"name": renamed_id, "fields": new_fields})
    if isinstance(resource, EnumResource) and renamed_id is not None:
        return resource.model_copy(update={"name": renamed_id})
    return resource.model_copy(update={"fields": new_fields})


def rename_resource(
    resources: Iterable[SchemaResource],
    old_name: str,
    new_name: str,
) -> RenameResult:
    """Rename a resource and every reference to it, atomically."""
    name_error = validate_name(new_name)
    if name_error:
        raise ValueError(f"新资源名 {new_name}: {name_error}")
    resources = tuple(resources)
    names = {resource.name for resource in resources}
    if old_name not in names:
        raise ValueError(f"资源 '{old_name}' 不存在")
    if new_name in names and new_name != old_name:
        raise ValueError(f"资源名 '{new_name}' 已存在")

    renamed = {old_name: new_name}
    old_resource = next(
        resource for resource in resources if resource.name == old_name
    )
    # cross-table refs only target Tables; a record/enum rename never rewrites refs
    ref_table_map = {old_name: new_name} if isinstance(old_resource, TableResource) else {}

    new_resources = tuple(
        _remap_resource(resource, renamed=renamed, ref_table_map=ref_table_map)
        for resource in resources
    )
    return RenameResult(
        resources=new_resources,
        mapping={old_resource.resource_id: f"{old_resource.resource_id.partition(':')[0]}:{new_name}"},
    )


def rename_field(
    resources: Iterable[SchemaResource],
    owner_id: str,
    old_field: str,
    new_field: str,
) -> RenameResult:
    """Rename a field on its owner and update cross-table ``ref`` targets."""
    field_error = validate_name(new_field)
    if field_error:
        raise ValueError(f"新字段名 {new_field}: {field_error}")
    resources = tuple(resources)
    owner = next(
        (resource for resource in resources if resource.resource_id == owner_id),
        None,
    )
    if owner is None:
        raise ValueError(f"资源 {owner_id} 不存在")
    fields = getattr(owner, "fields", ())
    if not any(field.name == old_field for field in fields):
        raise ValueError(f"{owner_id}/{old_field} 不存在")
    if any(field.name == new_field for field in fields) and new_field != old_field:
        raise ValueError(f"{owner_id}/{new_field} 已存在")

    owner_table = owner_id.partition(":")[2]

    def remap_field(field):
        if field.name == old_field:
            field = field.model_copy(update={"name": new_field})
        ref = field.ref
        if ref and ref == f"{owner_table}.{old_field}":
            field = field.model_copy(update={"ref": f"{owner_table}.{new_field}"})
        return field

    new_resources = []
    for resource in resources:
        if resource.resource_id == owner_id:
            new_fields = [remap_field(field) for field in fields]
            new_resources.append(
                resource.model_copy(update={"fields": new_fields})
            )
        elif isinstance(resource, TableResource):
            new_fields = [remap_field(field) for field in resource.fields]
            new_resources.append(resource.model_copy(update={"fields": new_fields}))
        else:
            new_resources.append(resource)

    return RenameResult(
        resources=tuple(new_resources),
        mapping={f"{owner_id}/{old_field}": f"{owner_id}/{new_field}"},
    )
