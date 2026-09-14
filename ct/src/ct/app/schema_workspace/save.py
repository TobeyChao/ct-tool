"""YAML-only transactional save: file plan + shared publisher.

Saving Schema changes writes *only* the resource YAML that actually changed:
the plan keeps unchanged files byte-for-byte (and therefore mtime-for-mtime),
creates files for new resources in the configured directories, deletes the
source files of removed resources, and treats a rename as "write the new path,
delete the old one". Excel workbooks, layout manifests, translations, export
artifacts and the success ledger are never part of the plan.

Planning is pure: it reads the workspace to compare content and returns the
operation set. ``publish_yaml_save`` hands that set to the shared
``FilePublisher`` so an interruption rolls back to the complete previous file
set (including deleting files this transaction created).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.schema.resource_repository import dump_yaml
from ct.schema.resources import (
    EnumResource,
    RecordResource,
    SchemaResource,
    TableResource,
    resource_to_data,
)
from ct.storage.files import normalize
from ct.storage.publication import FilePublisher, PublicationError

YAML_SUFFIX = ".yaml"


@dataclass(frozen=True)
class YamlSavePlan:
    """The exact file operations one save performs."""

    writes: dict[Path, bytes] = field(default_factory=dict)
    deletes: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()
    conflicts: tuple[str, ...] = ()
    targets: dict[str, Path] = field(default_factory=dict)
    #: 需要用户知悉但**不阻断**保存的事实（例如新表的目标工作簿已存在）
    notes: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.writes and not self.deletes

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def to_payload(self) -> dict:
        return {
            "files": sorted(str(path) for path in self.writes),
            "deletes": sorted(str(path) for path in self.deletes),
            "unchanged": sorted(str(path) for path in self.unchanged),
            "conflicts": list(self.conflicts),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class YamlSaveResult:
    written: tuple[Path, ...] = ()
    deleted: tuple[Path, ...] = ()
    unchanged: tuple[Path, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.written or self.deleted)

    def to_payload(self) -> dict:
        return {
            "written": sorted(str(path) for path in self.written),
            "deleted": sorted(str(path) for path in self.deleted),
            "unchanged": sorted(str(path) for path in self.unchanged),
        }


def _load_resource(path: Path) -> SchemaResource | None:
    """Load one persisted YAML file back into its model, for comparison only."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        if "table" in data:
            return TableResource.model_validate(data)
        kind = data.get("kind")
        if kind == "record":
            return RecordResource.model_validate(data)
        if kind == "enum":
            return EnumResource.model_validate(data)
    except Exception:  # noqa: BLE001 - unreadable file is simply "not equal"
        return None
    return None


def _business_content_matches(path: Path, resource: SchemaResource) -> bool:
    """True when the file already holds exactly this resource.

    Comparison goes through the canonical persistence representation, so a file
    that differs only in quoting, key order or explicitly written defaults is
    recognized as unchanged and left untouched.
    """
    if not path.is_file():
        return False
    existing = _load_resource(path)
    if existing is None:
        return False
    try:
        return resource_to_data(existing) == resource_to_data(resource)
    except Exception:  # noqa: BLE001
        return False


def _excel_target(workspace: CanonicalWorkspace, table: TableResource) -> Path:
    """该 Table 的工作簿目标路径（只判断存在性，不读取内容）。"""
    excel_dir = Path(workspace.resolve("excel_dir"))
    return excel_dir / (table.excel_file or f"{table.table}.xlsx")


def resource_target_path(
    workspace: CanonicalWorkspace,
    resource: SchemaResource,
    *,
    known_sources: Mapping[str, Path] | None = None,
) -> Path:
    """Where this resource lives (or should live) on disk."""
    if known_sources and resource.resource_id in known_sources:
        return Path(known_sources[resource.resource_id])
    directory = (
        workspace.config.resolve("schemas_dir")
        if isinstance(resource, TableResource)
        else workspace.config.resolve("types_dir")
    )
    return Path(directory) / f"{resource.name}{YAML_SUFFIX}"


