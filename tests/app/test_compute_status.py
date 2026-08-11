"""`ct/app/status.py::compute_status` 应用层单测。

直接构造 Workspace + CacheState，断言四类状态的分类与顺序
（组内顺序 = ws.order）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook

from ct.app.status import StatusReport, compute_status
from ct.app.workspace import Workspace
from ct.cache.state import CacheState, load_cache, save_cache, update_table_cache
from ct.excel.diff import file_hash
from ct.excel.template import generate_template
from ct.schema.models import TableSchema


_SCHEMA_YAML = """
table: {name}
primary: Id
fields:
  - {{name: Id, type: int32, comment: 主键}}
  - {{name: Name, type: string, comment: 名称}}
"""


def _setup_project(root: Path, names: tuple[str, ...] = ("Item", "ItemType", "Quest", "Skill", "UIConfig")) -> None:
    (root / "config" / "schemas").mkdir(parents=True)
    (root / "excel").mkdir()
    (root / "cache").mkdir()

    (root / "config" / "global.yaml").write_text(
        yaml.safe_dump({"primary_lang": "zh"}), encoding="utf-8"
    )
    for name in names:
        (root / "config" / "schemas" / f"{name}.yaml").write_text(
            _SCHEMA_YAML.format(name=name), encoding="utf-8"
        )


def _schema_from_yaml(root: Path, name: str) -> TableSchema:
    import yaml as _yaml

    data = _yaml.safe_load(
        (root / "config" / "schemas" / f"{name}.yaml").read_text(encoding="utf-8")
    )
    return TableSchema.model_validate(data)


def _seed_cache(root: Path, name: str, schema: TableSchema, *, wrong_hash: bool = False) -> None:
    cache = load_cache(root / "cache")
    xlsx = root / "excel" / f"{name}.xlsx"
    if wrong_hash:
        update_table_cache(cache, name, hash="deadbeef", ids=[])
    else:
        update_table_cache(cache, name, hash=file_hash(xlsx), ids=[])
    save_cache(cache, root / "cache")


def test_compute_status_classifies_all_four_kinds(tmp_path: Path) -> None:
    _setup_project(tmp_path)

    # Item：模板最新 + cache hash 一致 → 正常
    item = _schema_from_yaml(tmp_path, "Item")
    generate_template(item, tmp_path / "excel" / "Item.xlsx")
    _seed_cache(tmp_path, "Item", item)

    # ItemType：手写 excel（无元数据）+ cache 记录 → untracked
    item_type = _schema_from_yaml(tmp_path, "ItemType")
    wb = Workbook()
    wb.active.title = "ItemType"  # type: ignore[union-attr]
    wb.save(str(tmp_path / "excel" / "ItemType.xlsx"))
    _seed_cache(tmp_path, "ItemType", item_type)

    # Quest：无 excel → missing

    # Skill：cache hash 与 excel 不符 → changed
    skill = _schema_from_yaml(tmp_path, "Skill")
    generate_template(skill, tmp_path / "excel" / "Skill.xlsx")
    _seed_cache(tmp_path, "Skill", skill, wrong_hash=True)

    # UIConfig：模板按 v1 生成，schema 升级为 v2 → drifted
    uiconfig = _schema_from_yaml(tmp_path, "UIConfig")
    generate_template(uiconfig, tmp_path / "excel" / "UIConfig.xlsx")
    _seed_cache(tmp_path, "UIConfig", uiconfig)
    v2 = """
table: UIConfig
primary: Id
fields:
  - {name: Id, type: int32, comment: 主键}
  - {name: Name, type: string, comment: 名称}
  - {name: Theme, type: string, comment: 主题}
"""
    (tmp_path / "config" / "schemas" / "UIConfig.yaml").write_text(v2, encoding="utf-8")

    ws = Workspace.load(tmp_path)
    report = compute_status(ws, load_cache(ws.resolve("cache_dir")))

    assert isinstance(report, StatusReport)
    assert report.missing == ["Quest"]
    assert report.changed == ["Skill"]
    assert report.drifted == ["UIConfig"]
    assert report.untracked == ["ItemType"]
    assert report.has_anything


def test_compute_status_all_clean(tmp_path: Path) -> None:
    _setup_project(tmp_path, names=("Item",))
    name = "Item"
    schema = _schema_from_yaml(tmp_path, name)
    generate_template(schema, tmp_path / "excel" / f"{name}.xlsx")
    _seed_cache(tmp_path, name, schema)

    ws = Workspace.load(tmp_path)
    report = compute_status(ws, load_cache(ws.resolve("cache_dir")))

    assert report == StatusReport()
    assert not report.has_anything
