import os

from ct.export.flatc_runner import _normalize_generated_line_endings


def _write(tmp_path, content: bytes):
    path = tmp_path / "out.h"
    path.write_bytes(content)
    return path


def test_normalize_to_crlf_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "linesep", "\r\n")
    path = _write(tmp_path, b"line1\nline2\n")

    _normalize_generated_line_endings(tmp_path)

    assert path.read_bytes() == b"line1\r\nline2\r\n"


def test_normalize_keeps_lf_on_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "linesep", "\n")
    path = _write(tmp_path, b"line1\nline2\n")

    _normalize_generated_line_endings(tmp_path)

    assert path.read_bytes() == b"line1\nline2\n"


def test_normalize_is_idempotent_for_crlf_input(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "linesep", "\r\n")
    path = _write(tmp_path, b"line1\r\nline2\r\n")

    _normalize_generated_line_endings(tmp_path)

    assert path.read_bytes() == b"line1\r\nline2\r\n"


def test_normalize_skips_subdirectories(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "linesep", "\r\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    path = _write(tmp_path, b"a\nb\n")

    _normalize_generated_line_endings(tmp_path)

    assert path.read_bytes() == b"a\r\nb\r\n"
    assert sub.is_dir()