def plan_yaml_save(
    workspace: CanonicalWorkspace,
    resources: Iterable[SchemaResource],
    *,
    known_sources: Mapping[str, Path] | None = None,
) -> YamlSavePlan:
    """Build the file plan for publishing ``resources`` as the new schema set."""
    if known_sources is None:
        known_sources = dict(workspace.resources.sources)
    resources = tuple(resources)
    candidate_ids = {resource.resource_id for resource in resources}
    #: 目标路径 → 拥有它的基线资源（自定义来源文件名时两者可能不一致）
    source_owner = {
        normalize(Path(path)): resource_id for resource_id, path in known_sources.items()
    }

    writes: dict[Path, bytes] = {}
    unchanged: list[Path] = []
    conflicts: list[str] = []
    notes: list[str] = []
    targets: dict[str, Path] = {}
    path_owner: dict[Path, str] = {}
    folded: dict[str, str] = {}
    workbook_owners: dict[str, str] = {}

    for resource in resources:
        if not isinstance(resource, TableResource):
            continue
        workbook = normalize(_excel_target(workspace, resource))
        key = str(workbook).casefold()
        previous = workbook_owners.get(key)
        if previous is not None and previous != resource.resource_id:
            conflicts.append(
                f"多个 Table 映射到同一 Excel 路径 {workbook}："
                f"{previous} / {resource.resource_id}"
            )
        workbook_owners[key] = resource.resource_id

    for resource in resources:
        target = normalize(resource_target_path(workspace, resource, known_sources=known_sources))
        owner = targets.get(resource.resource_id)
        if owner is not None and owner != target:
            conflicts.append(f"资源 {resource.resource_id} 有多个目标路径：{owner} / {target}")
            continue
        targets[resource.resource_id] = target

        key = str(target).casefold()
        previous = folded.get(key)
        if previous is not None and previous != str(target):
            conflicts.append(f"目标路径仅大小写不同，跨平台行为不可确定：{previous} / {target}")
            continue
        folded[key] = str(target)

        claimed_by = path_owner.get(target)
        if claimed_by is not None and claimed_by != resource.resource_id:
            conflicts.append(
                f"多个资源映射到同一目标路径 {target}：{claimed_by} / {resource.resource_id}"
            )
            continue
        path_owner[target] = resource.resource_id

        owner = source_owner.get(target)
        if owner is not None and owner != resource.resource_id and owner in candidate_ids:
            # 该路径是另一个**仍然存在**的资源的源文件（自定义文件名场景）：
            # 直接写入会静默吞掉那个资源
            conflicts.append(
                f"目标路径 {target} 已是资源 {owner} 的源文件，不能再用于 {resource.resource_id}"
            )
            continue

        payload = dump_yaml(resource_to_data(resource)).encode("utf-8")
        is_known_source = target in {normalize(Path(p)) for p in known_sources.values()}
        if isinstance(resource, TableResource) and not is_known_source:
            workbook = _excel_target(workspace, resource)
            if workbook.exists():
                # 保存不碰工作簿；这里只提醒，覆盖与否留给显式模板更新的无损预检
                notes.append(
                    f"新 Table {resource.table} 的目标工作簿已存在：{workbook}"
                    "（保存不改动它；显式更新模板时按无损预检处理）"
                )
        if _business_content_matches(target, resource):
            unchanged.append(target)
            continue
        if target.exists() and not is_known_source:
            conflicts.append(f"目标文件已存在且不在本次变更范围内，拒绝覆盖：{target}")
            continue
        writes[target] = payload

    claimed = set(targets.values())
    deletes = tuple(
        sorted(
            {
                normalize(Path(path))
                for path in known_sources.values()
                if normalize(Path(path)) not in claimed
            }
        )
    )

    return YamlSavePlan(
        writes=writes,
        deletes=deletes,
        unchanged=tuple(sorted(unchanged)),
        conflicts=tuple(conflicts),
        targets=targets,
        notes=tuple(notes),
    )


def publish_yaml_save(root: Path, plan: YamlSavePlan) -> YamlSaveResult:
    """Publish a plan through the shared recoverable file publisher.

    No-op plans touch nothing at all (not even the journal), so a save with no
    real difference leaves the workspace bit-identical.
    """
    if plan.blocked:
        raise ValueError("保存计划存在冲突，拒绝发布：" + "；".join(plan.conflicts))
    if plan.is_empty:
        return YamlSaveResult(unchanged=plan.unchanged)
    try:
        FilePublisher(root).publish(plan.writes, plan.deletes)
    except PublicationError:
        raise
    except OSError as exc:
        # The publisher already rolled back to the previous file set; surface the
        # failure as a publication error so callers report "已回滚" rather than
        # treating it as a bad request.
        raise PublicationError(f"发布 YAML 失败，已回滚到保存前状态：{exc}") from exc
    return YamlSaveResult(
        written=tuple(sorted(plan.writes)),
        deleted=tuple(sorted(plan.deletes)),
        unchanged=plan.unchanged,
    )
