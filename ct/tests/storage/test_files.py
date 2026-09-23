"""Windows 单文件替换应允许文件观察者读取旧目标。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

import pytest

from ct.storage.files import atomic_write


@pytest.mark.skipif(sys.platform != "win32", reason="需要 Windows 错误码")
def test_atomic_write_replaces_target_while_reader_has_it_open(tmp_path: Path) -> None:
    target = tmp_path / "journal.json"
    target.write_bytes(b"old")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    reader = create_file(str(target), 0x80, 7, None, 3, 0, None)
    assert reader != ctypes.c_void_p(-1).value

    try:
        atomic_write(target, b"new")
        assert target.read_bytes() == b"new"
    finally:
        assert close_handle(reader)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["journal.json"]
