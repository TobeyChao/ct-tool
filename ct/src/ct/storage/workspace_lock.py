"""同一规范化工作区的进程间排他锁（export / deploy 互斥）。

要点（design 决策 5）：

- 锁文件固定在 ``<root>/.ct/export.lock``，**不随 cache_dir 变化**，否则换个
  缓存目录就会各锁各的、失去互斥。
- 使用系统 advisory lock（POSIX ``flock`` / Windows 文件区间锁）**加**进程内
  互斥，而不是 ``exists → write``：文件存在不等于锁被占用，进程死亡由系统
  自动释放，不会留下永久阻塞的残余锁。
- 冲突立即返回可呈现的 busy 错误，不静默排队。不同 root 各自独立、可以并行。
- 本轮只协调 export/deploy；Schema Apply、模板、i18n 编辑与外部编辑不在此列。
"""

from __future__ import annotations

import threading
from pathlib import Path

from ct.storage.files import normalize

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

LOCK_NAME = "export.lock"
PRIVATE_DIRNAME = ".ct"


class WorkspaceBusyError(RuntimeError):
    """同一工作区已有 export/deploy 在执行。

    继承 ``RuntimeError``；CLI 会把它渲染成友好错误并以非零状态退出。
    """


def _try_advisory(handle) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if msvcrt is not None:  # pragma: no cover - Windows
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    raise RuntimeError("当前平台没有可用的 advisory lock 实现")


def _release_advisory(handle) -> None:
    if fcntl is not None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt is not None:  # pragma: no cover - Windows
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


_registry_guard = threading.Lock()
_registry: dict[str, threading.Lock] = {}


def _inprocess_lock(key: str) -> threading.Lock:
    with _registry_guard:
        return _registry.setdefault(key, threading.Lock())


class WorkspaceLock:
    """可在同一进程内与跨进程排他；用作上下文管理器。"""

    def __init__(self, root: Path) -> None:
        self.root = normalize(Path(root))
        self.path = self.root / PRIVATE_DIRNAME / LOCK_NAME
        self._key = str(self.root)
        self._inprocess = _inprocess_lock(self._key)
        self._handle = None

    # ---- 生命周期
    def acquire(self) -> "WorkspaceLock":
        if not self._inprocess.acquire(blocking=False):
            raise WorkspaceBusyError(
                f"工作区正在导出/部署，请稍后重试：{self.root}"
            )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")
        except OSError:
            self._inprocess.release()
            raise
        if not _try_advisory(handle):
            handle.close()
            self._inprocess.release()
            raise WorkspaceBusyError(
                f"工作区正在导出/部署，请稍后重试：{self.root}"
            )
        self._handle = handle
        return self

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            _release_advisory(handle)
            handle.close()
        if self._inprocess.locked():
            self._inprocess.release()

    @property
    def held(self) -> bool:
        return self._handle is not None

    def __enter__(self) -> "WorkspaceLock":
        return self.acquire()

    def __exit__(self, *exc_info) -> None:
        self.release()
