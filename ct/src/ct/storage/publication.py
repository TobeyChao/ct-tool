"""可恢复的多文件发布：版本化 journal + 同卷暂存 + 备份预检 + 幂等恢复。

语义（design 决策 4）：

- 发布范围覆盖本次 ``output`` 文件、导出产生的 layout manifest，以及全量导出
  应删除的陈旧文件；删除与替换在**同一个事务**里可恢复。
- 只有全部生成与结构检查通过后，调用方才开始 publish。
- 目标新内容在**目标所在文件系统**的临时文件里准备，保证最终 ``os.replace``
  不跨卷（``cache_dir`` / ``output_dir`` / ``excel_dir`` 允许不同卷）。
- journal 固定在 ``<root>/.ct/export-publication.json``，不随 ``cache_dir`` 变化；
  锁与恢复记录因此不会失联。
- 状态机：``prepared`` → ``backed_up`` → ``publishing`` → ``committed``。
  **备份未全部完成绝不改写正式目标。**
- 恢复幂等：``committed`` 之前恢复旧集合（含删除本次新建文件），之后只做清理。
- journal 损坏 / 格式未知 / 记录路径越界 → 报错并**保留材料**，拒绝继续发布。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from ct.storage.files import atomic_write, normalize, sha256_bytes, sha256_file

JOURNAL_FORMAT = "export-publication/1"
JOURNAL_NAME = "export-publication.json"
PRIVATE_DIRNAME = ".ct"

PHASE_PREPARED = "prepared"
PHASE_BACKED_UP = "backed_up"
PHASE_PUBLISHING = "publishing"
PHASE_COMMITTED = "committed"

OP_REPLACE = "replace"
OP_CREATE = "create"
OP_DELETE = "delete"


class PublicationError(RuntimeError):
    """发布或恢复无法安全继续。

    出现它时**恢复材料必须保留**，并且后续 export/deploy 要被拒绝，直到人工
    或下一次显式恢复处理完现场。
    """


@dataclass
class PublicationEntry:
    """一个发布目标：正式路径 + 旧/新内容身份 + 备份与暂存引用。"""

    path: str
    op: str
    existed: bool
    old_hash: str | None = None
    new_hash: str | None = None
    staged: str | None = None
    backup: str | None = None
    done: bool = False

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "op": self.op,
            "existed": self.existed,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "staged": self.staged,
            "backup": self.backup,
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PublicationEntry":
        return cls(
            path=str(data["path"]),
            op=str(data["op"]),
            existed=bool(data.get("existed", False)),
            old_hash=data.get("old_hash"),
            new_hash=data.get("new_hash"),
            staged=data.get("staged"),
            backup=data.get("backup"),
            done=bool(data.get("done", False)),
        )


@dataclass
class PublicationJournal:
    operation_id: str
    root: str
    phase: str
    allowed_dirs: list[str]
    entries: list[PublicationEntry] = field(default_factory=list)
    format: str = JOURNAL_FORMAT

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "operation_id": self.operation_id,
            "root": self.root,
            "phase": self.phase,
            "allowed_dirs": list(self.allowed_dirs),
            "entries": [entry.to_dict() for entry in self.entries],
        }


class FilePublisher:
    """把一批 payload 与删除操作可恢复地发布到正式路径。"""

    def __init__(self, root: Path) -> None:
        self.root = normalize(Path(root))
        self.private_dir = self.root / PRIVATE_DIRNAME
        self.journal_path = self.private_dir / JOURNAL_NAME

    # ------------------------------------------------------------- journal I/O

    def read_journal(self) -> PublicationJournal | None:
        """读取恢复记录；损坏或格式未知一律报错并保留材料。"""
        if not self.journal_path.exists():
            return None
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PublicationError(
                f"发布恢复记录损坏，已保留材料并拒绝继续：{self.journal_path}（{exc}）"
            ) from exc
        if not isinstance(data, dict) or data.get("format") != JOURNAL_FORMAT:
            raise PublicationError(
                f"发布恢复记录格式未知，已保留材料并拒绝继续：{self.journal_path}"
                f"（需要 {JOURNAL_FORMAT}）"
            )
        try:
            journal = PublicationJournal(
                operation_id=str(data["operation_id"]),
                root=str(data["root"]),
                phase=str(data["phase"]),
                allowed_dirs=[str(item) for item in data["allowed_dirs"]],
                entries=[PublicationEntry.from_dict(item) for item in data["entries"]],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationError(
                f"发布恢复记录损坏，已保留材料并拒绝继续：{self.journal_path}（{exc}）"
            ) from exc
        self._validate(journal)
        return journal

    def _validate(self, journal: PublicationJournal) -> None:
        """记录里的每个路径都必须落在本次操作声明的允许目录内。"""
        allowed = [Path(item) for item in journal.allowed_dirs]
        for entry in journal.entries:
            target = Path(entry.path)
            if not any(target == base or base in target.parents for base in allowed):
                raise PublicationError(
                    f"发布恢复记录包含越界路径，已保留材料并拒绝继续：{target}"
                )

    def _write_journal(self, journal: PublicationJournal) -> None:
        self.private_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            journal.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
        ).encode("utf-8")
        # 写 journal 本身也走 临时文件 + replace
        atomic_write(self.journal_path, payload)

    # ------------------------------------------------------------------ publish

    def publish(
        self,
        payloads: Mapping[Path, bytes],
        deletions: Iterable[Path] = (),
    ) -> None:
        """发布 payload 与删除操作；任一步失败即回滚到发布前状态。"""
        targets: dict[Path, bytes] = {normalize(p): data for p, data in payloads.items()}
        removals = [normalize(p) for p in deletions]
        if not targets and not removals:
            return

        # 先处理上一次未完成的发布，避免叠加
        self.recover()

        operation_id = uuid.uuid4().hex
        allowed_dirs = sorted(
            {str(path.parent) for path in [*targets, *removals]}
        )
        entries: list[PublicationEntry] = []
        staging: list[Path] = []

        try:
            for path, data in targets.items():
                staged = self._stage(path, data, operation_id)
                staging.append(staged)
                entries.append(
                    PublicationEntry(
                        path=str(path),
                        op=OP_REPLACE if path.is_file() else OP_CREATE,
                        existed=path.is_file(),
                        old_hash=sha256_file(path) if path.is_file() else None,
                        new_hash=sha256_bytes(data),
                        staged=str(staged),
                    )
                )
            for path in removals:
                if not path.is_file():
                    continue
                entries.append(
                    PublicationEntry(
                        path=str(path),
                        op=OP_DELETE,
                        existed=True,
                        old_hash=sha256_file(path),
                        new_hash=None,
                    )
                )

            journal = PublicationJournal(
                operation_id=operation_id,
                root=str(self.root),
                phase=PHASE_PREPARED,
                allowed_dirs=allowed_dirs,
                entries=entries,
            )
            # prepared：完整目标清单已落 journal，正式文件尚未改动
            self._write_journal(journal)

            # backed_up：每个原文件备份完成且 hash 校验通过之前，绝不改写正式目标
            backup_dir = self.private_dir / "backup" / operation_id
            for entry in entries:
                if entry.old_hash is None:
                    entry.backup = None
                    continue
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"{len(entry.path)}-{Path(entry.path).name}"
                shutil.copy2(entry.path, backup)
                if sha256_file(backup) != entry.old_hash:
                    raise PublicationError(
                        f"备份校验失败，未改写任何正式文件：{entry.path}"
                    )
                entry.backup = str(backup)
            journal.phase = PHASE_BACKED_UP
            self._write_journal(journal)

            # publishing：逐文件替换/删除，进度写入 journal（崩溃后可回滚）
            journal.phase = PHASE_PUBLISHING
            self._write_journal(journal)
            for entry in entries:
                self._apply(entry)
                entry.done = True
                self._write_journal(journal)

            # committed：先原子记录提交点，再清理材料
            journal.phase = PHASE_COMMITTED
            self._write_journal(journal)
            self._cleanup(journal)
        except BaseException:
            self._rollback(staging)
            raise

    def _stage(self, target: Path, data: bytes, operation_id: str) -> Path:
        """在**目标所在目录**准备新内容 ⇒ 最终 replace 不跨卷。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".ct-stage-")
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        return Path(temporary)

    def _apply(self, entry: PublicationEntry) -> None:
        target = Path(entry.path)
        if entry.op == OP_DELETE:
            target.unlink(missing_ok=True)
            return
        staged = Path(entry.staged or "")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)

    # ----------------------------------------------------------------- recover

    def recover(self) -> str | None:
        """幂等恢复未完成的发布。返回一句描述；没有待恢复记录时返回 None。"""
        journal = self.read_journal()
        if journal is None:
            return None
        if journal.phase == PHASE_PREPARED:
            # 备份尚未完成 ⇒ 正式文件不可能被改动，只清理私有资源
            self._cleanup(journal)
            return "上次发布尚未完成备份，仅清理私有材料"
        if journal.phase == PHASE_COMMITTED:
            # 已提交：只完成清理，不回滚完整的新版本
            self._cleanup(journal)
            return "上次发布已提交，仅清理恢复材料"
        self._restore(journal)
        self._cleanup(journal)
        return f"已回滚未完成的发布（{journal.operation_id}）"

    def _restore(self, journal: PublicationJournal) -> None:
        """把正式文件恢复到发布前集合（内容与 mtime），并移除本次新建文件。"""
        for entry in journal.entries:
            target = Path(entry.path)
            if entry.existed:
                if not entry.backup:
                    # 备份尚未产生：正式文件可能还没被改，也可能已改但未记备份。
                    # 无法安全推断 ⇒ 保留材料并报错，不静默跳过。
                    raise PublicationError(
                        f"无法恢复：{entry.path} 缺少备份，已保留恢复材料"
                    )
                backup = Path(entry.backup)
                if not backup.is_file():
                    raise PublicationError(
                        f"无法恢复：备份缺失 {backup}，已保留恢复材料"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
            else:
                # 本次新建的目标：回滚时删除
                target.unlink(missing_ok=True)

    def _cleanup(self, journal: PublicationJournal) -> None:
        for entry in journal.entries:
            if entry.staged:
                Path(entry.staged).unlink(missing_ok=True)
            if entry.backup:
                Path(entry.backup).unlink(missing_ok=True)
        shutil.rmtree(self.private_dir / "backup" / journal.operation_id, ignore_errors=True)
        self.journal_path.unlink(missing_ok=True)

    def _rollback(self, staging: list[Path]) -> None:
        """本次 publish 抛错时：回滚已改动的正式文件并清理暂存。

        ``prepared`` 阶段（备份未完成）正式文件不可能被改动，只清理私有资源；
        备份完成后才开始逐文件替换，那时才需要真正回滚。
        """
        for path in staging:
            path.unlink(missing_ok=True)
        try:
            journal = self.read_journal()
        except PublicationError:
            return  # 记录已损坏：保留材料，交给调用方报错
        if journal is None:
            return
        if journal.phase in (PHASE_BACKED_UP, PHASE_PUBLISHING):
            self._restore(journal)
        self._cleanup(journal)
