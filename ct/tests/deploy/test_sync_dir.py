"""目录同步三态 + meta 保护 + 幂等。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ct.export.deploy import sync_dir


class _Reporter:
    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        pass


def _write(p: Path, content: str) -> None:
    p.write_text(content, encoding="utf-8")


def test_sync_adds_updates_and_deletes(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _write(src / "a.cs", "A1")
    _write(src / "b.lua", "B")
    _write(dst / "a.cs", "A0")
    _write(dst / "b.lua", "B")
    _write(dst / "old.cs", "OLD")
    _write(dst / "old.cs.meta", "M")

    sync_dir(src, dst, _Reporter())

    assert (dst / "a.cs").read_text() == "A1"
    assert (dst / "b.lua").read_text() == "B"
    assert not (dst / "old.cs").exists()
    assert not (dst / "old.cs.meta").exists()


def test_sync_preserves_meta_of_existing_files(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _write(src / "a.cs", "A")
    _write(dst / "a.cs", "A0")
    _write(dst / "a.cs.meta", "GUID-KEEP")

    sync_dir(src, dst, _Reporter())

    assert (dst / "a.cs").read_text() == "A"
    assert (dst / "a.cs.meta").read_text() == "GUID-KEEP"


def test_sync_idempotent(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _write(src / "a.cs", "A")
    _write(src / "b.bin", "BB")

    sync_dir(src, dst, _Reporter())
    before = {(p.name, p.read_bytes()) for p in dst.iterdir()}
    sync_dir(src, dst, _Reporter())
    after = {(p.name, p.read_bytes()) for p in dst.iterdir()}

    assert before == after


def test_sync_missing_src_raises(tmp_path: Path) -> None:
    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(FileNotFoundError):
        sync_dir(tmp_path / "nope", dst, _Reporter())


def test_sync_ignores_subdirectories(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "sub").mkdir()
    _write(src / "sub" / "x.cs", "X")
    _write(dst / "leftover.cs", "L")

    sync_dir(src, dst, _Reporter())

    # 只同步文件层级；子目录产物不在管理范围
    assert not (dst / "leftover.cs").exists()
    assert not (dst / "sub").exists()
