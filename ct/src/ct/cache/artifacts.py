"""Content-addressed cache for pure export generators.

Keys include the generator version and all effective inputs. Cached payloads
are checksummed and never deserialized as executable objects. Publication is
atomic; an interrupted run can only leave independently reusable artifacts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

T = TypeVar("T", str, bytes)


def _input(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _input(value.model_dump(mode="json"))
    if is_dataclass(value):
        return {f.name: _input(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(k): _input(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_input(v) for v in value]
    return value


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ct-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ArtifactCache:
    def __init__(self, directory: Path, *, version: str, forced: bool = False):
        self.directory = directory / "artifacts"
        self.version = version
        self.forced = forced
        self.hits = 0
        self.misses = 0
        self.used: set[Path] = set()

    def call(self, name: str, generate: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        key = json.dumps(
            [self.version, name, _input(args), _input(kwargs)],
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        path = self.directory / name / (hashlib.sha256(key).hexdigest() + ".json")
        self.used.add(path)
        if not self.forced:
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                payload = base64.b64decode(entry["payload"], validate=True)
                if entry["sha256"] == hashlib.sha256(payload).hexdigest():
                    if entry["kind"] == "text":
                        result = payload.decode("utf-8")
                    elif entry["kind"] == "bytes":
                        result = payload
                    else:
                        raise ValueError("Unknown artifact type")
                    self.hits += 1
                    return result
            except (OSError, ValueError, KeyError, TypeError):
                pass
        result = generate(*args, **kwargs)
        payload = result.encode("utf-8") if isinstance(result, str) else result
        entry = {
            "kind": "text" if isinstance(result, str) else "bytes",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "payload": base64.b64encode(payload).decode("ascii"),
        }
        atomic_write(path, json.dumps(entry).encode("utf-8"))
        self.misses += 1
        return result

    def prune(self) -> None:
        """Drop obsolete entries only after an unfiltered successful export."""
        for path in self.directory.glob("*/*.json"):
            if path not in self.used:
                path.unlink(missing_ok=True)
