#!/usr/bin/env python3
"""基线采集：在临时工作区跑普通/过滤/强制导出，记录产物内容与元信息。

绝不修改源工作区（默认 ``gd/``）：每次都把源工作区复制到临时目录，清掉
派生产物（``output/`` ``cache/`` ``excel/layout_manifests/``）后，再以
``--root <临时目录>`` 运行 ``ct export``。这样第一次运行是真正的冷启动，
第二次才覆盖 warm（缓存全命中、mtime 应保持）路径。

用法::

    python capture.py --ct <venv>/bin/ct --src ../../../gd --out .

产物：每个 mode 一个 JSON，含 mode、每次运行的 exit code/stdout/stderr、
**每次运行后的文件快照**（sha256 / size / mtime_ns），以及最终的
cache/state.json 内容。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

SNAPSHOT_DIRS = ("output", "excel/layout_manifests")

#: 派生目录：冷启动前删除，保证第一次导出真的在写
DERIVED_DIRS = ("output", "cache", "excel/layout_manifests")

#: 与产物无关的系统垃圾文件，不进入快照
IGNORED_NAMES = {".DS_Store"}


def snapshot(workspace: Path) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    for sub in SNAPSHOT_DIRS:
        base = workspace / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in str(path):
                continue
            if path.name in IGNORED_NAMES:
                continue
            stat = path.stat()
            files[str(path.relative_to(workspace))] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
    return files


def prepare(src: Path, workspace: Path) -> None:
    """复制源工作区并清空派生目录 ⇒ 冷启动。"""
    shutil.copytree(src, workspace)
    for sub in DERIVED_DIRS:
        shutil.rmtree(workspace / sub, ignore_errors=True)


def run_mode(
    *, ct: Path, src: Path, tmp: Path, mode: str, argv: list[str], runs: int = 1
) -> dict:
    workspace = tmp / mode
    prepare(src, workspace)
    transcript: list[dict] = []
    # 每次运行后各存一份快照：用于证明 warm 运行不会无谓改写文件（mtime 稳定）
    snapshots: list[dict[str, dict[str, object]]] = []
    for _ in range(runs):
        proc = subprocess.run(
            [str(ct), "export", *argv, "--root", str(workspace)],
            capture_output=True,
            text=True,
        )
        transcript.append(
            {
                "argv": ["ct", "export", *argv, "--root", "<tmp>"],
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        )
        snapshots.append(snapshot(workspace))
        if proc.returncode != 0:
            break
    state_path = workspace / "cache" / "state.json"
    return {
        "mode": mode,
        "runs": transcript,
        "snapshots": snapshots,
        "files": snapshots[-1] if snapshots else {},
        "state_json": json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.is_file()
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ct", required=True, type=Path, help="venv 里的 ct 可执行文件")
    parser.add_argument("--src", required=True, type=Path, help="源工作区（不会被修改）")
    parser.add_argument("--out", required=True, type=Path, help="采集结果输出目录")
    args = parser.parse_args()

    src = args.src.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    cases = {
        # 冷启动 → warm：第二次覆盖缓存全命中与 mtime 保持
        "normal": (["--verbose"], 2),
        # ItemType 无跨表 ref，单表导出可校验通过（见 baseline.md）
        "filtered": (["--table", "ItemType"], 1),
        # 反向证据：带跨表 ref 的单表导出必须仍被拒（design 决策 6 要求保留的范围）
        "filtered_ref_blocked": (["--table", "Item"], 1),
        "forced": (["--all"], 1),
    }

    with tempfile.TemporaryDirectory(prefix="ct-baseline-") as raw_tmp:
        tmp = Path(raw_tmp)
        for mode, (argv, runs) in cases.items():
            result = run_mode(
                ct=args.ct, src=src, tmp=tmp, mode=mode, argv=argv, runs=runs
            )
            (out / f"{mode}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            codes = [run["returncode"] for run in result["runs"]]
            print(f"{mode}: exit={codes} files={len(result['files'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
