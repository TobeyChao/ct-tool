"""导出应用层的类型化内部契约。

跨阶段传递的是这些对象，而不是散落的字典：请求、完成策略、准备结果、单表
构建结果、产物集合、最终结果。原 canonical 入口（``run_canonical_export``）
继续以同样的参数与返回 dict 形状对外，只在这里做一次适配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class InputChangedError(ValueError):
    """输入在捕获后发生变化：拒绝发布混合输入集合。

    继承 ``ValueError``，因此 CLI 的 ``(FileNotFoundError, ValueError)`` 分支
    会把它渲染成友好错误而非 traceback。
    """


@dataclass(frozen=True)
class ExportRequest:
    """一次导出请求的全部输入（root + 过滤 + 是否强制）。"""

    root: Path
    table_filter: str | None = None
    lang_filter: str | None = None
    forced: bool = False


@dataclass(frozen=True)
class CompletionPolicy:
    """入口策略：Web 只导出；CLI 导出后部署（可带 --for-build）。

    这是 CLI/Web 唯一允许分叉的地方；业务层不读 CLI flag、不调用 typer。
    """

    deploy: bool = False
    for_build: bool = False

    @classmethod
    def export_only(cls) -> "CompletionPolicy":
        return cls()

    @classmethod
    def export_then_deploy(cls, *, for_build: bool = False) -> "CompletionPolicy":
        return cls(deploy=True, for_build=for_build)


@dataclass(frozen=True)
class PreparedExport:
    """阶段 1 的输出：选中表/语言的稳定序列与解析结果。"""

    tables: tuple[str, ...]
    languages: tuple[str, ...]
    primary_lang: str
    prepared: tuple[Any, ...] = ()
    records: dict[str, Any] = field(default_factory=dict)
    enums: dict[str, Any] = field(default_factory=dict)


@dataclass
class TableBuild:
    """阶段 2 的单表产物：定宽声明、偏移常量与各语言字节。

    ``uniform`` 来自表 schema 的声明（缺省 true）；``fill_rate`` 只用于诊断报告，
    不参与布局决策。``slot_offsets`` 只在 ``uniform`` 为真时有意义（表级常量，
    供生成器发射字面量偏移）；``primary_bytes`` 是主表字节，``i18n_bytes`` 是
    稀疏 i18n 表字节（仅次级语言）。
    """

    table: str
    uniform: bool
    fill_rate: float
    bytes_normal: int
    slot_offsets: dict[int, int] = field(default_factory=dict)
    bytes_uniform: int | None = None
    primary_bytes: dict[str, bytes] = field(default_factory=dict)
    i18n_bytes: dict[str, bytes] = field(default_factory=dict)
    #: 稀疏 i18n 表**自己**的 slot→offset 常量（沿用主表的 uniform 声明）
    i18n_slot_offsets: dict[int, int] = field(default_factory=dict)

    def to_layout_info(self) -> dict[str, Any]:
        """``LayoutManifest.from_layout`` 需要的形参形状。

        只有 ``slot_offsets`` —— manifest 其余字段取自 layout 本身；
        ``uniform`` / ``fill_rate`` 分别是声明与诊断，都不落盘。
        """
        return {"slot_offsets": dict(self.slot_offsets)}


@dataclass
class ArtifactSet:
    """本次导出期望产出的完整集合，以及每个目标的 payload / 私有暂存引用。

    ``expected`` 是发布范围的真源（发布阶段据此计算新增/覆盖/删除）；
    ``payloads`` 保存待写内容；``staged`` 指向已落私有暂存区的目标。
    """

    expected: set[Path] = field(default_factory=set)
    payloads: dict[Path, bytes] = field(default_factory=dict)
    staged: dict[Path, Path] = field(default_factory=dict)
    deletions: set[Path] = field(default_factory=set)


@dataclass
class ExportResult:
    """一次导出的最终结果；``to_legacy_dict`` 保持原 canonical 返回形状。"""

    tables: int
    languages: list[str]
    written: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    bundle_hashes: dict[str, str] = field(default_factory=dict)
    excel_hashes: dict[str, str] = field(default_factory=dict)
    forced: bool = False
    elapsed: float = 0.0

    def to_legacy_dict(self) -> dict[str, Any]:
        """兼容适配：旧调用方按 dict 取值，字段名与含义保持不变。"""
        return {
            "tables": self.tables,
            "languages": self.languages,
            "written": self.written,
            "reused": self.reused,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "bundle_hashes": self.bundle_hashes,
            "excel_hashes": self.excel_hashes,
            "forced": self.forced,
            "elapsed": self.elapsed,
        }
