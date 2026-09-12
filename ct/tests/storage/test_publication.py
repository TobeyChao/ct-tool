"""可恢复文件发布：journal、同卷暂存、备份预检、幂等恢复、损坏与越界拒绝。"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from ct.storage import publication as pub
from ct.storage.publication import (
    JOURNAL_FORMAT,
    PHASE_BACKED_UP,
    PHASE_COMMITTED,
    PHASE_PREPARED,
    PHASE_PUBLISHING,
    FilePublisher,
    PublicationError,
)


def _seed(root: Path) -> dict[str, Path]:
    """建一个已有产物的工作区，返回逻辑名 → 路径。"""
    (root / "output" / "json").mkdir(parents=True, exist_ok=True)
    (root / "output" / "binary").mkdir(parents=True, exist_ok=True)
    files = {
        "a": root / "output" / "json" / "a.json",
        "b": root / "output" / "json" / "b.json",
        "bundle": root / "output" / "binary" / "data_zh.bin",
    }
    files["a"].write_bytes(b"old-a")
    files["b"].write_bytes(b"old-b")
    files["bundle"].write_bytes(b"old-bundle")
    # 稳定 mtime，便于断言回滚恢复了元信息
    for index, path in enumerate(files.values()):
        stamp = 1_600_000_000_000_000_000 + index
        os.utime(path, ns=(stamp, stamp))
    return files


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file() and ".ct" not in p.relative_to(root).parts
    }


# --------------------------------------------------------------------- 4.1


def test_publish_applies_payloads_and_deletions(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    files = _seed(root)
    publisher = FilePublisher(root)

    publisher.publish(
        {files["a"]: b"new-a", root / "output" / "json" / "c.json": b"new-c"},
        deletions=[files["b"]],
    )

    assert files["a"].read_bytes() == b"new-a"
    assert not files["b"].exists(), "删除项应被移除"
    assert (root / "output" / "json" / "c.json").read_bytes() == b"new-c"
    assert files["bundle"].read_bytes() == b"old-bundle", "未涉及的文件不得改动"
    assert not publisher.journal_path.exists(), "成功提交后不留下恢复记录"


def test_journal_path_does_not_depend_on_cache_dir(tmp_path: Path) -> None:
    """journal 固定在 <root>/.ct/，改 cache_dir 后仍能找到原恢复记录。"""
    root = tmp_path / "gd"
    _seed(root)
    publisher = FilePublisher(root)

    assert publisher.journal_path == root / ".ct" / "export-publication.json"

    def boom(*args, **kwargs):
        raise RuntimeError("注入：发布中途失败")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pub, "PHASE_PUBLISHING", PHASE_PUBLISHING)
        patch.setattr(FilePublisher, "_apply", boom)
        patch.setattr(FilePublisher, "_rollback", lambda self, staging: None)
        patch.setattr(FilePublisher, "_cleanup", lambda self, journal: None)
        with pytest.raises(RuntimeError):
            publisher.publish({root / "output" / "json" / "a.json": b"x"})

    # cache_dir 指向别处也照样找得到
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "global.yaml").write_text(
        "primary_lang: zh\ncache_dir: elsewhere\n", encoding="utf-8"
    )
    other = FilePublisher(root)
    assert other.journal_path == root / ".ct" / "export-publication.json"
    assert other.read_journal() is not None


def test_staging_happens_on_the_target_volume(tmp_path: Path) -> None:
    """最终 replace 的源必须与目标同目录（不跨卷）。"""
    root = tmp_path / "gd"
    _seed(root)
    seen: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "replace", spy)
        FilePublisher(root).publish(
            {root / "output" / "json" / "a.json": b"new-a"}
        )

    assert seen, "应当发生一次 replace"
    for src, dst in seen:
        assert src.parent == dst.parent, f"暂存与目标不同目录：{src} -> {dst}"


def test_backup_failure_never_touches_formal_files(tmp_path: Path) -> None:
    """备份中途失败：正式文件内容与 mtime 全部不变。"""
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)

    real_copy2 = shutil.copy2
    calls = {"count": 0}

    def flaky(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("注入：备份中途失败")
        return real_copy2(src, dst, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(shutil, "copy2", flaky)
        with pytest.raises(OSError):
            FilePublisher(root).publish(
                {files["a"]: b"new-a", files["b"]: b"new-b"}
            )

    assert _snapshot(root) == before, "备份未完成时不得改写任何正式文件"


# --------------------------------------------------------------------- 4.2


def test_crash_after_first_replace_restores_everything(tmp_path: Path) -> None:
    """替换了一个文件后崩溃（未记录进度）：恢复原内容、mtime，并删除新建文件。"""
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)
    created = root / "output" / "json" / "created.json"

    real_apply = FilePublisher._apply
    applied = {"count": 0}

    def flaky_apply(self, entry):
        real_apply(self, entry)
        applied["count"] += 1
        if applied["count"] == 1:
            raise RuntimeError("注入：第一个文件替换后进程崩溃")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FilePublisher, "_apply", flaky_apply)
        # 模拟进程直接死亡：不走 except 的自动回滚
        patch.setattr(FilePublisher, "_rollback", lambda self, staging: None)
        with pytest.raises(RuntimeError):
            FilePublisher(root).publish(
                {files["a"]: b"new-a", files["b"]: b"new-b", created: b"new-c"}
            )

    # 现场仍在：journal 处于 publishing
    journal = FilePublisher(root).read_journal()
    assert journal is not None and journal.phase == PHASE_PUBLISHING

    message = FilePublisher(root).recover()
    assert message and "回滚" in message
    assert _snapshot(root) == before, "恢复后必须与发布前完全一致（含 mtime）"
    assert not created.exists(), "本次新建的文件必须被移除"
    assert not FilePublisher(root).journal_path.exists()


def test_crash_during_deletion_restores_deleted_files(tmp_path: Path) -> None:
    """全量删除中途崩溃：下次恢复要把已删产物找回来。"""
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)

    real_apply = FilePublisher._apply
    applied = {"count": 0}

    def flaky_apply(self, entry):
        real_apply(self, entry)
        applied["count"] += 1
        if applied["count"] == 1:
            raise RuntimeError("注入：删除中断")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FilePublisher, "_apply", flaky_apply)
        patch.setattr(FilePublisher, "_rollback", lambda self, staging: None)
        with pytest.raises(RuntimeError):
            FilePublisher(root).publish({}, deletions=[files["a"], files["b"]])

    assert not files["a"].exists(), "第一个删除应已生效"
    FilePublisher(root).recover()
    assert _snapshot(root) == before, "恢复后被删文件必须回来"


def test_committed_journal_is_only_cleaned_up(tmp_path: Path) -> None:
    """已提交：恢复保留完整新产物，只清理材料。"""
    root = tmp_path / "gd"
    files = _seed(root)
    publisher = FilePublisher(root)
    publisher.publish({files["a"]: b"new-a"})

    # 伪造一个「已提交但未清理」的现场
    backup = root / ".ct" / "backup" / "op1" / "a.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(b"old-a")
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op1",
                "root": str(root),
                "phase": PHASE_COMMITTED,
                "allowed_dirs": [str((root / "output" / "json").resolve())],
                "entries": [
                    {
                        "path": str(files["a"]),
                        "op": "replace",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": "y",
                        "staged": None,
                        "backup": str(backup),
                        "done": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    message = publisher.recover()
    assert message and "已提交" in message
    assert files["a"].read_bytes() == b"new-a", "已提交的新产物不得回滚"
    assert not publisher.journal_path.exists()
    assert not backup.exists()


# --------------------------------------------------------------------- 4.3


def test_recovery_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FilePublisher, "_apply", lambda self, entry: (_ for _ in ()).throw(RuntimeError("崩")))
        patch.setattr(FilePublisher, "_rollback", lambda self, staging: None)
        with pytest.raises(RuntimeError):
            FilePublisher(root).publish({files["a"]: b"new-a"})

    publisher = FilePublisher(root)
    publisher.recover()
    assert _snapshot(root) == before
    # 再恢复一次：无记录，安全返回
    assert publisher.recover() is None
    assert _snapshot(root) == before


def test_recover_without_journal_is_a_noop(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    _seed(root)
    assert FilePublisher(root).recover() is None


def test_subprocess_crash_leaves_recoverable_journal(tmp_path: Path) -> None:
    """真正的子进程被杀：正式文件与恢复材料都要留下来给下一次恢复。"""
    import subprocess
    import sys
    import textwrap

    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)

    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(Path(__file__).parents[2] / "src")!r})
        from pathlib import Path
        from ct.storage.publication import FilePublisher

        root = Path({str(root)!r})
        publisher = FilePublisher(root)

        def die(self, entry):
            # 第一个文件替换完成后立刻 _exit，模拟没有任何清理机会的崩溃
            target = Path(entry.path)
            if entry.op == "delete":
                target.unlink(missing_ok=True)
            else:
                os.replace(entry.staged, target)
            os._exit(9)

        FilePublisher._apply = die
        publisher.publish({{root / "output" / "json" / "a.json": b"new-a"}})
        """
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 9, proc.stderr

    publisher = FilePublisher(root)
    assert publisher.journal_path.exists(), "崩溃后必须留下恢复记录"
    message = publisher.recover()
    assert message and "回滚" in message
    assert _snapshot(root) == before


