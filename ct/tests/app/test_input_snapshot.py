"""输入快照：Excel 只读一次、账本 hash 等于实际解析内容、变更复核、行不被就地修改。"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from _helpers import build_project
from ct.app.canonical_export import run_canonical_export
from ct.app.exporting.build import _merge_i18n
from ct.app.exporting.models import InputChangedError
from ct.schema.resources import TableResource


def _excel_bytes(ids: list[int]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["id"])      # 注释行
    ws.append(["主键"])    # 字段行
    for value in ids:
        ws.append([value])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _project(tmp_path: Path, ids: list[int] | None = None) -> Path:
    root = build_project(
        tmp_path / "gd",
        schemas=[
            {
                "table": "Item",
                "primary": "Id",
                "fields": [
                    {"name": "Id", "type": "int32"},
                    {"name": "Name", "type": "string", "i18n": True},
                ],
            }
        ],
    )
    excel = root / "excel"
    excel.mkdir(parents=True, exist_ok=True)
    (excel / "Item.xlsx").write_bytes(_excel_bytes(ids if ids is not None else [1]))
    return root


class _MutatingReporter:
    """第一次收到进度日志时就篡改输入（模拟生成期间的外部编辑）。

    ``after_table`` 回调发生在阶段 1 读完表之后、发布前复核之前。
    """

    def __init__(self, mutate) -> None:
        self._mutate = mutate
        self._done = False

    def step_started(self, step: str) -> None:
        pass

    def step_finished(self, step: str) -> None:
        pass

    def log(self, line: str, *, err: bool = False) -> None:
        if not self._done:
            self._done = True
            self._mutate()


def _reporter_writing(path: Path, payload: bytes) -> _MutatingReporter:
    return _MutatingReporter(lambda: path.write_bytes(payload))


def test_ledger_records_captured_bytes_not_a_later_reread(
    tmp_path: Path, monkeypatch
) -> None:
    """账本 hash 必须来自实际解析的字节，而不是生成完成后重读磁盘。

    这里让「捕获到的字节」与磁盘内容不同：如果实现仍重读磁盘，账本会记录磁盘
    hash，且产物会来自磁盘数据 —— 两个断言都会失败。
    """
    import ct.app.exporting.build as export_module

    root = _project(tmp_path, ids=[1])
    excel = root / "excel" / "Item.xlsx"
    captured = _excel_bytes([7])
    monkeypatch.setattr(
        export_module, "read_excel_bytes", lambda workspace, tables: {excel: captured}
    )

    result = run_canonical_export(root)

    assert result["excel_hashes"]["Item"] == hashlib.sha256(captured).hexdigest()
    assert result["excel_hashes"]["Item"] != hashlib.sha256(
        excel.read_bytes()
    ).hexdigest()
    payload = json.loads((root / "output" / "json" / "Item_zh.json").read_text("utf-8"))
    assert [row["Id"] for row in payload["Items"]] == [7]


def test_excel_change_during_generation_aborts(tmp_path: Path) -> None:
    root = _project(tmp_path, ids=[1])
    excel = root / "excel" / "Item.xlsx"
    with pytest.raises(InputChangedError) as excinfo:
        run_canonical_export(root, reporter=_reporter_writing(excel, _excel_bytes([2])))
    assert "输入在生成期间发生变化" in str(excinfo.value)


def test_new_schema_during_generation_aborts(tmp_path: Path) -> None:
    """只比对文件内容发现不了新增资源 —— 目录成员也必须进快照。"""
    root = _project(tmp_path)
    new_schema = root / "config" / "schemas" / "Quest.yaml"
    body = (
        "table: Quest\nprimary: Id\nfields:\n  - {name: Id, type: int32}\n"
    ).encode("utf-8")
    with pytest.raises(InputChangedError) as excinfo:
        run_canonical_export(root, reporter=_reporter_writing(new_schema, body))
    assert "资源目录成员变化" in str(excinfo.value)


def test_schema_removal_during_generation_aborts(tmp_path: Path) -> None:
    """删除资源同样必须被目录成员复核抓住。"""
    root = _project(tmp_path)
    victim = root / "config" / "schemas" / "Item.yaml"
    with pytest.raises(InputChangedError) as excinfo:
        run_canonical_export(root, reporter=_MutatingReporter(victim.unlink))
    assert "资源目录成员变化" in str(excinfo.value)


def test_global_config_path_change_during_generation_aborts(tmp_path: Path) -> None:
    """global.yaml 改路径会改变全部输入解析结果，必须拦下。"""
    root = _project(tmp_path)
    config = root / "config" / "global.yaml"
    changed = (
        "primary_lang: zh\nsecondary_langs: [en]\nexcel_dir: excel_moved\n"
    ).encode("utf-8")
    with pytest.raises(InputChangedError) as excinfo:
        run_canonical_export(root, reporter=_reporter_writing(config, changed))
    assert "global.yaml" in str(excinfo.value)


def test_change_after_final_check_keeps_captured_hash(
    tmp_path: Path, monkeypatch
) -> None:
    """最终复核之后的外部改动：账本仍记捕获版本，后续 status 能发现变化。"""
    import ct.app.exporting.build as export_module

    root = _project(tmp_path, ids=[1])
    excel = root / "excel" / "Item.xlsx"
    captured_hash = hashlib.sha256(_excel_bytes([1])).hexdigest()

    real_verify = export_module.verify_inputs_unchanged
    calls = {"count": 0}

    def spy(before, after, *, when):
        real_verify(before, after, when=when)
        calls["count"] += 1
        if calls["count"] == 2:  # 第二次 = 发布前复核；之后、返回之前再改磁盘
            excel.write_bytes(_excel_bytes([9]))

    monkeypatch.setattr(export_module, "verify_inputs_unchanged", spy)

    result = run_canonical_export(root)

    assert result["excel_hashes"]["Item"] == captured_hash
    assert result["excel_hashes"]["Item"] != hashlib.sha256(
        excel.read_bytes()
    ).hexdigest()


def test_translation_change_during_generation_aborts(tmp_path: Path) -> None:
    root = _project(tmp_path)
    translation = root / "i18n" / "en" / "Item.json"
    translation.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(InputChangedError):
        run_canonical_export(
            root,
            reporter=_reporter_writing(translation, b'{"1.Name": {}}\n'),
        )


def test_generators_do_not_mutate_parsed_rows(tmp_path: Path, monkeypatch) -> None:
    """生成器不得就地修改共享的 canonical 行（内核把它们同时交给多个阶段）。"""
    import ct.app.exporting.build as export_module

    root = _project(tmp_path)
    holder: dict[str, object] = {}
    real_prepare = export_module.prepare_tables

    def spy(workspace, **kwargs):
        result = real_prepare(workspace, **kwargs)
        holder["result"] = result
        holder["rows"] = copy.deepcopy([item.parsed.rows for item in result.prepared])
        return result

    monkeypatch.setattr(export_module, "prepare_tables", spy)
    run_canonical_export(root)

    result = holder["result"]
    snapshot = holder["rows"]
    for item, expected in zip(result.prepared, snapshot):
        assert item.parsed.rows == expected


def test_merge_i18n_keeps_input_rows_untouched() -> None:
    table = TableResource.model_validate(
        {
            "table": "Item",
            "primary": "Id",
            "fields": [
                {"name": "Id", "type": "int32"},
                {"name": "Name", "type": "string", "i18n": True},
            ],
        }
    )
    rows = [{"Id": 1, "Name": "原文"}]
    merged = _merge_i18n(
        rows, table, {"1.Name": {"text": "译文", "confirmed": True}}
    )
    assert rows == [{"Id": 1, "Name": "原文"}]
    assert merged == [{"Id": 1, "Name": "译文"}]
    assert merged[0] is not rows[0]


# ---------------------------------------------------------------------------
# 生成阶段只消费**捕获到的内容**（配置/资源/译文/旧 manifest），不再读盘


def test_generation_consumes_captured_translation(tmp_path: Path, monkeypatch) -> None:
    """磁盘上的译文与捕获内容不同时，产物必须反映**捕获**的那一份。"""
    import ct.app.exporting.build as build

    root = _project(tmp_path, ids=[1])
    i18n = root / "i18n" / "en" / "Item.json"
    i18n.parent.mkdir(parents=True, exist_ok=True)
    i18n.write_text(
        json.dumps(
            {"1.Name": {"source": "剑", "text": "DISK", "confirmed": True}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured = json.dumps(
        {"1.Name": {"source": "剑", "text": "CAPTURED", "confirmed": True}},
        ensure_ascii=False,
    ).encode("utf-8")

    real = build.capture_translation_contents

    def fake(workspace, **kwargs):
        out = dict(real(workspace, **kwargs))
        out[workspace.resolve("i18n_dir") / "en" / "Item.json"] = captured
        return out

    monkeypatch.setattr(build, "capture_translation_contents", fake)
    run_canonical_export(root)

    payload = json.loads((root / "output" / "json" / "Item_en.json").read_text("utf-8"))
    assert payload["Items"][0]["Name"] == "CAPTURED"


def test_generation_consumes_captured_schema(tmp_path: Path, monkeypatch) -> None:
    """schema 资源同样从捕获内容解析：改捕获内容即可改变产物形状。"""
    import ct.app.exporting.build as build

    root = _project(tmp_path)
    real = build.capture_sources

    def fake(root_path):
        config, contents = real(root_path)
        key = next(path for path in contents if path.name == "Item.yaml")
        text = contents[key].decode("utf-8")
        contents[key] = (text + "\njson_key: capturedItems\n").encode("utf-8")
        return config, contents

    monkeypatch.setattr(build, "capture_sources", fake)
    run_canonical_export(root)

    payload = json.loads((root / "output" / "json" / "Item_zh.json").read_text("utf-8"))
    assert "capturedItems" in payload, f"未使用捕获的 schema：{sorted(payload)}"


def test_generation_consumes_captured_manifest(tmp_path: Path, monkeypatch) -> None:
    """旧 manifest 也来自捕获内容：revision 必须接着**捕获的**那一版递增。"""
    import ct.app.exporting.build as build

    root = _project(tmp_path)
    run_canonical_export(root)  # 先产出 revision 1 的 manifest

    real = build.capture_manifest_contents

    def fake(workspace, **kwargs):
        out = dict(real(workspace, **kwargs))
        key = workspace.resolve("excel_dir") / "layout_manifests" / "Item.json"
        document = json.loads(out[key].decode("utf-8"))
        # 让捕获到的旧 manifest 与当前布局「确有差异」，否则实现会按设计跳过重写
        document["layout_revision"] = 41
        document["schema_hash"] = "captured-schema-hash"
        out[key] = json.dumps(document, ensure_ascii=False).encode("utf-8")
        return out

    monkeypatch.setattr(build, "capture_manifest_contents", fake)
    run_canonical_export(root)

    manifest = json.loads(
        (root / "excel" / "layout_manifests" / "Item.json").read_text("utf-8")
    )
    assert manifest["layout_revision"] == 42, manifest["layout_revision"]
