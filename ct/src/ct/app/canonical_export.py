"""兼容层：原 canonical 导出入口。

真正的五阶段 pipeline 已移到 :mod:`ct.app.exporting.build`（唯一实现）；这里只
保留参数、返回 dict 形状与异常契约的**兼容委托**，并把历史上从这里导入的名字
继续暴露出去，避免既有调用方与测试断裂。

新代码请直接用 ``ct.app.exporting.service``（完整用例）或
``ct.app.exporting.build``（纯 pipeline）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ct.app.exporting.build import (
    CANONICAL_STEPS,
    CODEGEN_VERSION,
    STAGING_SUBDIR,
    UNIFORM_FILL_THRESHOLD,
    _Publication,
    _assert_single_vtable,
    _i18n_rows,
    _i18n_table,
    _merge_i18n,
    _named_ref,
    _sha,
    _table_types,
    persist_export_state,
    run_pipeline,
)
from ct.app.exporting.models import ExportRequest
from ct.contracts import CancelToken, NullReporter, ProgressReporter

__all__ = [
    "CANONICAL_STEPS",
    "CODEGEN_VERSION",
    "STAGING_SUBDIR",
    "UNIFORM_FILL_THRESHOLD",
    "persist_export_state",
    "run_canonical_export",
    "run_pipeline",
]


def run_canonical_export(
    root: Path,
    *,
    table_filter: str | None = None,
    lang_filter: str | None = None,
    forced: bool = False,
    reporter: ProgressReporter | None = None,
    cancel_token: CancelToken | None = None,
) -> dict[str, Any]:
    """兼容入口：**只导出**，保持原 dict 返回形状与异常契约。

    不部署、不提交成功账本（那些属于 CLI/Web 的完整应用用例）。它与完整用例共用
    同一把工作区锁与同一份发布恢复，但**只调用一次锁，不递归抢锁**。
    """
    from ct.app.exporting.service import export_only

    request = ExportRequest(
        root=root,
        table_filter=table_filter,
        lang_filter=lang_filter,
        forced=forced,
    )
    result = export_only(
        request,
        reporter=reporter or NullReporter(),
        cancel_token=cancel_token,
    )
    return result.to_legacy_dict()
