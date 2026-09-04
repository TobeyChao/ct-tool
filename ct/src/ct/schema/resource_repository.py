"""Deterministic YAML persistence for canonical Schema resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pydantic
import yaml

from ct.schema.name_validation import require_valid_generated_names
from ct.schema.resources import (
    EnumResource,
    FieldDef,
    RecordResource,
    SchemaResource,
    TableResource,
    replace_field_type,
    resource_to_data,
)
from ct.schema.type_expression import NamedType, TypeExpression, VectorType


_OLD_FIELD_KEYS = frozenset({"values", "fields", "element", "element_values"})
_OLD_TYPE_NAMES = frozenset({"enum", "struct", "array"})


class _IndentedDumper(yaml.SafeDumper):
    """PyYAML dumper that indents block sequences under their parent key.

    The default SafeDumper emits ``fields:`` immediately followed by a
    top-level ``- name:`` line.  Overriding ``increase_indent`` pushes each
    sequence item one level deeper, matching the conventional style::

        fields:
          - name: Id
            type: int32
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, indentless=False)


def dump_yaml(data: Any) -> str:
    """Serialize ``data`` as deterministic, human-diffable YAML.

    Sequences are indented under their parent key (see ``_IndentedDumper``);
    keys keep their model order and unicode is written verbatim.
    """
    return yaml.dump(data, Dumper=_IndentedDumper, allow_unicode=True, sort_keys=False)


@dataclass(frozen=True)
class ResourceWorkspace:
    tables: tuple[TableResource, ...]
    records: tuple[RecordResource, ...]
    enums: tuple[EnumResource, ...]
    by_name: dict[str, SchemaResource]
    by_id: dict[str, SchemaResource]
    sources: dict[str, Path]

    @property
    def resources(self) -> tuple[SchemaResource, ...]:
        return (*self.tables, *self.records, *self.enums)


def _validation_text(exc: Exception) -> str:
    if not isinstance(exc, pydantic.ValidationError):
        return str(exc)
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        context = error.get("ctx") or {}
        original = context.get("error")
        message = str(original) if original is not None else error.get("msg", str(exc))
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)


def _read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"加载 Schema 资源失败 [{path}]: {exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"加载 Schema 资源失败 [{path}]: 根节点必须是 mapping")
    return data


def _reject_old_field_shape(data: dict[str, Any], path: Path) -> None:
    for index, field in enumerate(data.get("fields", [])):
        if not isinstance(field, dict):
            continue
        old_keys = sorted(_OLD_FIELD_KEYS.intersection(field))
        old_type = field.get("type") in _OLD_TYPE_NAMES
        if old_keys or old_type:
            name = field.get("name", f"#{index + 1}")
            raise ValueError(
                f"加载 Schema 资源失败 [{path}]: 字段 {name} 使用旧格式；"
                "请改为具名 Enum/Record 与 vector<T>，产品不会自动迁移或写回"
            )


def _resolve_type(
    type_expr: TypeExpression,
    by_name: dict[str, SchemaResource],
    *,
    owner_path: str,
) -> TypeExpression:
    if isinstance(type_expr, VectorType):
        return VectorType(
            element=_resolve_type(type_expr.element, by_name, owner_path=owner_path)
        )
    if not isinstance(type_expr, NamedType):
        return type_expr
    target = by_name.get(type_expr.name)
    if target is None:
        raise ValueError(f"{owner_path}: 具名类型 '{type_expr.name}' 不存在")
    if isinstance(target, TableResource):
        raise ValueError(f"{owner_path}: 字段类型不能直接引用 Table '{target.name}'")
    kind = "record" if isinstance(target, RecordResource) else "enum"
    if type_expr.expected_kind is not None and type_expr.expected_kind != kind:
        raise ValueError(
            f"{owner_path}: 期望 {type_expr.expected_kind}，"
            f"但 '{type_expr.name}' 实际为 {kind}"
        )
    return type_expr.resolve(kind)


def _resolve_fields(
    fields: list[FieldDef],
    by_name: dict[str, SchemaResource],
    *,
    owner_id: str,
) -> list[FieldDef]:
    return [
        replace_field_type(
            field,
            _resolve_type(
                field.type_expr,
                by_name,
                owner_path=f"{owner_id}/{field.name}",
            ),
        )
        for field in fields
    ]


class YamlResourceRepository:
    def __init__(self, schemas_dir: Path, types_dir: Path) -> None:
        self.schemas_dir = schemas_dir
        self.types_dir = types_dir

    def load(self) -> ResourceWorkspace:
        if not self.schemas_dir.exists():
            raise FileNotFoundError(f"Schema 目录不存在: {self.schemas_dir}")

        tables: list[TableResource] = []
        records: list[RecordResource] = []
        enums: list[EnumResource] = []
        sources: dict[str, Path] = {}

        for path in sorted(self.schemas_dir.glob("*.yaml")):
            data = _read_yaml(path)
            if data is None:
                continue
            _reject_old_field_shape(data, path)
            try:
                resource = TableResource.model_validate(data)
            except Exception as exc:
                raise ValueError(
                    f"加载 Table 失败 [{path.name}]: {_validation_text(exc)}"
                ) from exc
            tables.append(resource)
            sources[resource.resource_id] = path

        if self.types_dir.exists():
            for path in sorted(self.types_dir.glob("*.yaml")):
                data = _read_yaml(path)
                if data is None:
                    continue
                _reject_old_field_shape(data, path)
                kind = data.get("kind")
                try:
                    if kind == "record":
                        resource = RecordResource.model_validate(data)
                        records.append(resource)
                    elif kind == "enum":
                        resource = EnumResource.model_validate(data)
                        enums.append(resource)
                    else:
                        raise ValueError("kind 必须为 record 或 enum")
                except Exception as exc:
                    raise ValueError(
                        f"加载具名类型失败 [{path.name}]: {_validation_text(exc)}"
                    ) from exc
                sources[resource.resource_id] = path

        all_resources: list[SchemaResource] = [*tables, *records, *enums]
        by_name: dict[str, SchemaResource] = {}
        for resource in all_resources:
            previous = by_name.get(resource.name)
            if previous is not None:
                raise ValueError(
                    f"资源名 '{resource.name}' 重复: "
                    f"{sources[previous.resource_id].name} 和 "
                    f"{sources[resource.resource_id].name}"
                )
            by_name[resource.name] = resource

        require_valid_generated_names(all_resources)

        resolved_tables = [
            table.model_copy(
                update={
                    "fields": _resolve_fields(
                        table.fields,
                        by_name,
                        owner_id=table.resource_id,
                    )
                }
            )
            for table in tables
        ]
        resolved_records = [
            record.model_copy(
                update={
                    "fields": _resolve_fields(
                        record.fields,
                        by_name,
                        owner_id=record.resource_id,
                    )
                }
            )
            for record in records
        ]
        resolved_enums = enums

        resolved: list[SchemaResource] = [
            *resolved_tables,
            *resolved_records,
            *resolved_enums,
        ]
        resolved_by_name = {resource.name: resource for resource in resolved}
        return ResourceWorkspace(
            tables=tuple(resolved_tables),
            records=tuple(resolved_records),
            enums=tuple(resolved_enums),
            by_name=resolved_by_name,
            by_id={resource.resource_id: resource for resource in resolved},
            sources=sources,
        )

    def write(self, resource: SchemaResource) -> Path:
        target_dir = (
            self.schemas_dir if isinstance(resource, TableResource) else self.types_dir
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{resource.name}.yaml"
        text = dump_yaml(resource_to_data(resource))
        target.write_text(text, encoding="utf-8")
        return target
