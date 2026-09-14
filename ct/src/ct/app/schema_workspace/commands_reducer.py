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
from ct.schema.resource_repository import ResourceDecodeError, decode_resource_payload
from ct.schema.resources import (
    EnumItem,
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    FieldDef,
)
from ct.schema.type_expression import parse_type_expression

DraftState = tuple[tuple[SchemaResource, ...], dict[str, tuple[QueryIndex, ...]]]

_ALLOWED_PROPERTIES = frozenset(
    {"comment", "i18n", "server_only", "excel_columns", "ref"}
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


def _add_resource(command: Command) -> SchemaResource:
    """把 add_resource 命令解成领域模型。

    公开协议是结构化 JSON（``{"kind":..., "resource":{...}}``）；Python 内部
    仍可直接传模型对象，但只认这一种形状，不接受含糊的两套输入。
    """
    if "resource" not in command.payload:
        raise ResourceDecodeError("add_resource 缺少 resource", location="resource")
    resource = command.payload["resource"]
    if isinstance(resource, (TableResource, RecordResource, EnumResource)):
        return resource
    kind = command.payload.get("kind")
    if kind is None and isinstance(resource, dict):
        kind = "table" if "table" in resource else resource.get("kind")
    return decode_resource_payload(kind, resource)


def apply_command(state: DraftState, command: Command) -> DraftState:
    resources, indexes = state
    if command.type == "add_resource":
        resource = _add_resource(command)
        if any(existing.resource_id == resource.resource_id for existing in resources):
            raise ValueError(f"资源 {resource.resource_id} 已存在")
        new_indexes = dict(indexes)
        if isinstance(resource, TableResource):
            # Table 的索引声明随资源一起创建：草稿索引状态必须同步初始化，
            # 否则 merge_indexes 会把它抹成 ()（等价于静默删掉索引）
            new_indexes[resource.resource_id] = tuple(resource.indexes)
        return (resources + (resource,), new_indexes)
    if command.type == "delete_resource":
        name = command.payload["name"]
        index = _resource_index(resources, name)
        new_indexes = dict(indexes)
        new_indexes.pop(resources[index].resource_id, None)
        return (resources[:index] + resources[index + 1:], new_indexes)
    if command.type == "rename_resource":
        result = rename_resource(resources, command.payload["old"], command.payload["new"])
        new_indexes = {
            result.mapping.get(resource_id, resource_id): declared
            for resource_id, declared in indexes.items()
        }
        return (result.resources, new_indexes)
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
        if isinstance(owner, TableResource) and owner.primary == name:
            raise ValueError(f"主键字段 '{name}' 不可删除")
        fields = [f for f in owner.fields if f.name != name]
        updated = owner.model_copy(update={"fields": fields})
        return (_replace_resource(resources, owner_index, updated), indexes)
    if command.type == "move_field":
        owner_id = command.payload["owner"]
        name = command.payload["name"]
        to_index = int(command.payload["to"])
        owner_index = _resource_index(resources, owner_id)
        owner = resources[owner_index]
        if isinstance(owner, TableResource) and owner.primary == name:
            raise ValueError(f"主键字段 '{name}' 不可调整顺序")
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
        values = [EnumItem.model_validate(value) for value in command.payload["values"]]
        index = _resource_index(resources, name)
        resource = resources[index]
        if not isinstance(resource, EnumResource):
            raise ValueError(f"{name} 不是 Enum")
        updated = resource.model_copy(update={"values": values})
        return (_replace_resource(resources, index, updated), indexes)
    if command.type == "rename_enum_item":
        name = command.payload["name"]
        old_name = command.payload["oldName"]
        new_name = command.payload["newName"]
        ordinal = int(command.payload["originalOrdinal"])
        index = _resource_index(resources, name)
        resource = resources[index]
        if not isinstance(resource, EnumResource):
            raise ValueError(f"{name} 不是 Enum")
        if ordinal < 0 or ordinal >= len(resource.values):
            raise ValueError(f"Enum {name}: ordinal {ordinal} 不存在")
        item = resource.values[ordinal]
        if item.name != old_name:
            raise ValueError(f"Enum {name}: ordinal {ordinal} 当前为 {item.name}，不是 {old_name}")
        if any(existing.name == new_name for existing in resource.values):
            raise ValueError(f"Enum {name}: 值 '{new_name}' 已存在")
        values = list(resource.values)
        values[ordinal] = item.model_copy(update={"name": new_name})
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
