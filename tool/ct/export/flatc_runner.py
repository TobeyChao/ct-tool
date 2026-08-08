from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_TARGETS = [
    ("--cpp", "cpp"),
    ("--csharp", "csharp"),
    ("--lua", "lua"),
]


def _resolve_flatc(flatc_path: Path) -> Path:
    """Resolve flatc path with platform-aware extension (Windows: .exe)."""
    # On Windows, prefer .exe extension even if a bare file exists
    # (e.g., both "flatc" Linux binary and "flatc.exe" may be present)
    if sys.platform == "win32" and not flatc_path.suffix:
        exe_path = flatc_path.with_suffix(".exe")
        if exe_path.exists():
            return exe_path
    if flatc_path.exists():
        return flatc_path
    return flatc_path


def check_flatc(flatc_path: Path) -> bool:
    resolved = _resolve_flatc(flatc_path)
    if not resolved.exists():
        logger.error(
            f"flatc 未找到: {flatc_path}\n"
            f"请将 flatc 可执行文件放入项目目录（如 tools/flatc），"
            f"并在 config/global.yaml 中配置 flatc_path"
        )
        return False
    try:
        result = subprocess.run(
            [str(resolved), "--version"],
            capture_output=True, text=True, timeout=5,
        )
        flatc_ver = result.stdout.strip().split()[-1] if result.stdout.strip() else ""
    except Exception:
        logger.warning("无法检测 flatc 版本，跳过版本检查")
        return True
    from importlib.metadata import version as pkg_version
    try:
        py_ver = pkg_version("flatbuffers")
    except Exception:
        py_ver = None
    if flatc_ver and py_ver and flatc_ver != py_ver:
        logger.warning(
            f"flatc 版本 ({flatc_ver}) 与 Python flatbuffers ({py_ver}) 不一致，"
            f"binary 格式可能不兼容"
        )
    return True


def compile_fbs(
    flatc_path: Path,
    fbs_dir: Path,
    output_dir: Path,
) -> bool:
    resolved = _resolve_flatc(flatc_path)
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
        # 清空目标目录，防止旧产物残留（flatc 只写新文件、不删旧文件，
        # 命名变更后旧名文件会一直堆在目录里）
        for old in out.iterdir():
            if old.is_file():
                old.unlink()
        for fbs_file in fbs_files:
            cmd = [str(resolved), flag, "-o", str(out), str(fbs_file)]
            # PascalCase 字段名会触发 flatc 的 snake_case 提示，纯噪声
            cmd.insert(1, "--no-warnings")
            if flag == "--lua":
                # WYSIWYG: 字段名按 snake_case 解读，无下划线名（如 UIConfig）
                # 原样透传，不做 lowerCamel 往返（见 flatbuffers fork）
                cmd.insert(1, "--lua-snake-input")
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
