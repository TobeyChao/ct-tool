"""Persistent task state for long-running plan/apply work.

Tasks survive module switches in the panel (the frontend TaskBar reads this
endpoint); failures carry actionable messages and links, not transient toasts.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


class TaskState:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    def start(self, kind: str, scope: str) -> str:
        task_id = uuid.uuid4().hex[:12]
        self._tasks[task_id] = {
            "id": task_id,
            "kind": kind,
            "scope": scope,
            "status": "running",
            "message": "",
            "started_at": time.time(),
        }
        return task_id

    def update(self, task_id: str, *, message: str = "", status: str = "running") -> None:
        if task_id in self._tasks:
            self._tasks[task_id].update(message=message, status=status)

    def fail(self, task_id: str, error: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].update(status="error", message=error)

    def snapshot(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(task) for task in self._tasks.values()),
            key=lambda task: task["started_at"],
            reverse=True,
        )


task_state = TaskState()
