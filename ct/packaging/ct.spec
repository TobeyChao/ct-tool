# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec：冻结完整 ct CLI。

产物为 dist/ct-runtime/ 目录，内含可执行文件 ct（macOS/Linux）或
ct.exe（Windows）与 _internal 支持文件。ct.web 静态资源通过
collect_data_files 收集，运行时以 Path(__file__).parent/"static" 定位。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# SPECPATH 由 PyInstaller 注入：指向本 spec 所在目录（ct/packaging）
SRC = Path(SPECPATH).parent / "src"

datas = collect_data_files("ct.web")
hiddenimports = collect_submodules("ct")

a = Analysis(
    ["ct_entry.py"],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ct",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ct-runtime",
)
