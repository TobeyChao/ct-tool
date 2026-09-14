"""Shared workspace transaction entry: one lock, then recovery, then control.

Schema save, export and deploy all mutate the same workspace, so they have to
share one exclusive lock and one recovery step, and they have to report the
same "workspace is busy" behaviour. Recovery runs *before* the caller loads any
configuration: ``global.yaml`` may have been edited into an unparseable state
while an interrupted publication still has to be rolled back first.

The entry point lives in the storage layer so the Schema use case can reuse it
without depending on export business code. Each use case calls it exactly once,
so a single request never nests the lock (the lock is not re-entrant).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ct.contracts import NullReporter, ProgressReporter
from ct.storage.publication import FilePublisher
from ct.storage.workspace_lock import WorkspaceBusyError, WorkspaceLock

__all__ = ["WorkspaceBusyError", "workspace_transaction"]


@contextmanager
def workspace_transaction(
    root: Path,
    reporter: ProgressReporter | None = None,
) -> Iterator[str | None]:
    """Hold the workspace lock, recover an interrupted publish, then yield.

    Yields the recovery description (``None`` when there was nothing to recover)
    so callers can surface it without reading the journal a second time. The
    lock is released on exit, including when the body raises.
    """
    reporter = reporter or NullReporter()
    with WorkspaceLock(root):
        recovery = FilePublisher(root).recover()
        if recovery:
            reporter.log(f"[发布恢复] {recovery}")
        yield recovery
