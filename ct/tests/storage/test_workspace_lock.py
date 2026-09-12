"""工作区排他锁：同工作区 busy、进程死亡可重入、不同工作区独立。"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ct.storage.workspace_lock import WorkspaceBusyError, WorkspaceLock


def _root(tmp_path: Path, name: str = "gd") -> Path:
    root = tmp_path / name
    (root / "config").mkdir(parents=True, exist_ok=True)
    return root


def test_lock_file_lives_under_ct_and_not_cache_dir(tmp_path: Path) -> None:
    root = _root(tmp_path)
    lock = WorkspaceLock(root)
    assert lock.path == root / ".ct" / "export.lock"

    # cache_dir 指向别处，锁文件位置不变
    (root / "config" / "global.yaml").write_text(
        "primary_lang: zh\ncache_dir: somewhere-else\n", encoding="utf-8"
    )
    assert WorkspaceLock(root).path == root / ".ct" / "export.lock"


def test_second_acquire_in_same_process_is_busy(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with WorkspaceLock(root):
        with pytest.raises(WorkspaceBusyError):
            WorkspaceLock(root).acquire()


def test_lock_is_released_after_context_exit(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with WorkspaceLock(root):
        pass
    with WorkspaceLock(root):
        pass  # 不抛错即已释放


def test_existing_lock_file_does_not_mean_locked(tmp_path: Path) -> None:
    """文件存在 ≠ 锁被占用（不能用 exists → write 判定）。"""
    root = _root(tmp_path)
    lock_path = root / ".ct" / "export.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(b"12345")

    with WorkspaceLock(root):
        pass


def test_different_workspaces_are_independent(tmp_path: Path) -> None:
    with WorkspaceLock(_root(tmp_path, "gd-a")):
        with WorkspaceLock(_root(tmp_path, "gd-b")):
            pass  # 不同 root 不应互斥


def _spawn_holder(root: Path, hold_seconds: float) -> subprocess.Popen:
    script = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).parents[2] / "src")!r})
        from pathlib import Path
        from ct.storage.workspace_lock import WorkspaceLock

        lock = WorkspaceLock(Path({str(root)!r}))
        lock.acquire()
        print("LOCKED", flush=True)
        time.sleep({hold_seconds})
        """
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_cross_process_conflict_is_busy(tmp_path: Path) -> None:
    root = _root(tmp_path)
    holder = _spawn_holder(root, hold_seconds=30)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "LOCKED"
        with pytest.raises(WorkspaceBusyError):
            WorkspaceLock(root).acquire()
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_process_death_releases_the_lock(tmp_path: Path) -> None:
    """持锁进程被杀后，新请求必须能拿到锁（不因残留文件永久阻塞）。"""
    root = _root(tmp_path)
    holder = _spawn_holder(root, hold_seconds=30)
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "LOCKED"

    # 持锁期间确实互斥
    with pytest.raises(WorkspaceBusyError):
        WorkspaceLock(root).acquire()

    holder.kill()
    holder.wait(timeout=10)

    with WorkspaceLock(root):
        pass
    # 文件仍在，但锁已由系统释放
    assert (root / ".ct" / "export.lock").exists()
