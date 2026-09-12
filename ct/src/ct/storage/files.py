"""存储原语：单文件原子写、哈希与路径规范化。

放在 ``ct.storage`` 而不是 ``ct.cache``：缓存与发布协议互不依赖，但两者都需要
同一个原子写实现，所以由存储层提供、缓存层复用。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def normalize(path: Path) -> Path:
    """规范化路径：解析符号链接/相对段并统一大小写，用于身份比较与白名单。"""
    return Path(os.path.normcase(str(Path(path).resolve())))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    """同目录临时文件 + ``os.replace``：单文件替换是原子的。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ct-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
