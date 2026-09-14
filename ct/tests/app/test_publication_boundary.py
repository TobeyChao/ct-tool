"""构建与正式写入分离：末段生成失败不得留下任何正式产物改动（task 3.1）。"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from typer.testing import CliRunner

import ct.app.exporting.build as export_module
from _helpers import build_project
from ct.app.canonical_commands import canonical_validate
from ct.app.canonical_export import persist_export_state, run_canonical_export
from ct.cli import app
from ct.contracts import CancelToken, CancelledError
from ct.storage.publication import FilePublisher


def _project(tmp_path: Path, tables: tuple[str, ...] = ("Item",)) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": name,
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                ],
            }
            for name in tables
        ],
    )
    from _helpers import make_workbook

    for name in tables:
        make_workbook(root, name, [[1, "剑"]])
    return root


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    """正式产物快照：output/ 与导出产生的 layout manifest，含 mtime。"""
    files: dict[str, tuple[bytes, int]] = {}
    for base in (root / "output", root / "excel" / "layout_manifests"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(root))] = (
                    path.read_bytes(),
                    path.stat().st_mtime_ns,
                )
    return files


def _assert_untouched(root: Path, before: dict[str, tuple[bytes, int]]) -> None:
    after = _snapshot(root)
    assert set(after) == set(before), "产物集合发生变化"
    for key, (payload, mtime) in before.items():
        assert after[key] == (payload, mtime), f"{key} 的内容或 mtime 被改动"


def test_late_fbs_check_failure_leaves_everything_untouched(
    tmp_path: Path, monkeypatch
) -> None:
    """阶段 2 已经生成 JSON，阶段 4 的 FBS 检查失败 —— 正式产物必须原样。"""
    root = _project(tmp_path)
    run_canonical_export(root)
    before = _snapshot(root)
    assert before, "首次导出应产出正式产物"

    def boom(*args, **kwargs):
        raise RuntimeError("FBS 检查失败（注入）")

    monkeypatch.setattr(export_module, "validate_canonical_fbs", boom)
    with pytest.raises(RuntimeError, match="FBS 检查失败"):
        run_canonical_export(root, forced=True)

    _assert_untouched(root, before)


def test_late_bundle_failure_leaves_everything_untouched(
    tmp_path: Path, monkeypatch
) -> None:
    """最后一个阶段（Bundle）失败 —— 前面阶段的 JSON/bytes/Accessor 都不得落盘。"""
    root = _project(tmp_path)
    run_canonical_export(root)
    before = _snapshot(root)

    def boom(*args, **kwargs):
        raise RuntimeError("Bundle 生成失败（注入）")

    monkeypatch.setattr(export_module, "build_canonical_bundle", boom)
    with pytest.raises(RuntimeError, match="Bundle 生成失败"):
        run_canonical_export(root, forced=True)

    _assert_untouched(root, before)


def test_first_export_failure_creates_no_output(tmp_path: Path, monkeypatch) -> None:
    """首次导出即末段失败：output/ 与 manifest 目录不应被创建出半套内容。"""
    root = _project(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("Bundle 生成失败（注入）")

    monkeypatch.setattr(export_module, "build_canonical_bundle", boom)
    with pytest.raises(RuntimeError):
        run_canonical_export(root)

    assert not (root / "output").exists() or not any(
        (root / "output").rglob("*.json")
    )
    # 模板 manifest 由 gen-template 预置；导出失败不得改动它
    manifests = sorted(p.name for p in (root / "excel" / "layout_manifests").glob("*.json"))
    assert manifests == ["Item.json"]


def test_generation_failure_does_not_touch_manifests(tmp_path: Path, monkeypatch) -> None:
    """manifest 是发布目标：生成失败时它的内容与 mtime 也必须不变。"""
    root = _project(tmp_path)
    run_canonical_export(root)
    manifest = root / "excel" / "layout_manifests" / "Item.json"
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)

    def boom(*args, **kwargs):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(export_module, "build_canonical_bundle", boom)
    with pytest.raises(RuntimeError):
        run_canonical_export(root, forced=True)

    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before


# --------------------------------------------------- 发布范围与删除集合（3.4）


def test_filtered_export_does_not_expand_scope(tmp_path: Path) -> None:
    """单表导出只产出选中表 + 共享产物，未选中表一个文件都不许出现。"""
    root = _project(tmp_path, tables=("Item", "Other"))
    manifests_before = sorted(
        p.name for p in (root / "excel" / "layout_manifests").glob("*.json")
    )
    run_canonical_export(root, table_filter="Item")

    produced = {
        str(p.relative_to(root))
        for p in (root / "output").rglob("*")
        if p.is_file()
    }
    assert not any("Other" in name for name in produced), sorted(produced)
    manifests = sorted(p.name for p in (root / "excel" / "layout_manifests").glob("*.json"))
    assert manifests == manifests_before == ["Item.json", "Other.json"]
    json_files = sorted(p.name for p in (root / "output" / "json").glob("*.json"))
    assert json_files == ["Item_en.json", "Item_zh.json"]
    # 共享产物仍参与导出
    assert (root / "output" / "fbs" / "types.fbs").is_file()
    assert (root / "output" / "fbs" / "container.fbs").is_file()


def test_language_filter_keeps_primary_json(tmp_path: Path) -> None:
    """次语言过滤仍生成选中表的主语言 JSON（既有兼容行为）。"""
    root = _project(tmp_path)
    run_canonical_export(root, lang_filter="en")
    names = sorted(p.name for p in (root / "output" / "json").glob("*.json"))
    assert names == ["Item_en.json", "Item_zh.json"]
    bundles = sorted(p.name for p in (root / "output" / "binary").glob("*.bin"))
    assert bundles == ["data_en.bin"]


def test_stale_artifacts_are_deleted_on_full_export(tmp_path: Path) -> None:
    """全量导出必须清掉上一轮遗留、本轮不再产出的旧产物。"""
    root = _project(tmp_path, tables=("Item", "Other"))
    run_canonical_export(root)
    stale = root / "output" / "json" / "Other_zh.json"
    assert stale.is_file()

    (root / "config" / "schemas" / "Other.yaml").unlink()
    (root / "excel" / "Other.xlsx").unlink()
    run_canonical_export(root)

    assert not stale.exists()
    assert (root / "output" / "json" / "Item_zh.json").is_file()


def test_filtered_export_never_deletes_out_of_scope_artifacts(tmp_path: Path) -> None:
    """过滤导出不清理范围外产物（否则会把别的表删掉）。"""
    root = _project(tmp_path, tables=("Item", "Other"))
    run_canonical_export(root)
    other = root / "output" / "json" / "Other_zh.json"
    assert other.is_file()

    run_canonical_export(root, table_filter="Item")
    assert other.is_file(), "过滤导出不应删除未选中表的产物"


def test_stale_enumeration_excludes_private_staging(tmp_path: Path) -> None:
    """私有暂存目录不能被当成陈旧产物删除。"""
    root = _project(tmp_path)
    staging = root / "output" / export_module.STAGING_SUBDIR
    staging.mkdir(parents=True, exist_ok=True)
    marker = staging / "in-flight-payload.bin"
    marker.write_bytes(b"staged")

    run_canonical_export(root)

    assert marker.is_file(), "私有暂存被陈旧清理误删"


# ------------------------------------------------- 取消边界（4.5）


def test_cancel_before_publication_keeps_old_version(tmp_path: Path) -> None:
    """发布开始前取消：正式产物与账本都不变。"""
    root = _project(tmp_path)
    first = run_canonical_export(root)
    persist_export_state(root, first["excel_hashes"], first["bundle_hashes"])
    before = _snapshot(root)
    state_before = (root / "cache" / "state.json").read_bytes()

    token = CancelToken()
    token.cancel()
    with pytest.raises(CancelledError):
        run_canonical_export(root, forced=True, cancel_token=token)

    _assert_untouched(root, before)
    assert (root / "cache" / "state.json").read_bytes() == state_before


def test_cancel_during_publication_still_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    """发布已开始后到达的取消不得把已提交的产物误报为已取消。"""
    root = _project(tmp_path)
    run_canonical_export(root)

    token = CancelToken()
    real_publish = FilePublisher.publish

    def spy(self, payloads, deletions=()):
        token.cancel()  # 取消恰好落在发布窗口内
        return real_publish(self, payloads, deletions)

    monkeypatch.setattr(FilePublisher, "publish", spy)

    result = run_canonical_export(root, forced=True, cancel_token=token)

    assert result["written"], "发布窗口内的取消不应中断事务"
    assert not FilePublisher(root).journal_path.exists(), "事务应正常提交并清理"


# --------------------------------------------- 只读命令的报告（4.4）


def _write_pending_journal(root: Path) -> Path:
    """伪造一个「未完成发布」现场（阶段 publishing）。"""
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    journal = publisher.journal_path
    journal.write_text(
        json.dumps(
            {
                "format": "export-publication/1",
                "operation_id": "fake-op",
                "root": str(root),
                "phase": "publishing",
                "allowed_dirs": [str((root / "output").resolve())],
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return journal


def test_validate_reports_pending_publication_without_recovering(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    run_canonical_export(root)
    journal = _write_pending_journal(root)
    before = _snapshot(root)

    issues = canonical_validate(root)

    assert any("未完成的发布" in issue.message for issue in issues)
    assert journal.exists(), "只读命令不得删除恢复材料"
    assert _snapshot(root) == before, "只读命令不得执行恢复写入"


def test_validate_reports_corrupt_publication_record(tmp_path: Path) -> None:
    root = _project(tmp_path)
    run_canonical_export(root)
    publisher = FilePublisher(root)
    publisher.private_dir.mkdir(parents=True, exist_ok=True)
    publisher.journal_path.write_text("{ 坏掉的 JSON", encoding="utf-8")

    issues = canonical_validate(root)

    assert any("损坏" in issue.message for issue in issues)
    assert publisher.journal_path.exists()


def test_status_reports_pending_publication(tmp_path: Path) -> None:
    root = _project(tmp_path)
    run_canonical_export(root)
    _write_pending_journal(root)

    result = CliRunner().invoke(app, ["status", "--root", str(root)])

    output = (result.stdout or "") + (result.stderr or "")
    assert "未完成的发布" in output
    assert "[OK]" not in output, "存在未完成发布时不得报告一切正常"


def test_export_recovers_before_running(tmp_path: Path) -> None:
    """下一次 export 必须先恢复现场，再执行本次请求。"""
    root = _project(tmp_path)
    run_canonical_export(root)
    publisher = FilePublisher(root)

    # 制造一个「已替换了一个文件、但未提交」的现场
    target = root / "output" / "json" / "Item_zh.json"
    original = target.read_bytes()
    backup_dir = publisher.private_dir / "backup" / "fake-op"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "Item_zh.json"
    backup.write_bytes(original)
    target.write_bytes(b'{"Items": "gone"}')
    _write_pending_journal_with_entry(root, target, backup)

    run_canonical_export(root, forced=True)

    assert target.read_bytes() != b'{"Items": "gone"}'
    assert not publisher.journal_path.exists()


def _write_pending_journal_with_entry(root: Path, target: Path, backup: Path) -> Path:
    publisher = FilePublisher(root)
    journal = publisher.journal_path
    journal.write_text(
        json.dumps(
            {
                "format": "export-publication/1",
                "operation_id": "fake-op",
                "root": str(root),
                "phase": "publishing",
                "allowed_dirs": [str((root / "output").resolve())],
                "entries": [
                    {
                        "path": str(target),
                        "op": "replace",
                        "existed": True,
                        "old_hash": "x",
                        "new_hash": "y",
                        "staged": None,
                        "backup": str(backup),
                        "done": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return journal


# ------------------------------- manifest 与产物在同一可恢复事务内（4.2）


def test_manifest_participates_in_the_recoverable_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    """manifest 属于发布范围：发布中途崩溃后必须与 output 一起被恢复。"""
    root = _project(tmp_path)
    run_canonical_export(root)
    before = _snapshot(root)
    assert any("layout_manifests" in name for name in before)

    real_apply = FilePublisher._apply
    applied = {"count": 0}

    def flaky(self, entry):
        real_apply(self, entry)
        applied["count"] += 1
        if applied["count"] == 1:
            raise RuntimeError("注入：发布中途崩溃")

    monkeypatch.setattr(FilePublisher, "_apply", flaky)
    # 模拟进程直接死亡：不留自动回滚机会
    monkeypatch.setattr(FilePublisher, "_rollback", lambda self, staging: None)
    with pytest.raises(RuntimeError):
        run_canonical_export(root, forced=True)

    publisher = FilePublisher(root)
    assert publisher.read_journal() is not None, "崩溃后必须留下恢复记录"

    publisher.recover()
    _assert_untouched(root, before)