# --------------------------------------------------------------------- 4.4


def test_corrupt_journal_is_refused_and_materials_kept(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    _seed(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text("{ 这不是 JSON", encoding="utf-8")

    with pytest.raises(PublicationError) as excinfo:
        publisher.read_journal()
    assert "损坏" in str(excinfo.value)
    assert publisher.journal_path.exists(), "不得静默删除恢复材料"


def test_unknown_journal_format_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "gd"
    _seed(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps({"format": "export-publication/99", "entries": []}), encoding="utf-8"
    )

    with pytest.raises(PublicationError) as excinfo:
        publisher.read_journal()
    assert "格式未知" in str(excinfo.value)
    assert publisher.journal_path.exists()


def test_journal_path_escape_is_refused(tmp_path: Path) -> None:
    """记录里出现允许目录之外的路径 ⇒ 拒绝，且保留材料。"""
    root = tmp_path / "gd"
    _seed(root)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op",
                "root": str(root),
                "phase": PHASE_PUBLISHING,
                "allowed_dirs": [str((root / "output" / "json").resolve())],
                "entries": [
                    {
                        "path": str(outside),
                        "op": "delete",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": None,
                        "staged": None,
                        "backup": None,
                        "done": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PublicationError) as excinfo:
        publisher.read_journal()
    assert "越界" in str(excinfo.value)
    assert outside.exists(), "越界路径不得被触碰"
    assert publisher.journal_path.exists()


def test_missing_backup_refuses_to_skip(tmp_path: Path) -> None:
    """备份缺失时不得静默跳过恢复。"""
    root = tmp_path / "gd"
    files = _seed(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op",
                "root": str(root),
                "phase": PHASE_PUBLISHING,
                "allowed_dirs": [str((root / "output" / "json").resolve())],
                "entries": [
                    {
                        "path": str(files["a"]),
                        "op": "replace",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": "y",
                        "staged": None,
                        "backup": str(root / ".ct" / "backup" / "nope" / "a.json"),
                        "done": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PublicationError) as excinfo:
        publisher.recover()
    assert "缺少备份" in str(excinfo.value) or "备份缺失" in str(excinfo.value)
    assert publisher.journal_path.exists()


def test_prepared_phase_only_cleans_private_materials(tmp_path: Path) -> None:
    """prepared（备份未完成）时正式文件不可能被改动，恢复只清理私有资源。"""
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op",
                "root": str(root),
                "phase": PHASE_PREPARED,
                "allowed_dirs": [str((root / "output" / "json").resolve())],
                "entries": [
                    {
                        "path": str(files["a"]),
                        "op": "replace",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": "y",
                        "staged": None,
                        "backup": None,
                        "done": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    message = publisher.recover()
    assert message and "清理" in message
    assert _snapshot(root) == before
    assert not publisher.journal_path.exists()


def test_backed_up_phase_rolls_back(tmp_path: Path) -> None:
    """backed_up（备份齐全、尚未替换）也能安全回滚。"""
    root = tmp_path / "gd"
    files = _seed(root)
    before = _snapshot(root)
    publisher = FilePublisher(root)
    backup_dir = root / ".ct" / "backup" / "op"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "a.json"
    shutil.copy2(files["a"], backup)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op",
                "root": str(root),
                "phase": PHASE_BACKED_UP,
                "allowed_dirs": [str((root / "output" / "json").resolve())],
                "entries": [
                    {
                        "path": str(files["a"]),
                        "op": "replace",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": "y",
                        "staged": None,
                        "backup": str(backup),
                        "done": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    publisher.recover()
    assert _snapshot(root) == before
