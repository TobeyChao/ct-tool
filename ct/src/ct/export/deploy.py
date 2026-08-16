"""部署到 Unity Assets：目录同步与目标编排。

语义（详见 openspec change deploy-unity-assets design.md）：
- 每个目标目录被同步为与对应产物目录完全一致：新增写入、变化覆盖、多余删除。
- 代码产物同步时保留已存在文件的 `.meta`（GUID 稳定）；产物文件被删除时连带删同名 `.meta`。
- 二进制产物只做覆盖，不管理 meta。
"""

from __future__ import annotations

from pathlib import Path

from ct.app.events import ProgressReporter
from ct.app.options import ExportOptions
from ct.app.workspace import Workspace


def sync_dir(src: Path, dst: Path, reporter: ProgressReporter) -> int:
    """把 dst 同步为与 src 一致，返回写入/删除的文件总数。

    不存在的 src 视为错误（防止把空目录同步过去造成误删）。
    """
    if not src.is_dir():
        raise FileNotFoundError(f"产物目录不存在: {src}")
    dst.mkdir(parents=True, exist_ok=True)

    src_names = {p.name for p in src.iterdir() if p.is_file()}
    changed = 0

    # 清理目标中多余产物：源里没有的非 .meta 文件删除；孤儿 .meta 仅当对应
    # 产物文件也不存在时删除（仍存在产物的 .meta 必须保留）。
    for p in sorted(dst.iterdir()):
        if not p.is_file():
            continue
        if p.name in src_names:
            continue
        if p.name.endswith(".meta"):
            stem = p.name[: -len(".meta")]
            if stem in src_names:
                continue
            p.unlink()
            reporter.log(f"[deploy] 删除 {p}")
            changed += 1
            continue
        p.unlink()
        reporter.log(f"[deploy] 删除 {p}")
        changed += 1

    # 新增/覆盖：内容不一致才写入，避免无谓的 mtime 变化触发 Unity 重导入。
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        target = dst / p.name
        try:
            same = target.read_bytes() == p.read_bytes()
        except FileNotFoundError:
            same = False
        if not same:
            target.write_bytes(p.read_bytes())
            reporter.log(f"[deploy] 写入 {target}")
            changed += 1
    return changed


def deploy(ws: Workspace, opts: ExportOptions, reporter: ProgressReporter) -> int:
    """按配置部署产物，返回写入/删除的文件总数。

    未配置或未启用时跳过（返回 0）。失败时抛 FileNotFoundError/OSError。
    """
    if not ws.config.deploy.enabled:
        reporter.log("[deploy] 未配置或未启用，跳过", err=True)
        return 0

    targets = ws.config.resolve_deploy_targets(for_build=opts.for_build)
    if not targets:
        reporter.log("[deploy] unity_project 未配置，跳过", err=True)
        return 0

    total = 0
    for src, dst in targets:
        reporter.log(f"[deploy] 同步 {src} → {dst}")
        total += sync_dir(src, dst, reporter)
    return total
