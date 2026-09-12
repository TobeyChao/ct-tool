"""导出应用层的类型化契约：请求/结果/完成策略，以及旧入口的兼容形状。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_export import run_canonical_export
from ct.app.exporting.models import (
    ArtifactSet,
    CompletionPolicy,
    ExportRequest,
    ExportResult,
    PreparedExport,
    TableBuild,
)

#: 旧调用方依赖的返回字段（顺序无关，集合必须一致）
LEGACY_KEYS = {
    "tables",
    "languages",
    "written",
    "reused",
    "cache_hits",
    "cache_misses",
    "bundle_hashes",
    "excel_hashes",
    "forced",
    "elapsed",
}


def _project(tmp_path: Path) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [{"name": "Id", "type": "int32"}],
            }
        ],
    )
    excel = root / "excel"
    excel.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(["id"])       # 注释行
    ws.append(["主键"])     # 字段行
    ws.append([1])
    wb.save(str(excel / "Item.xlsx"))
    return root


def test_export_result_exposes_exactly_the_legacy_fields() -> None:
    result = ExportResult(tables=1, languages=["zh"])
    assert set(result.to_legacy_dict()) == LEGACY_KEYS


def test_run_canonical_export_keeps_the_legacy_dict_shape(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = run_canonical_export(root)
    assert set(result) == LEGACY_KEYS
    assert result["tables"] == 1
    assert result["languages"] == ["zh", "en"]
    assert result["forced"] is False
    assert set(result["excel_hashes"]) == {"Item"}
    assert isinstance(result["elapsed"], float)


def test_run_canonical_export_reports_forced(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assert run_canonical_export(root, forced=True)["forced"] is True


def test_compat_entry_exports_only(tmp_path: Path, monkeypatch) -> None:
    """兼容入口只导出：不部署、不提交成功账本（那些属于完整应用用例）。"""
    root = _project(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "ct.export.deploy.deploy", lambda *args, **kwargs: calls.append("deploy") or 0
    )

    result = run_canonical_export(root)

    assert calls == [], "兼容入口不得部署"
    assert set(result) == LEGACY_KEYS
    assert not (root / "cache" / "state.json").exists(), "兼容入口不得提交账本"
    assert (root / "output" / "json" / "Item_zh.json").is_file()


def test_export_request_carries_filters_and_forced() -> None:
    request = ExportRequest(
        root=Path("/tmp/x"), table_filter="Item", lang_filter="en", forced=True
    )
    assert request.table_filter == "Item"
    assert request.lang_filter == "en"
    assert request.forced is True


def test_completion_policy_has_exactly_two_strategies() -> None:
    only = CompletionPolicy.export_only()
    assert (only.deploy, only.for_build) == (False, False)

    deploy = CompletionPolicy.export_then_deploy(for_build=True)
    assert (deploy.deploy, deploy.for_build) == (True, True)

    assert CompletionPolicy.export_then_deploy() == CompletionPolicy(deploy=True)
    assert only != deploy


def test_build_and_artifact_containers_default_to_empty() -> None:
    build = TableBuild(table="Item", uniform=False, fill_rate=0.5, bytes_normal=10)
    assert build.primary_bytes == {} and build.i18n_bytes == {}
    assert build.bytes_uniform is None

    artifacts = ArtifactSet()
    assert artifacts.expected == set()
    assert artifacts.payloads == {} and artifacts.staged == {} and artifacts.deletions == set()

    prepared = PreparedExport(tables=("Item",), languages=("zh",), primary_lang="zh")
    assert prepared.records == {} and prepared.enums == {}
