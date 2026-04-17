from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_TARGETS = [
    ("--cpp", "cpp"),
    ("--csharp", "csharp"),
    ("--lua", "lua"),
]


def check_flatc(flatc_path: Path) -> bool:
    if not flatc_path.exists():
        logger.error(
            f"flatc 未找到: {flatc_path}\n"
            f"请将 flatc 可执行文件放入项目目录（如 tools/flatc），"
            f"并在 config/global.yaml 中配置 flatc_path"
        )
        return False
    return True


def compile_fbs(
    flatc_path: Path,
    fbs_dir: Path,
    output_dir: Path,
) -> bool:
    if not check_flatc(flatc_path):
        return False

    fbs_files = sorted(fbs_dir.glob("*.fbs"))
    if not fbs_files:
        logger.warning("无 .fbs 文件需要编译")
        return True

    success = True
    for flag, subdir in _TARGETS:
        out = output_dir / "generated" / subdir
        out.mkdir(parents=True, exist_ok=True)
        for fbs_file in fbs_files:
            cmd = [str(flatc_path), flag, "-o", str(out), str(fbs_file)]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    logger.error(
                        f"flatc 编译失败 [{fbs_file.name}] {flag}:\n{result.stderr}"
                    )
                    success = False
                else:
                    logger.info(f"flatc {flag} {fbs_file.name} → {out}")
            except FileNotFoundError:
                logger.error(f"无法执行 flatc: {flatc_path}")
                return False
            except subprocess.TimeoutExpired:
                logger.error(f"flatc 编译超时: {fbs_file.name}")
                success = False

    return success
