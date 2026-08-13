#!/usr/bin/env bash
# 构建「内置 ct 运行时」的 macOS launcher。
#
# 前置：Flutter SDK（可用 FLUTTER 环境变量指定，默认取 PATH 中的 flutter）、
#       ct/.venv（Python >= 3.10，按根 AGENTS.md 创建）、Xcode + CocoaPods。
#
# 产物：launcher/build/macos/Build/Products/Release/ct_launcher.app
#       （内含 Contents/Resources/runtime/，随包分发，用户无需安装 Python）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CT_DIR="$REPO_ROOT/ct"
LAUNCHER_DIR="$REPO_ROOT/launcher"
VENV_PY="$CT_DIR/.venv/bin/python"
FLUTTER="${FLUTTER:-flutter}"

if [ ! -x "$VENV_PY" ]; then
  echo "[error] 未找到 ct venv: $VENV_PY（请先按根 AGENTS.md 创建）" >&2
  exit 1
fi

echo "[1/4] 冻结 ct CLI（PyInstaller onedir）..."
"$VENV_PY" -m pip install -q pyinstaller
(
  cd "$CT_DIR"
  "$VENV_PY" -m PyInstaller --noconfirm --distpath dist --workpath build packaging/ct.spec
)

RUNTIME_DIR="$CT_DIR/dist/ct-runtime"
if [ ! -x "$RUNTIME_DIR/ct" ]; then
  echo "[error] 冻结产物缺失: $RUNTIME_DIR/ct" >&2
  exit 1
fi

echo "[2/4] 构建 macOS launcher（flutter build macos --release）..."
(
  cd "$LAUNCHER_DIR"
  "$FLUTTER" build macos --release
)

APP="$LAUNCHER_DIR/build/macos/Build/Products/Release/ct_launcher.app"
if [ ! -d "$APP" ]; then
  echo "[error] launcher 产物缺失: $APP" >&2
  exit 1
fi

echo "[3/4] 嵌入 runtime 到 .app/Contents/Resources/runtime/ ..."
RESOURCES="$APP/Contents/Resources"
rm -rf "$RESOURCES/runtime"
mkdir -p "$RESOURCES/runtime"
cp -R "$RUNTIME_DIR/." "$RESOURCES/runtime/"

echo "[4/4] ad-hoc 签名..."
codesign --force --deep -s - "$APP"

echo "完成：$APP"
echo "分发：整个 .app 可复制到游戏仓库（如 Config/launcher-apps/）；Windows 版请用 launcher/tool/build_windows.ps1 在 Windows 机器构建。"
