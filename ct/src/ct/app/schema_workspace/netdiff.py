"""Normalized net difference between the on-disk baseline and a draft candidate.

The draft keeps an honest command history (every click, including the ones the
user undid), while the status bar and the save summary must describe the *net*
effect: "N resources have unsaved changes". This module derives that net effect
from structure alone:

* resources are matched by canonical identity (``kind:Name``);
* explicit rename commands connect a base identity to its final identity, so
  ``A -> B -> C`` reports one rename ``A -> C`` and ``A -> B -> A`` reports
  nothing at all;
* a delete followed by an add is **not** inferred as a rename;
* content comparison uses the canonical persistence representation, so object
  key order, default values and repeated edits of the same property never
  manufacture a difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ct.app.schema_workspace.commands_reducer import (
    Command,
    DraftState,
    apply_command,
)
from ct.schema.commands import rename_field, rename_resource
from ct.schema.resources import EnumResource, FieldDef, SchemaResource, resource_to_data

NET_DIFF_FORMAT = "net-diff/1"

ADDED = "added"
REMOVED = "removed"
MODIFIED = "modified"
RENAMED = "renamed"


@dataclass(frozen=True)
class FieldDiff:
    """One field of a changed resource, in its final name."""

    name: str
    change: str
    old_name: str | None = None
    details: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "change": self.change}
        if self.old_name is not None and self.old_name != self.name:
            payload["oldName"] = self.old_name
        if self.details:
            payload["details"] = list(self.details)
        return payload


@dataclass(frozen=True)
class ResourceDiff:
    """One changed resource, counted once no matter how many commands touched it."""

    kind: str
    name: str
    change: str
    old_name: str | None = None
    fields: tuple[FieldDiff, ...] = ()

    @property
    def resource_id(self) -> str:
        return f"{self.kind}:{self.name}"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "resourceId": self.resource_id,
            "kind": self.kind,
            "name": self.name,
            "change": self.change,
        }
        if self.old_name is not None and self.old_name != self.name:
            payload["oldName"] = self.old_name
        if self.fields:
            payload["fields"] = [item.to_payload() for item in self.fields]
        return payload

    def render(self) -> str:
        label = {
            ADDED: "新增",
            REMOVED: "删除",
            MODIFIED: "修改",
            RENAMED: "重命名",
        }.get(self.change, self.change)
        if self.change == RENAMED and self.old_name:
            return f"{self.kind} {self.old_name} → {self.name}"
        return f"{label} {self.kind} {self.name}"


@dataclass(frozen=True)
class NetDiff:
    """The complete, ordered net difference of one draft."""

    changes: tuple[ResourceDiff, ...] = field(default_factory=tuple)

    @property
    def changed_resources(self) -> int:
        return len(self.changes)

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": NET_DIFF_FORMAT,
            "changedResources": self.changed_resources,
            "isNoOp": self.is_empty,
            "resources": [item.to_payload() for item in self.changes],
        }

    def summary(self) -> str:
        return "；".join(item.render() for item in self.changes)


def _resource_paths(state: DraftState) -> set[str]:
    paths: set[str] = set()
    for resource in state[0]:
        owner = resource.resource_id
        paths.add(owner)
        for item in getattr(resource, "fields", getattr(resource, "values", ())):
            paths.add(f"{owner}/{item.name}")
    return paths


def rename_identity(
    base: DraftState,
    commands: Sequence[Command] | Iterable[Command] = (),
    *,
    cursor: int | None = None,
) -> dict[str, str]:
    """Map base canonical paths to their current path via explicit renames.

    Only explicit ``rename_resource`` / ``rename_field`` commands connect two
    identities; nothing is ever inferred from names alone. Entries whose path is
    unchanged (including round trips such as ``A -> B -> A``) are omitted.
    """
    command_list = list(commands)
    if cursor is not None:
        command_list = command_list[:cursor]

    forward = {path: path for path in _resource_paths(base)}
    state = base
    for command in command_list:
        mapping: dict[str, str] = {}
        try:
            if command.type == "rename_resource":
                mapping = rename_resource(
                    state[0], command.payload["old"], command.payload["new"]
                ).mapping
            elif command.type == "rename_enum_item":
                owner = command.payload["name"]
                mapping = {f"{owner}/{command.payload['oldName']}": f"{owner}/{command.payload['newName']}"}
            elif command.type == "rename_field":
                mapping = rename_field(
                    state[0],
                    command.payload["owner"],
                    command.payload["old"],
                    command.payload["new"],
                ).mapping
        except (KeyError, ValueError):
            # A malformed tail must not stop the diff: history is best effort,
            # the structural comparison below stays authoritative.
            mapping = {}
        if mapping:
            for old, new in mapping.items():
                for origin, current in list(forward.items()):
                    if current == old or current.startswith(old + "/"):
                        forward[origin] = new + current[len(old):]
        try:
            state = apply_command(state, command)
        except (KeyError, ValueError):
            break
    return {origin: current for origin, current in forward.items() if origin != current}


def _normalized_resource(resource: SchemaResource) -> dict[str, Any]:
    """Canonical persistence shape without identity keys."""
    data = resource_to_data(resource)
    data.pop("name", None)
    data.pop("table", None)
    return data


def _field_payload(field: FieldDef) -> dict[str, Any]:
    data = field.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    data.pop("name", None)
    return data


def _field_details(before: FieldDef, after: FieldDef) -> tuple[str, ...]:
    old = _field_payload(before)
    new = _field_payload(after)
    return tuple(
        sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
    )


def _kind_of(resource: SchemaResource) -> str:
    return resource.resource_id.partition(":")[0]


def _field_diffs(
    owner_after: str,
    before: SchemaResource,
    after: SchemaResource,
    identity: dict[str, str],
) -> tuple[FieldDiff, ...]:
    if isinstance(before, EnumResource) and isinstance(after, EnumResource):
        old_values = {item.name: (i, item) for i, item in enumerate(before.values)}
        new_values = {item.name: (i, item) for i, item in enumerate(after.values)}
        result = []
        matched = set()
        for name, (old_ordinal, item) in old_values.items():
            path = identity.get(f"{before.resource_id}/{name}", f"{owner_after}/{name}")
            final_name = path.rpartition("/")[2]
            target = new_values.get(final_name)
            if target is None:
                result.append(FieldDiff(name, REMOVED, details=(f"ordinal {old_ordinal} → 删除 · wire 风险",)))
                continue
            matched.add(final_name)
            ordinal, new_item = target
            details = []
            if ordinal != old_ordinal:
                details.append(f"ordinal {old_ordinal} → {ordinal} · wire 风险")
            elif name != final_name:
                details.append(f"ordinal {ordinal} 不变 · API 名称变化")
            if item.comment != new_item.comment:
                details.append("comment")
            if name != final_name or details:
                result.append(FieldDiff(final_name, RENAMED if name != final_name else MODIFIED,
                                        old_name=name, details=tuple(details)))
        for name, (ordinal, _) in new_values.items():
            if name not in matched:
                result.append(FieldDiff(name, ADDED, details=(f"新增 ordinal {ordinal}",)))
        return tuple(result)
    before_fields = {field.name: field for field in getattr(before, "fields", ())}
    after_fields = {field.name: field for field in getattr(after, "fields", ())}
    before_owner = before.resource_id
    diffs: list[FieldDiff] = []
    matched: set[str] = set()

    for name, field in before_fields.items():
        target_path = identity.get(f"{before_owner}/{name}", f"{before_owner}/{name}")
        target_owner, _, target_name = target_path.rpartition("/")
        target = after_fields.get(target_name) if target_owner == owner_after else None
        if target is None:
            diffs.append(FieldDiff(name=name, change=REMOVED))
            continue
        matched.add(target_name)
        if target_name != name:
            diffs.append(
                FieldDiff(
                    name=target_name,
                    change=RENAMED,
                    old_name=name,
                    details=_field_details(field, target),
                )
            )
            continue
        details = _field_details(field, target)
        if details:
            diffs.append(FieldDiff(name=name, change=MODIFIED, details=details))

    for name in after_fields:
        if name not in matched and name not in before_fields:
            diffs.append(FieldDiff(name=name, change=ADDED))

    order = {name: index for index, name in enumerate(after_fields)}
    diffs.sort(key=lambda item: (item.change == ADDED, order.get(item.name, len(order)), item.name))
    return tuple(diffs)


def compute_net_diff(
    base: DraftState,
    candidate: DraftState,
    commands: Sequence[Command] | Iterable[Command] = (),
    *,
    cursor: int | None = None,
) -> NetDiff:
    """Return the net difference between the baseline state and the candidate."""
    identity = rename_identity(base, commands, cursor=cursor)
    base_resources = {resource.resource_id: resource for resource in base[0]}
    candidate_resources = {resource.resource_id: resource for resource in candidate[0]}

    changes: list[ResourceDiff] = []
    claimed: set[str] = set()

    for base_id, before in base_resources.items():
        final_id = identity.get(base_id, base_id)
        after = candidate_resources.get(final_id)
        if after is None:
            changes.append(
                ResourceDiff(
                    kind=_kind_of(before),
                    name=before.name,
                    change=REMOVED,
                )
            )
            continue
        claimed.add(final_id)
        fields = _field_diffs(final_id, before, after, identity)
        renamed = final_id != base_id
        if renamed:
            changes.append(
                ResourceDiff(
                    kind=_kind_of(after),
                    name=after.name,
                    change=RENAMED,
                    old_name=before.name,
                    fields=fields,
                )
            )
            continue
        if _normalized_resource(before) != _normalized_resource(after):
            changes.append(
                ResourceDiff(
                    kind=_kind_of(after),
                    name=after.name,
                    change=MODIFIED,
                    fields=fields,
                )
            )

    for candidate_id, after in candidate_resources.items():
        if candidate_id in claimed:
            continue
        changes.append(
            ResourceDiff(kind=_kind_of(after), name=after.name, change=ADDED)
        )

    changes.sort(key=lambda item: (item.resource_id, item.change))
    return NetDiff(changes=tuple(changes))
