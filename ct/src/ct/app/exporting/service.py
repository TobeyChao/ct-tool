"""统一完成服务：一把工作区锁 + 发布恢复 + pipeline + 完成策略 + 原子账本。

这是 CLI 与 Web **唯一**允许分叉的地方（``CompletionPolicy``）；业务层不读 CLI
flag、不调用 typer、不打印文本——呈现交给显式通知回调与 ``ProgressReporter``。

完成顺序（design 决策 5）：

1. 持锁 → 先恢复上一次未完成的本地发布；
2. 跑 pipeline（prepare/build/publish）；
3. 通知「本地导出完成」（CLI 据此输出 `导出完成: N 张表`）；
4. ``policy.deploy`` 为真时执行部署；
5. 最后原子提交成功账本。

部署或记账失败都向上抛：本地产物保留、账本不推进、命令非零退出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ct.app.exporting.models import (
    CompletionPolicy,
    ExportRequest,
    ExportResult,
)
from ct.contracts import CancelToken, NullReporter, ProgressReporter
from ct.storage.workspace_transaction import workspace_transaction

__all__ = ["run_export", "run_deploy", "workspace_transaction"]


def run_export(
    request: ExportRequest,
    *,
    policy: CompletionPolicy | None = None,
    reporter: ProgressReporter | None = None,
    cancel_token: CancelToken | None = None,
    notify: Callable[[ExportResult], None] | None = None,
    on_deploy: Callable[[int], None] | None = None,
    deployer: Callable[[bool, ProgressReporter], int] | None = None,
) -> ExportResult:
    """完整导出用例：锁 → 恢复 → 发布 → 通知 → （按策略）部署 → 提交账本。

    ``notify`` 在本地发布完成后触发（CLI 据此输出「导出完成」）；``on_deploy``
    在部署成功后带上同步文件数触发（CLI 据此输出部署结果）。两者都是**呈现回调**，
    业务层不打印任何文本。

    ``deployer`` 让适配器决定部署**失败如何呈现**（CLI 需要保留 ``[deploy error]``
    前缀）；不传则直接用 ``ct.export.deploy.deploy``。
    """
    from ct.app.exporting.build import persist_export_state, run_pipeline
    from ct.config import load_config
    from ct.export.deploy import deploy as default_deploy

    policy = policy or CompletionPolicy.export_only()
    reporter = reporter or NullReporter()

    with workspace_transaction(request.root, reporter):
        result = run_pipeline(request, reporter=reporter, cancel_token=cancel_token)

        # 中间通知只表达「本地导出完成」；部署失败仍然是整体失败
        if notify is not None:
            notify(result)

        if policy.deploy:
            if deployer is None:
                changed = default_deploy(
                    load_config(request.root), policy.for_build, reporter
                )
            else:
                changed = deployer(policy.for_build, reporter)
            if on_deploy is not None:
                on_deploy(changed)

        # 本地发布与（可选的）部署都成功后才推进成功账本
        persist_export_state(
            request.root, result.excel_hashes, result.bundle_hashes
        )
    return result


def export_only(
    request: ExportRequest,
    *,
    reporter: ProgressReporter | None = None,
    cancel_token: CancelToken | None = None,
) -> ExportResult:
    """只导出（不部署、不记账）：兼容与 Web 之外的低层调用方使用。"""
    from ct.app.exporting.build import run_pipeline

    reporter = reporter or NullReporter()
    with workspace_transaction(request.root, reporter):
        return run_pipeline(request, reporter=reporter, cancel_token=cancel_token)
