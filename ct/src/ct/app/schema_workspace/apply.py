"""Transactional Apply: plan manifest, staging, journal, publish, recovery.

Logical atomicity: after any normal completion or recovery the observable
workspace equals the complete old revision or the complete new revision,
never a long-lived mixed set. This is achieved with a same-filesystem
staging dir, a durable journal, a transaction backup, stepwise ``os.replace``
publishing and startup recovery — not a kernel-level atomic multi-file swap.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ct.app.canonical_workspace import CanonicalWorkspace
from ct.app.schema_workspace.snapshot import build_snapshot

PLAN_TTL_SECONDS = 7200  # default two-hour plan expiry
PLAN_FORMAT = "apply-plan/1"
JOURNAL_FORMAT = "apply-journal/1"


class ApplyError(Exception):
    """A plan cannot be applied or recovered; the workspace is untouched."""


@dataclass(frozen=True)
class PlanManifest:
    plan_id: str
    base_revision: str
    candidate_hash: str
    created_at: float
    expires_at: float
    staging_dir: Path
    targets: tuple[tuple[str, str], ...]  # (relative path, staging relative path)
    table_fingerprints: dict[str, Any] = None  # per-table fps to publish

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) > self.expires_at


def _stable_sha256(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _staging_for(workspace: CanonicalWorkspace) -> Path:
    return workspace.resolve("cache_dir") / "staging"


def _plans_dir(workspace: CanonicalWorkspace) -> Path:
    return workspace.resolve("cache_dir") / "plans"


def _journal_path(workspace: CanonicalWorkspace) -> Path:
    return workspace.resolve("cache_dir") / "apply.journal.json"


def _lock_path(workspace: CanonicalWorkspace) -> Path:
    return workspace.resolve("cache_dir") / "apply.lock"


class WorkspaceApplyLock:
    def __init__(self, workspace: CanonicalWorkspace) -> None:
        self.path = _lock_path(workspace)

    def __enter__(self) -> "WorkspaceApplyLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise ApplyError(f"工作区已被其他 Apply 占用: {self.path}")
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def create_plan(
    workspace: CanonicalWorkspace,
    *,
    candidate_resources: list[Any],
    candidate_indexes: dict[str, Any],
    targets: list[tuple[str, str]],  # (relative target, relative staging)
    table_fingerprints: dict[str, Any],
) -> PlanManifest:
    """Create a plan manifest without touching real workspace files."""
    with WorkspaceApplyLock(workspace):
        base_revision = build_snapshot(workspace).revision
        candidate_hash = _stable_sha256(
            {
                "resources": [r.model_dump(mode="json") for r in candidate_resources],
                "indexes": candidate_indexes,
            }
        )
        plan_id = uuid.uuid4().hex[:12]
        now = time.time()
        staging = _staging_for(workspace) / plan_id
        staging.mkdir(parents=True, exist_ok=True)
        for _, staging_relative in targets:
            (staging / staging_relative).parent.mkdir(parents=True, exist_ok=True)
        manifest = PlanManifest(
            plan_id=plan_id,
            base_revision=base_revision,
            candidate_hash=candidate_hash,
            created_at=now,
            expires_at=now + PLAN_TTL_SECONDS,
            staging_dir=staging,
            targets=tuple(targets),
            table_fingerprints=table_fingerprints,
        )
        plans_dir = _plans_dir(workspace)
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / f"{plan_id}.json").write_text(
            json.dumps(_manifest_payload(manifest), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return manifest


def _manifest_payload(manifest: PlanManifest) -> dict[str, Any]:
    return {
        "format": PLAN_FORMAT,
        "plan_id": manifest.plan_id,
        "base_revision": manifest.base_revision,
        "candidate_hash": manifest.candidate_hash,
        "created_at": manifest.created_at,
        "expires_at": manifest.expires_at,
        "staging_dir": str(manifest.staging_dir),
        "targets": list(manifest.targets),
        "table_fingerprints": manifest.table_fingerprints,
    }


def load_plan(workspace: CanonicalWorkspace, plan_id: str) -> PlanManifest | None:
    path = _plans_dir(workspace) / f"{plan_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("format") != PLAN_FORMAT:
        return None
    try:
        return PlanManifest(
            plan_id=data["plan_id"],
            base_revision=data["base_revision"],
            candidate_hash=data["candidate_hash"],
            created_at=float(data["created_at"]),
            expires_at=float(data["expires_at"]),
            staging_dir=Path(data["staging_dir"]),
            targets=tuple(tuple(pair) for pair in data["targets"]),
            table_fingerprints=data.get("table_fingerprints"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def validate_plan_stale(
    workspace: CanonicalWorkspace,
    manifest: PlanManifest,
    *,
    base_revision: str,
    candidate_hash: str,
    now: float | None = None,
) -> None:
    """Reject stale/expired plans before any write happens."""
    if manifest.is_expired(now):
        raise ApplyError("plan 已过期，请重新生成")
    current_revision = build_snapshot(workspace).revision
    if current_revision != base_revision:
        raise ApplyError("plan 已过期：源工作区已变化，请重新审查")
    if candidate_hash != manifest.candidate_hash:
        raise ApplyError("plan 已过期：候选内容不匹配，请重新生成")


def preflight_writable(workspace: CanonicalWorkspace, manifest: PlanManifest) -> None:
    """Fail before backup/publish when any target is not writable/locked."""
    blocked: list[str] = []
    for relative, _ in manifest.targets:
        target = workspace.root / relative
        if target.exists() and not os.access(target, os.W_OK):
            blocked.append(str(target))
    if blocked:
        raise ApplyError(
            "目标文件不可写或正被占用（Excel/Office 打开？）: "
            + ", ".join(blocked)
            + "。请关闭占用程序后重试。"
        )


def _absolute(workspace: CanonicalWorkspace, relative: str) -> Path:
    return (workspace.root / relative).resolve()


def _backup_dir(workspace: CanonicalWorkspace, plan_id: str) -> Path:
    return workspace.resolve("cache_dir") / "backups" / plan_id


def apply_plan(
    workspace: CanonicalWorkspace,
    plan_id: str,
    *,
    base_revision: str,
    candidate_hash: str,
) -> dict[str, Any]:
    """Publish a validated plan using journal + backup + os.replace."""
    manifest = load_plan(workspace, plan_id)
    if manifest is None:
        raise ApplyError(f"plan '{plan_id}' 不存在或已清理")
    validate_plan_stale(workspace, manifest, base_revision=base_revision, candidate_hash=candidate_hash)

    with WorkspaceApplyLock(workspace):
        validate_plan_stale(workspace, manifest, base_revision=base_revision, candidate_hash=candidate_hash)
        preflight_writable(workspace, manifest)
        journal_path = _journal_path(workspace)
        backup = _backup_dir(workspace, plan_id)
        backup.mkdir(parents=True, exist_ok=True)

        journal: dict[str, Any] = {
            "format": JOURNAL_FORMAT,
            "plan_id": plan_id,
            "phase": "backup",
            "targets": list(manifest.targets),
        }
        journal_path.write_text(json.dumps(journal, sort_keys=True), encoding="utf-8")

        # backup existing targets
        for relative, _ in manifest.targets:
            absolute = _absolute(workspace, relative)
            if absolute.exists():
                destination = backup / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(absolute, destination)

        journal["phase"] = "publish"
        journal_path.write_text(json.dumps(journal, sort_keys=True), encoding="utf-8")

        # stepwise os.replace from staging to targets
        published: list[str] = []
        for relative, staging_relative in manifest.targets:
            staged = manifest.staging_dir / staging_relative
            if not staged.exists():
                raise ApplyError(f"staging 缺少文件: {staged}")
            absolute = _absolute(workspace, relative)
            absolute.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, absolute)
            published.append(relative)
            journal["published"] = published
            journal_path.write_text(json.dumps(journal, sort_keys=True), encoding="utf-8")

        journal["phase"] = "committed"
        journal_path.write_text(json.dumps(journal, sort_keys=True), encoding="utf-8")
        journal_path.unlink(missing_ok=True)
        shutil.rmtree(manifest.staging_dir, ignore_errors=True)
        ( _plans_dir(workspace) / f"{plan_id}.json").unlink(missing_ok=True)
        return {"plan_id": plan_id, "published": published}


def recover(workspace: CanonicalWorkspace) -> list[str]:
    """Recover an interrupted apply to a complete old or new revision."""
    journal_path = _journal_path(workspace)
    if not journal_path.exists():
        return []
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # unreadable journal: keep backup and finish from it if possible
        return ["journal 无法解析，需要人工检查"]
    if journal.get("format") != JOURNAL_FORMAT:
        return ["journal 格式不兼容，需要人工检查"]

    plan_id = journal["plan_id"]
    backup = _backup_dir(workspace, plan_id)
    phase = journal.get("phase")
    reported: list[str] = []

    if phase in ("backup", "publish"):
        # roll back to the complete old revision (restore backups)
        for relative, _ in journal.get("targets", []):
            absolute = _absolute(workspace, relative)
            saved = backup / relative
            if saved.exists():
                absolute.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, absolute)
        reported.append(f"recovered to old revision (plan {plan_id})")
    elif phase == "committed":
        # finish publish by restoring any not-yet-published staged files
        for relative, staging_relative in journal.get("targets", []):
            staged = _staging_for(workspace) / plan_id / staging_relative
            if staged.exists():
                absolute = _absolute(workspace, relative)
                absolute.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, absolute)
        reported.append(f"completed publish to new revision (plan {plan_id})")

    journal_path.unlink(missing_ok=True)
    shutil.rmtree(backup, ignore_errors=True)
    return reported


def stage_candidate_yaml(manifest: PlanManifest, resources: list) -> None:
    """Write canonical candidate YAML into the plan staging dir (app layer)."""
    import yaml

    from ct.schema.resources import TableResource, resource_to_data

    for resource in resources:
        directory = "config/schemas" if isinstance(resource, TableResource) else "config/types"
        target = manifest.staging_dir / f"{resource.name}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(
                resource_to_data(resource), allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
