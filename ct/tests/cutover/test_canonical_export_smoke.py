"""Canonical export smoke: run canonical export on the repository_cutover
fixture (canonical workspace) and assert the artifact tree is produced
(FBS/binary/accessors) plus the background task reports phases/history."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ct.app.canonical_export import run_canonical_export

FIXTURE = Path(__file__).parents[2] / "tests/fixtures/repository_cutover/workspace"


def test_canonical_export_writes_fbs_binary_accessors(tmp_path: Path) -> None:
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    run_canonical_export(workspace)
    fbs = workspace / "output" / "fbs"
    assert (fbs / "types.fbs").exists()
    assert "enum ItemRarity : byte" in (fbs / "types.fbs").read_text(encoding="utf-8")
    assert (fbs / "Item.fbs").exists()
    binary = workspace / "output" / "binary"
    for lang in ("zh", "en", "ja"):
        assert (binary / f"data_{lang}.bin").exists()
    generated = workspace / "output" / "generated"
    assert (generated / "csharp" / "ItemAccessor.cs").exists()
    assert (generated / "lua" / "ItemAccessor.lua").exists()


def test_canonical_export_manifest_is_content_stable(tmp_path: Path) -> None:
    """manifest 不带 layout_revision：重复导出（含强制）内容逐字节不变。"""
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    manifest_path = workspace / "excel" / "layout_manifests" / "Item.json"
    run_canonical_export(workspace)
    first = manifest_path.read_bytes()
    assert "layout_revision" not in json.loads(first)

    run_canonical_export(workspace)
    assert manifest_path.read_bytes() == first

    # 强制导出按规格重写全部选中产物，但字节必须与同输入的增量结果相同
    run_canonical_export(workspace, forced=True)
    assert manifest_path.read_bytes() == first


def test_canonical_export_task_reports_phases_and_history(tmp_path: Path) -> None:
    import time

    from ct.web.tasks import canonical_export_task

    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    try:
        canonical_export_task.start(workspace, forced=False)
        deadline = time.time() + 20
        steps_seen: list[str] = []
        last: dict = {}
        while time.time() < deadline:
            last = canonical_export_task.progress()
            if last["step_name"]:
                steps_seen.append(last["step_name"])
            if last["status"] != "running":
                break
            time.sleep(0.02)
        assert last.get("status") == "done", last
        assert last["tables_exported"] == 4
        assert last["step_index"] == len(last["steps"]) - 1
        assert last["forced"] is False
        # full phase list is reported; the export is fast, so only assert the
        # complete steps list plus the observed final step (no polling-granularity flake)
        assert last["steps"] == ["解析校验", "JSON", "Accessor", "FBS", "Bundle"]
        assert "Bundle" in steps_seen
        # history entry written to the workspace cache
        history = json.loads(
            (workspace / "cache" / "panel_history.json").read_text(encoding="utf-8")
        )
        assert history[-1]["result"] == "成功"
        assert history[-1]["tables"] == 4
    finally:
        canonical_export_task.status = "idle"


# ---------------------------------------------------------------------------
# 定宽布局（uniform）：导出期逐表决策 + 落盘 + 硬断言
# ---------------------------------------------------------------------------


def _export_fixture(tmp_path: Path) -> Path:
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    run_canonical_export(workspace)
    return workspace


def test_uniform_decision_is_recorded_in_manifest(tmp_path: Path) -> None:
    """每张表的定宽决策、填充率、slot→offset 都要落盘，便于复查与生成器消费。"""
    workspace = _export_fixture(tmp_path)
    manifests = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (workspace / "excel" / "layout_manifests").glob("*.json")
    }
    # Item 填充率 92.9% → 开；UIConfig 63.3% → 不开（阈值 0.75）
    assert manifests["Item"]["uniform"] is True
    assert 0.9 < manifests["Item"]["fill_rate"] <= 1.0
    assert manifests["UIConfig"]["uniform"] is False
    assert 0.5 < manifests["UIConfig"]["fill_rate"] < 0.75
    # 定宽表必须给出表级 slot→offset，且**没有 0 偏移**（0 表示槽位缺失）
    offsets = dict(manifests["Item"]["slot_offsets"])
    assert offsets and all(off != 0 for off in offsets.values())
    # 未定宽的表不写偏移
    assert manifests["UIConfig"]["slot_offsets"] == []


def test_uniform_table_accessor_has_no_offset_table(tmp_path: Path) -> None:
    workspace = _export_fixture(tmp_path)
    generated = workspace / "output" / "generated" / "csharp"
    item = (generated / "ItemAccessor.cs").read_text(encoding="utf-8")
    uiconfig = (generated / "UIConfigAccessor.cs").read_text(encoding="utf-8")
    assert "private readonly int[] _off;" not in item
    assert "OffsetsFor" not in item
    assert "private readonly int[] _off;" in uiconfig
    assert "OffsetsFor" in uiconfig


def test_uniform_tables_really_have_single_vtable(tmp_path: Path) -> None:
    """导出物层面复核：被判为定宽的表，其字节里只能有 1 种 vtable。"""
    import struct

    from ct.export.canonical_binary import count_vtables

    workspace = _export_fixture(tmp_path)
    bundle = (workspace / "output" / "binary" / "data_zh.bin").read_bytes()
    manifests = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (workspace / "excel" / "layout_manifests").glob("*.json")
    }

    def u16(b, o):
        return struct.unpack_from("<H", b, o)[0]

    def i32(b, o):
        return struct.unpack_from("<i", b, o)[0]

    root = i32(bundle, 0)
    vt = root - i32(bundle, root)
    vec = root + u16(bundle, vt + 4)
    vec += i32(bundle, vec)
    base, count = vec + 4, i32(bundle, vec)
    seen = 0
    for i in range(count):
        e = base + i * 4
        entry = e + i32(bundle, e)
        evt = entry - i32(bundle, entry)
        np_ = entry + u16(bundle, evt + 4)
        np_ += i32(bundle, np_)
        name = bundle[np_ + 4:np_ + 4 + i32(bundle, np_)].decode()
        dp = entry + u16(bundle, evt + 6)
        dp += i32(bundle, dp)
        table = bundle[dp + 4:dp + 4 + i32(bundle, dp)]
        n = count_vtables(table)
        if manifests[name]["uniform"]:
            assert n == 1, f"{name} 被判为定宽，却有 {n} 种 vtable"
        seen += 1
    assert seen == len(manifests)


def test_uniform_assertion_fires_when_slot_is_omitted(tmp_path: Path, monkeypatch) -> None:
    """A5 硬断言必须真的挡得住：人为让枚举槽位又被省略 → 导出应报错，而不是产出错数据。"""
    import pytest

    from ct.export import canonical_binary as cb

    def _buggy_prepend_enum(self, builder, type_expr, value, index):        # noqa: ANN001
        # 复刻修复前的行为：uniform 下仍走 PrependInt8Slot(.., 0)，第 0 项不占位
        builder.PrependInt8Slot(index, self._enum_index(type_expr, value), 0)

    monkeypatch.setattr(cb._Builder, "_prepend_enum", _buggy_prepend_enum)

    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    from ct.app.canonical_commands import CanonicalValidationError

    with pytest.raises(CanonicalValidationError) as excinfo:
        run_canonical_export(workspace)
    issues = excinfo.value.issues
    assert issues, "应报告问题"
    assert any("vtable" in str(issue) for issue in issues), (
        f"应指出 vtable 数不为 1，实际 issues={issues}"
    )


def test_export_cleans_stale_generated_dirs(tmp_path: Path) -> None:
    """B4：全量导出前清理 output/fbs 与 output/generated，避免陈旧格式误导消费方。

    实例：2026/8/14 的 *_i18n.fbs 与 9/10 的产物并存，而全仓已无代码生成它们。
    """
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)
    stale_fbs = workspace / "output" / "fbs" / "Item_i18n.fbs"
    stale_fbs.parent.mkdir(parents=True, exist_ok=True)
    stale_fbs.write_text("// 上一代遗留\n", encoding="utf-8")
    stale_cs = workspace / "output" / "generated" / "csharp" / "Zombie.cs"
    stale_cs.parent.mkdir(parents=True, exist_ok=True)
    stale_cs.write_text("// 上一代遗留\n", encoding="utf-8")

    run_canonical_export(workspace)

    assert not stale_fbs.exists()
    assert not stale_cs.exists()
    assert (workspace / "output" / "fbs" / "types.fbs").exists()   # 新产物在


def test_export_emits_enum_declarations(tmp_path: Path) -> None:
    workspace = _export_fixture(tmp_path)
    gen = workspace / "output" / "generated"
    cs = (gen / "csharp" / "Enums.cs").read_text(encoding="utf-8")
    lua = (gen / "lua" / "Enums.lua").read_text(encoding="utf-8")
    assert "public enum ItemRarity : byte" in cs
    assert "public enum UIConfigLayer : byte" in cs
    assert "common = 0," in cs
    assert "Enums.ItemRarity = {" in lua


def test_export_wires_declared_indexes_into_accessors(tmp_path: Path) -> None:
    """B1：表声明的 indexes 必须一路到达生成物（原先硬编码 () ⇒ 永不生成 ByCodeName）。"""
    workspace = _export_fixture(tmp_path)
    gen = workspace / "output" / "generated" / "csharp"
    item_type = (gen / "ItemTypeAccessor.cs").read_text(encoding="utf-8")
    uiconfig = (gen / "UIConfigAccessor.cs").read_text(encoding="utf-8")
    # 只有 ItemType 声明了索引（codename）；UIConfig 没声明，且 Group 索引已砍
    assert "Runtime.ByCodeName(TableName" in item_type
    assert "Runtime.ByCodeName" not in uiconfig
    assert "GroupKey" not in uiconfig
    # 没声明索引的表不应出现
    assert "Runtime.ByCodeName" not in (gen / "QuestAccessor.cs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C：稀疏 i18n 表（main + i18n 侧表）—— 这是 spec 本就要求的形态
# ---------------------------------------------------------------------------


def _bundle_table_names(bundle: bytes) -> list[str]:
    import struct

    def u16(b, o):
        return struct.unpack_from("<H", b, o)[0]

    def i32(b, o):
        return struct.unpack_from("<i", b, o)[0]

    root = i32(bundle, 0)
    vt = root - i32(bundle, root)
    vec = root + u16(bundle, vt + 4)
    vec += i32(bundle, vec)
    base, count = vec + 4, i32(bundle, vec)
    names: list[str] = []
    for i in range(count):
        e = base + i * 4
        entry = e + i32(bundle, e)
        evt = entry - i32(bundle, entry)
        np_ = entry + u16(bundle, evt + 4)
        np_ += i32(bundle, np_)
        names.append(bundle[np_ + 4:np_ + 4 + i32(bundle, np_)].decode())
    return names


def test_bundles_split_main_and_sparse_i18n(tmp_path: Path) -> None:
    """主语言包 = 主表（全量字段）；次级语言包 = **稀疏 i18n 表**（主键 + i18n 字段）。"""
    workspace = _export_fixture(tmp_path)
    binary = workspace / "output" / "binary"

    zh = _bundle_table_names((binary / "data_zh.bin").read_bytes())
    assert "Item" in zh and "ItemType" in zh and "Quest" in zh
    assert not any(n.endswith("_i18n") for n in zh), "主语言包不应含 i18n 侧表"

    for lang in ("en", "ja"):
        names = _bundle_table_names((binary / f"data_{lang}.bin").read_bytes())
        assert names == ["ItemType_i18n", "Item_i18n", "Quest_i18n"]
        # UIConfig 没有 i18n 字段 ⇒ 不应产出 i18n 表
        assert "UIConfig_i18n" not in names


def test_sparse_i18n_is_much_smaller_than_full_copy(tmp_path: Path) -> None:
    """稀疏表体积应显著小于「每语言一份全量」——这正是恢复该架构的理由。"""
    workspace = _export_fixture(tmp_path)
    binary = workspace / "output" / "binary"
    zh_size = (binary / "data_zh.bin").stat().st_size
    en_size = (binary / "data_en.bin").stat().st_size
    # Small fixtures include bundle/vtable/alignment overhead; allow 10%
    # relative slack around the 50% target rather than depending on padding.
    assert en_size < zh_size * 0.55, f"en={en_size} 应远小于 zh={zh_size}"


def test_i18n_fbs_declares_entry_and_table(tmp_path: Path) -> None:
    """spec：主表 fbs 之外还要有 {Table}I18nEntry / {Table}I18nTable。"""
    workspace = _export_fixture(tmp_path)
    item_fbs = (workspace / "output" / "fbs" / "Item.fbs").read_text(encoding="utf-8")
    assert "table ItemI18nEntry {" in item_fbs
    assert "table ItemI18nTable {" in item_fbs
    assert "Id: int32;" in item_fbs
    # 没有 i18n 字段的表不应产出
    uiconfig_fbs = (workspace / "output" / "fbs" / "UIConfig.fbs").read_text(encoding="utf-8")
    assert "UIConfigI18nEntry" not in uiconfig_fbs


def test_main_accessor_reads_i18n_from_sparse_table(tmp_path: Path) -> None:
    """改动 1/7 的生成器侧：多语言字段按**行下标**读稀疏 i18n 表，且有原文回退。

    读路径**内联在主 accessor 里**，不再有一份独立的 `{Table}_i18nAccessor`：
    那份包装的唯一消费者就是这里的 getter，对外没有任何用途。
    """
    workspace = _export_fixture(tmp_path)
    gen = workspace / "output" / "generated" / "csharp"
    item = (gen / "ItemAccessor.cs").read_text(encoding="utf-8")
    assert "Item_i18nAccessor" not in item
    assert not (gen / "Item_i18nAccessor.cs").exists()
    assert not (gen / "Item_i18nAccessor.lua").exists()
    # i18n 表缺席（主语言＝默认发布形态）⇒ 读回 null；表/行在时按行下标取译文
    assert "Runtime.TryTable(I18nTableName)" in item
    assert "string v = ItemAccessor.I18nName(_index);" in item
    # 回退分支走 per-field 行下标缓存（主语言默认走这条路；
    # 没缓存时每次 50.25 ns + 35.4 字节/次）
    assert "NStringCache.Decode" in item
    assert "string[] c = ItemAccessor.NameCache;" in item
    assert "c[_index] = s;" in item
    # 主表原文缓存的世代是**主表**世代：它与语言无关（切语言不动主表）
    assert "_strCacheVersion = TableVersion.Current;" in item
    # 译文缓存的世代是 **i18n** 世代：切语言时它必须整体重建（实测踩过串语言）
    assert "_i18nStrCacheVersion = TableVersion.I18nCurrent;" in item
    assert "_i18nStrCacheVersion == TableVersion.I18nCurrent" in item
    # 句柄守卫在**表缺席**时也必须生效，否则每次读都重走一遍 TryTable
    assert "_i18nTableVersion == TableVersion.I18nCurrent" in item
    # Lua 侧同样不再产出独立模块（它从来没有被 require 过）
    lua = (workspace / "output" / "generated" / "lua" / "ItemAccessor.lua").read_text(
        encoding="utf-8"
    )
    assert "local function i18n_table()" in lua
    assert 'GD.FindTableI18n("Item_i18n")' in lua


# ---------------------------------------------------------------------------
# P1/P2 回归：清理时序 / 仅次级语言导出 / 空表
# ---------------------------------------------------------------------------


def test_export_secondary_lang_only_uniform_table(tmp_path: Path) -> None:
    """P1：--lang en（仅次级语言）导出定宽 i18n 表不得 KeyError。

    修复前主语言被过滤掉时 ``bytes_uniform`` 从未写入 layout_info，
    阶段 2 的日志格式化直接 KeyError。
    """
    workspace = tmp_path / "gd"
    for section in ("config", "excel", "i18n"):
        shutil.copytree(FIXTURE / section, workspace / section)

    result = run_canonical_export(workspace, lang_filter="en")

    assert result["languages"] == ["en"]
    binary = workspace / "output" / "binary"
    assert (binary / "data_en.bin").exists()
    # 次级语言包 = 稀疏 i18n 表（Item 是定宽表，en 语言只走 i18n 侧表）
    assert set(_bundle_table_names((binary / "data_en.bin").read_bytes())) == {
        "ItemType_i18n",
        "Item_i18n",
        "Quest_i18n",
    }
    # 主语言未请求 ⇒ 不产出主语言包
    assert not (binary / "data_zh.bin").exists()
