"""Deterministic YAML persistence for canonical Schema resources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


def _read_yaml(path: Path, contents: Mapping[Path, bytes] | None = None) -> dict[str, Any] | None:
    try:
        if contents is not None and path in contents:
            data = yaml.safe_load(contents[path].decode("utf-8"))
        else:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"加载 Schema 资源失败 [{path}]: {exc}") from exc
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"加载 Schema 资源失败 [{path}]: 根节点必须是 mapping")
    return data


def old_shape_message(data: dict[str, Any]) -> str | None:
    """旧格式检测（纯函数）：返回诊断文本，或 ``None`` 表示形态合法。

    落盘加载与结构化创建命令复用同一份判断，避免两处规则漂移。
    """
    for index, field in enumerate(data.get("fields", [])):
        if not isinstance(field, dict):
            continue
        old_keys = sorted(_OLD_FIELD_KEYS.intersection(field))
        old_type = field.get("type") in _OLD_TYPE_NAMES
        if old_keys or old_type:
            name = field.get("name", f"#{index + 1}")
            return (
                f"字段 {name} 使用旧格式；请改为具名 Enum/Record 与 vector<T>，"
                "产品不会自动迁移或写回"
            )
    if data.get("kind") == "enum" and any(
        isinstance(item, str) for item in data.get("values", [])
    ):
        return "Enum values 必须是 {name, comment} 结构，产品不会自动迁移"
    return None


def _reject_old_field_shape(data: dict[str, Any], path: Path) -> None:
    message = old_shape_message(data)
    if message is not None:
        raise ValueError(f"加载 Schema 资源失败 [{path}]: {message}")


class ResourceDecodeError(ValueError):
    """结构化创建资源无法解码：带字段位置，供 API/UI 定位。"""

    def __init__(self, message: str, *, location: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.location = location


CREATION_KINDS = ("table", "record", "enum")


def _loc(job: str) -> str:
    return f"resource.{job}" if job else "resource"


def _field_location(location: tuple[Any, ...]) -> str:
    """pydantic error loc → ``fields[0].type`` 形式。"""
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts)


def decode_resource_payload(kind: object, data: object) -> SchemaResource:
    """把 ``add_resource`` 的结构化 payload 解码成领域模型（无文件 I/O）。

    契约（见 add-schema-resource-creation 的 design 决策 2）：

    - ``kind`` 必须是 ``table`` / ``record`` / ``enum``；
    - Table 用 ``table``/``primary``/``fields``；Record/Enum 用 ``name`` 与
      ``fields``/``values``，其 ``kind`` 必须与命令类别一致；
    - 未知键、缺失内容、非法类型表达式、字符串形式的 Enum 值列表一律显式拒绝。
    """
    if kind not in CREATION_KINDS:
        raise ResourceDecodeError(
            f"未知的资源类别 {kind!r}；只支持 {'、'.join(CREATION_KINDS)}",
            location="kind",
        )
    if not isinstance(data, dict):
        raise ResourceDecodeError("resource 必须是对象", location="resource")

    declared = data.get("kind")
    if declared is not None and declared != kind:
        raise ResourceDecodeError(
            f"resource.kind={declared!r} 与命令类别 {kind!r} 不一致",
            location=_loc("kind"),
        )
    if kind == "table":
        if "name" in data:
            raise ResourceDecodeError(
                "Table 使用 table/primary/fields，不接受 name", location=_loc("name")
            )
        if "table" not in data:
            raise ResourceDecodeError("Table 缺少 table", location=_loc("table"))
    else:
        if declared is None:
            data = {**data, "kind": kind}
        if "name" not in data:
            raise ResourceDecodeError(
                f"{kind.capitalize()} 缺少 name", location=_loc("name")
            )

    old_shape = old_shape_message(data)
    if old_shape is not None:
        raise ResourceDecodeError(old_shape, location=_loc(""))

    model = {"table": TableResource, "record": RecordResource, "enum": EnumResource}[kind]
    try:
        return model.model_validate(data)
    except pydantic.ValidationError as exc:
        errors = exc.errors()
        first = errors[0]
        location = _field_location(tuple(first.get("loc", ())))
        messages = []
        for error in errors:
            original = (error.get("ctx") or {}).get("error")
            messages.append(str(original) if original is not None else str(error.get("msg", "")))
        raise ResourceDecodeError(
            "；".join(message for message in messages if message),
            location=_loc(location),
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ResourceDecodeError(str(exc), location=_loc("")) from exc


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
    resolved: list[FieldDef] = []
    for field in fields:
        resolved_type = _resolve_type(
            field.type_expr,
            by_name,
            owner_path=f"{owner_id}/{field.name}",
        )
        if field.excel_columns is not None:
            if not isinstance(resolved_type, VectorType):
                raise ValueError(
                    f"{owner_id}/{field.name}: excel_columns（展开组数）仅适用于"
                    f" vector<T>（定长展开列），当前类型 {field.type_text}"
                )
        if isinstance(resolved_type, VectorType):
            if field.ref is not None:
                raise ValueError(f"{owner_id}/{field.name}: ref 字段不能声明 vector")
            if (
                isinstance(resolved_type.element, NamedType)
                and resolved_type.element.expected_kind == "record"
                and field.excel_columns is None
            ):
                raise ValueError(
                    f"{owner_id}/{field.name}: vector<Record> 必须配置 excel_columns 展开槽位"
                )
        resolved.append(replace_field_type(field, resolved_type))
    return resolved


class YamlResourceRepository:
    def __init__(
        self,
        schemas_dir: Path,
        types_dir: Path,
        contents: Mapping[Path, bytes] | None = None,
    ) -> None:
        self.schemas_dir = schemas_dir
        self.types_dir = types_dir
        #: 捕获到的输入字节；给定时**只**从这些内容解析（不再 glob/读盘），
        #: 从而保证导出使用的资源集合与实际复核的内容完全一致。
        self.contents = contents

    def _paths(self, directory: Path) -> list[Path]:
        if self.contents is None:
            return sorted(directory.glob("*.yaml"))
        return sorted(
            path
            for path in self.contents
            if path.parent == directory and path.name.endswith(".yaml")
        )

    def load(self) -> ResourceWorkspace:
        if self.contents is None and not self.schemas_dir.exists():
            raise FileNotFoundError(f"Schema 目录不存在: {self.schemas_dir}")

        tables: list[TableResource] = []
        records: list[RecordResource] = []
        enums: list[EnumResource] = []
        sources: dict[str, Path] = {}

        for path in self._paths(self.schemas_dir):
            data = _read_yaml(path, self.contents)
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

        if self.contents is not None or self.types_dir.exists():
            for path in self._paths(self.types_dir):
                data = _read_yaml(path, self.contents)
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
