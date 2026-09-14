"""Shared workspace transaction entry (task 2.1).

Every writer of one workspace — Schema save, export, deploy — must take the same
lock, recover an interrupted publish before loading configuration, and report the
same busy error. These tests pin that contract.
"""

from __future__ import annotations

import json

import pytest

from ct.storage.publication import FilePublisher, JOURNAL_FORMAT
from ct.storage.workspace_lock import WorkspaceBusyError, WorkspaceLock
from ct.storage.workspace_transaction import workspace_transaction


class _Reporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, message: str) -> None:
        self.lines.append(message)


def _write_prepared_journal(root) -> None:
    """A journal whose backup never completed: recovery only cleans private state."""
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text(
        json.dumps(
            {
                "format": JOURNAL_FORMAT,
                "operation_id": "op-1",
                "root": str(root),
                "phase": "prepared",
                "allowed_dirs": [str(root)],
                "entries": [],
            }
        ),
        encoding="utf-8",
    )


def test_transaction_recovers_before_yielding(tmp_path) -> None:
    root = tmp_path / "gd"
    root.mkdir()
    _write_prepared_journal(root)
    reporter = _Reporter()

    with workspace_transaction(root, reporter) as recovery:
        assert recovery is not None
        assert not FilePublisher(root).journal_path.exists()

    assert reporter.lines and "发布恢复" in reporter.lines[0]


def test_transaction_reports_nothing_when_clean(tmp_path) -> None:
    root = tmp_path / "gd"
    root.mkdir()
    reporter = _Reporter()
    with workspace_transaction(root, reporter) as recovery:
        assert recovery is None
    assert reporter.lines == []


def test_transaction_holds_the_shared_lock_and_never_nests(tmp_path) -> None:
    root = tmp_path / "gd"
    root.mkdir()
    with workspace_transaction(root):
        # Another writer (export/deploy/save) must see the workspace as busy...
        with pytest.raises(WorkspaceBusyError):
            with workspace_transaction(root):
                pass
        # ...and so must a bare lock acquisition.
        with pytest.raises(WorkspaceBusyError):
            WorkspaceLock(root).acquire()
    # Released on exit: the next writer proceeds.
    with workspace_transaction(root) as recovery:
        assert recovery is None


def test_transaction_releases_lock_when_body_raises(tmp_path) -> None:
    root = tmp_path / "gd"
    root.mkdir()
    with pytest.raises(RuntimeError):
        with workspace_transaction(root):
            raise RuntimeError("boom")
    with workspace_transaction(root):
        pass


def test_busy_message_covers_save_export_and_deploy(tmp_path) -> None:
    root = tmp_path / "gd"
    root.mkdir()
    with workspace_transaction(root):
        with pytest.raises(WorkspaceBusyError) as excinfo:
            WorkspaceLock(root).acquire()
    message = str(excinfo.value)
    assert "保存" in message and "导出" in message and "部署" in message
