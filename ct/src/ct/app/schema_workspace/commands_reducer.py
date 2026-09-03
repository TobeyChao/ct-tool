"""Workspace Draft command reducer with undo/redo cursor semantics.

Commands are pure, deterministic functions over the canonical resource tuple
(plus the table-level index map). Replaying ``commands[:cursor]`` from the
base always reproduces the current Draft, so undo/redo only move the cursor.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ct.schema.commands import rename_field, rename_resource
from ct.schema.indexes import QueryIndex, parse_indexes
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    FieldDef,
)
from ct.schema.type_expression import parse_type_expression

DraftState = tuple[tuple[SchemaResource, ...], dict[str, tuple[QueryIndex, ...]]]

_ALLOWED_PROPERTIES = frozenset(
    {"comment", "i18n", "server_only", "separator", "excel_columns", "ref"}
)


@dataclass(frozen=True)
class Command:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def _resource_index(resources, resource_id: str) -> int:
    for index, resource in enumerate(resources):
        if resource.resource_id == resource_id:
            return index
    raise ValueError(f"资源 {resource_id} 不存在")


def _replace_resource(resources: tuple[SchemaResource, ...], index: int, resource) -> tuple[SchemaResource, ...]:
    return tuple(resources[:index] + (resource,) + resources[index + 1:])


def _field_index(fields: tuple, name: str) -> int:
    for index, field in enumerate(fields):
        if field.name == name:
            return index
    raise ValueError(f"字段 {name} 不存在")


def apply_command(state: DraftState, command: Command) -> DraftState:
    resources, indexes = state
    if command.type == "add_resource":
        resource = command.payload["resource"]
        return (resources + (resource,), indexes)
    if command.type == "delete_resource":
        name = command.payload["name"]
        index = _resource_index(resources, name)
        return (resources[:index] + resources[index + 1:], indexes)
    if command.type == "rename_resource":
        result = rename_resource(resources, command.payload["old"], command.payload["new"])
        return (result.resources, indexes)
    if command.type == "rename_field":
        result = rename_field(
            resources,
            command.payload["owner"],
            command.payload["old"],
            command.payload["new"],
        )
        return (result.resources, indexes)
    if command.type == "add_field":
        owner_id = command.payload["owner"]
        field = FieldDef.model_validate(command.payload["field"])
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        fields = [*owner.fields, field]
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "delete_field":
        owner_id = command.payload["owner"]
        name = command.payload["name"]
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        fields = [f for f in owner.fields if f.name != name]
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "move_field":
        owner_id = command.payload["owner"]
        name = command.payload["name"]
        to_index = int(command.payload["to"])
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        fields = list(owner.fields)
        from_index = _field_index(fields, name)
        field = fields.pop(from_index)
        fields.insert(to_index, field)
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "set_property":
        owner_id = command.payload["owner"]
        name = command.payload["name"]
        prop = command.payload["property"]
        value = command.payload["value"]
        if prop not in _ALLOWED_PROPERTIES:
            raise ValueError(f"不允许的属性: {prop}")
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        field_index = _field_index(tuple(owner.fields), name)
        field = owner.fields[field_index]
        updated_field = field.model_copy(update={prop: value})
        fields = [
            updated_field if index == field_index else f
            for index, f in enumerate(owner.fields)
        ]
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "set_type":
        owner_id = command.payload["owner"]
        name = command.payload["name"]
        type_text = command.payload["type_text"]
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        field_index = _field_index(tuple(owner.fields), name)
        field = owner.fields[field_index]
        updated_field = field.model_copy(update={"type_expr": parse_type_expression(type_text)})
        fields = [
            updated_field if index == field_index else f
            for index, f in enumerate(owner.fields)
        ]
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "set_enum_values":
        name = command.payload["name"]
        values = list(command.payload["values"])
        index = _resource_index(resources, name)
        resource = resources[index]
        if not isinstance(resource, EnumResource):
            raise ValueError(f"{name} 不是 Enum")
        updated = resource.model_copy(update={"values": values})
        return (_replace_resource(resources, index, updated), indexes)
    if command.type == "set_indexes":
        table = command.payload["table"]
        parsed = parse_indexes(command.payload.get("indexes", []))
        new_indexes = dict(indexes)
        new_indexes[table] = parsed
        return (resources, new_indexes)
    raise ValueError(f"未知命令类型: {command.type}")


def apply_commands(state: DraftState, commands: list[Command]) -> DraftState:
    result = state
    for command in commands:
        result = apply_command(result, command)
    return result


@dataclass
class DraftLog:
    """Command log with undo/redo cursor over an immutable base state."""

    base_resources: tuple[SchemaResource, ...]
    base_indexes: dict[str, tuple[QueryIndex, ...]] = field(default_factory=dict)
    commands: list[Command] = field(default_factory=list)
    cursor: int = 0

    def current(self) -> DraftState:
        return apply_commands((self.base_resources, self.base_indexes), self.commands[: self.cursor])

    def execute(self, command: Command) -> None:
        self.commands = self.commands[: self.cursor]
        self.commands.append(command)
        self.cursor += 1

    def undo(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def redo(self) -> None:
        if self.cursor < len(self.commands):
            self.cursor += 1
