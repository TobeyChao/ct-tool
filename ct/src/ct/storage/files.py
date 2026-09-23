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


def atomic_replace(source: str | Path, target: str | Path) -> None:
    """Atomically rename, including over a file opened by Windows file watchers."""
    if os.name != "nt":
        os.replace(source, target)
        return

    # MoveFileExW (used by os.replace) rejects replacement while a watcher has
    # the old target open. FileRenameInfoEx with POSIX semantics explicitly
    # permits that case and keeps existing handles bound to the old file.
    import ctypes
    from ctypes import wintypes

    class FileRenameInfoEx(ctypes.Structure):
        _fields_ = [
            ("flags", wintypes.DWORD),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    set_info = kernel32.SetFileInformationByHandle
    set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    set_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(str(source), 0x10000, 7, None, 3, 0, None)  # DELETE, share all
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = str(target).encode("utf-16-le")
        offset = FileRenameInfoEx.file_name.offset
        info = ctypes.create_string_buffer(offset + len(name) + 2)
        wintypes.DWORD.from_buffer(info, FileRenameInfoEx.flags.offset).value = 0x3
        wintypes.DWORD.from_buffer(info, FileRenameInfoEx.file_name_length.offset).value = len(name)
        ctypes.memmove(ctypes.addressof(info) + offset, name, len(name))
        if not set_info(handle, 22, info, len(info)):  # FileRenameInfoEx
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


def atomic_write(path: Path, payload: bytes) -> None:
    """同目录临时文件 + ``os.replace``：单文件替换是原子的。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".ct-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        atomic_replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
