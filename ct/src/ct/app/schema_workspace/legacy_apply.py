"""One-time adapter for the recovery materials of the removed Apply pipeline.

The old ``schema_workspace/apply.py`` published YAML through its own lock and
journal (``<cache_dir>/apply.journal.json``). Those materials may still be on
disk when the YAML-only save ships, so switching the write path must first
resolve them:

* ``phase == committed`` — the new revision was fully published, only private
  cleanup is missing → finish the cleanup;
* ``phase in {backup, publish}`` — roll back to the complete old revision from
  the recorded backups, but only when every publish target has a backup;
* anything unreadable, unknown or incomplete — **block** new writes and keep
  every material on disk for manual inspection. Nothing here is ever deleted on
  a timer.

The adapter reads the legacy journal format directly and does not import the
removed module, so it keeps working after ``apply.py`` is deleted. The legacy
``apply.lock`` is deliberately ignored: its presence never means "busy" (the
old code used ``exists``/``write`` semantics, and a dead process leaves the file
behind).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ct.config import load_config

LEGACY_JOURNAL_FORMAT = "apply-journal/1"
LEGACY_JOURNAL_NAME = "apply.journal.json"
LEGACY_LOCK_NAME = "apply.lock"
LEGACY_BACKUP_DIRNAME = "backups"
LEGACY_PLANS_DIRNAME = "plans"
LEGACY_STAGING_DIRNAME = "staging"


class LegacyApplyBlocked(RuntimeError):
    """Legacy materials cannot be resolved reliably; keep them and stop writing."""

    def __init__(self, message: str, materials: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.materials = materials


@dataclass(frozen=True)
class LegacyApplyStatus:
    """What was found, what is preserved, and whether writing may continue."""

    journal_path: Path
    plan_id: str = ""
    phase: str = ""
    materials: tuple[str, ...] = ()
    blocked: bool = False
    recovered: bool = False
    reason: str = ""

    def to_payload(self) -> dict:
        return {
            "planId": self.plan_id,
            "phase": self.phase,
            "materials": list(self.materials),
            "blocked": self.blocked,
            "recovered": self.recovered,
            "reason": self.reason,
        }


def legacy_cache_dir(root: Path) -> Path:
    """Locate the cache directory, tolerating a currently unparseable config."""
    try:
        return Path(load_config(root).resolve("cache_dir"))
    except Exception:  # noqa: BLE001 - recovery must not depend on config health
        return Path(root) / "cache"


def _read_journal(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyApplyBlocked(
            f"旧 Apply 恢复记录无法解析，已保留材料并阻止写入：{path}（{exc}）"
        ) from exc
    if not isinstance(data, dict) or data.get("format") != LEGACY_JOURNAL_FORMAT:
        raise LegacyApplyBlocked(
            f"旧 Apply 恢复记录格式未知，已保留材料并阻止写入：{path}"
            f"（需要 {LEGACY_JOURNAL_FORMAT}）"
        )
    return data


def _materials(root: Path, cache_dir: Path, plan_id: str) -> tuple[str, ...]:
    found: list[Path] = [cache_dir / LEGACY_JOURNAL_NAME]
    if plan_id:
        found.append(cache_dir / LEGACY_BACKUP_DIRNAME / plan_id)
        found.append(cache_dir / LEGACY_PLANS_DIRNAME / f"{plan_id}.json")
        found.append(cache_dir / LEGACY_STAGING_DIRNAME / plan_id)
    lock = cache_dir / LEGACY_LOCK_NAME
    if lock.exists():
        found.append(lock)
    return tuple(str(path) for path in found if path.exists())


def _cleanup(cache_dir: Path, plan_id: str) -> None:
    shutil.rmtree(cache_dir / LEGACY_BACKUP_DIRNAME / plan_id, ignore_errors=True)
    shutil.rmtree(cache_dir / LEGACY_STAGING_DIRNAME / plan_id, ignore_errors=True)
    (cache_dir / LEGACY_PLANS_DIRNAME / f"{plan_id}.json").unlink(missing_ok=True)
    (cache_dir / LEGACY_JOURNAL_NAME).unlink(missing_ok=True)


def recover_legacy_apply(root: Path) -> LegacyApplyStatus | None:
    """Resolve leftover Apply materials; raise when they cannot be resolved.

    Callers run this inside the workspace transaction, before loading the
    workspace, so an interrupted legacy publish can never mix with a new save.
    Returns ``None`` when there is nothing to do.
    """
    root = Path(root)
    cache_dir = legacy_cache_dir(root)
    journal_path = cache_dir / LEGACY_JOURNAL_NAME
    if not journal_path.exists():
        return None

    data = _read_journal(journal_path)
    plan_id = str(data.get("plan_id", ""))
    phase = str(data.get("phase", ""))
    materials = _materials(root, cache_dir, plan_id)

    if phase == "committed":
        _cleanup(cache_dir, plan_id)
        return LegacyApplyStatus(
            journal_path=journal_path,
            plan_id=plan_id,
            phase=phase,
            materials=materials,
            recovered=True,
            reason="旧 Apply 事务已提交，仅清理遗留材料",
        )

    if phase not in {"backup", "publish"}:
        raise LegacyApplyBlocked(
            f"旧 Apply 恢复记录处于未知阶段 '{phase}'，已保留材料并阻止写入：{journal_path}",
            materials=materials,
        )

    # The old writer replaced a file BEFORE recording it in published.
    # A publish journal therefore requires backups for every target, including
    # the unrecorded last replacement. Missing backups are ambiguous (new file
    # or incomplete materials), so preserve the entire recovery set.
    targets = data.get("targets")
    if phase == "publish":
        if not isinstance(targets, list) or not targets or any(
            not isinstance(pair, list) or len(pair) != 2
            or not all(isinstance(value, str) and value for value in pair)
            or Path(pair[0]).is_absolute() or ".." in Path(pair[0]).parts
            for pair in targets
        ):
            raise LegacyApplyBlocked("旧 Apply 缺少可信完整 targets，已保留恢复材料", materials)
        published = [pair[0] for pair in targets]
    else:
        published = []  # backup phase has not touched live targets
    backups = cache_dir / LEGACY_BACKUP_DIRNAME / plan_id
    for relative in published:
        backup = backups / relative
        if not backup.is_file():
            raise LegacyApplyBlocked(
                "旧 Apply 事务缺少可还原的备份，已保留材料并阻止写入："
                f"{backup}（材料：{', '.join(materials)}）",
                materials=materials,
            )
    for relative in published:
        target = Path(root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backups / relative, target)
    _cleanup(cache_dir, plan_id)
    return LegacyApplyStatus(
        journal_path=journal_path,
        plan_id=plan_id,
        phase=phase,
        materials=materials,
        recovered=True,
        reason=f"旧 Apply 事务已回滚到保存前版本（{plan_id}）",
    )


def detect_legacy_apply_material(root: Path) -> LegacyApplyStatus | None:
    """Read-only inspection (used by tests and diagnostics; writes nothing)."""
    root = Path(root)
    cache_dir = legacy_cache_dir(root)
    journal_path = cache_dir / LEGACY_JOURNAL_NAME
    if not journal_path.exists():
        return None
    try:
        data = _read_journal(journal_path)
    except LegacyApplyBlocked as exc:
        return LegacyApplyStatus(
            journal_path=journal_path,
            materials=_materials(root, cache_dir, ""),
            blocked=True,
            reason=str(exc),
        )
    plan_id = str(data.get("plan_id", ""))
    phase = str(data.get("phase", ""))
    targets = data.get("targets") or []
    backups = cache_dir / LEGACY_BACKUP_DIRNAME / plan_id
    missing = [str(pair[0]) for pair in targets if not (backups / str(pair[0])).is_file()] if phase == "publish" else []
    if phase == "publish" and not targets:
        missing = ["完整 targets 记录"]
    return LegacyApplyStatus(
        journal_path=journal_path,
        plan_id=plan_id,
        phase=str(data.get("phase", "")),
        materials=_materials(root, cache_dir, plan_id),
        blocked=bool(missing),
        reason=(
            "缺少备份，无法可靠还原：" + ", ".join(missing) if missing else ""
        ),
    )
