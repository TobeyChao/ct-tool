#!/usr/bin/env bash
# 构建「内置原生 Rust 运行时」的 macOS launcher（native Web 桌面壳）。
#
# 前置：Flutter SDK（可用 FLUTTER 环境变量指定，默认取 PATH 中的 flutter）、
#       Rust 工具链 + Xcode + CocoaPods。**不再需要 Python/ct/.venv**：
#       先在 native/ 下执行 `cargo run -p ct-xtask --release -- dist` 产出运行时包，
#       本脚本做「定位包 -> flutter build -> 嵌单个 ct 二进制 -> 复核无解释器 -> ad-hoc 签名 -> DMG」。
#
# 产物：launcher/build/macos/Build/Products/Release/ct_launcher.app
#       launcher/build/macos/ct-launcher-<arch>.dmg
#       （内含 Contents/Resources/runtime/ct，随包分发，用户无需安装 Python）
#
# 可选：RUNTIME_PACKAGE=<native/dist 下的包目录> 指定运行时包；SKIP_FLUTTER_BUILD=1 复用已有构建产物。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LAUNCHER_DIR="$REPO_ROOT/launcher"
DIST_ROOT="$REPO_ROOT/native/dist"

# Flutter 定位：环境变量优先，其次 PATH，最后常见安装位置。
if [ -n "${FLUTTER:-}" ]; then
  FLUTTER_BIN="$FLUTTER"
elif command -v flutter >/dev/null 2>&1; then
  FLUTTER_BIN="$(command -v flutter)"
else
  for candidate in \
    "$HOME/development/flutter/bin/flutter" \
    "$HOME/flutter/bin/flutter" \
    "/opt/homebrew/bin/flutter" \
    "/usr/local/bin/flutter"; do
    if [ -x "$candidate" ]; then
      FLUTTER_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "${FLUTTER_BIN:-}" ] || [ ! -x "$FLUTTER_BIN" ]; then
  echo "[error] 未找到 Flutter SDK。请安装后重试，或用 FLUTTER=/path/to/flutter 指定。" >&2
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TRIPLE="aarch64-apple-darwin" ;;
  x86_64) TRIPLE="x86_64-apple-darwin" ;;
  *) TRIPLE="" ;;
esac

echo "[1/6] 定位原生运行时包（${TRIPLE}）"
if [ -n "${RUNTIME_PACKAGE:-}" ]; then
  RUNTIME_BIN="$RUNTIME_PACKAGE/bin/ct"
else
  RUNTIME_BIN=""
  if [ -d "$DIST_ROOT" ]; then
    if [ -n "$TRIPLE" ]; then
      CANDIDATE="$(ls -1td "$DIST_ROOT"/ct-native-*"$TRIPLE" 2>/dev/null | head -n 1 || true)"
    else
      CANDIDATE="$(ls -1td "$DIST_ROOT"/ct-native-*apple-darwin 2>/dev/null | head -n 1 || true)"
    fi
    if [ -n "$CANDIDATE" ]; then
      RUNTIME_BIN="$CANDIDATE/bin/ct"
    fi
  fi
fi
if [ -z "$RUNTIME_BIN" ] || [ ! -x "$RUNTIME_BIN" ]; then
  echo "[error] 没有可用的原生运行时包：先在 native/ 执行 cargo run -p ct-xtask --release -- dist" >&2
  echo "        或显式指定 RUNTIME_PACKAGE=<native/dist 下的包目录>" >&2
  exit 1
fi
echo "      内置运行时: $RUNTIME_BIN"
"$RUNTIME_BIN" --version

# 运行时包内不得混入解释器（无 Python 依赖是可交付的硬条件）。
RUNTIME_ROOT="$(dirname "$(dirname "$RUNTIME_BIN")")"
if find "$RUNTIME_ROOT" \( -name "python*" -o -name "*.py" -o -name "*.pyc" \) -print | grep -q .; then
  echo "[error] 运行时包内含解释器文件" >&2
  find "$RUNTIME_ROOT" \( -name "python*" -o -name "*.py" -o -name "*.pyc" \) | sed "s/^/        /" >&2
  exit 1
fi

if [ "${SKIP_FLUTTER_BUILD:-0}" = "1" ]; then
  echo "[2/6] 跳过 flutter build（SKIP_FLUTTER_BUILD=1）"
else
  echo "[2/6] 构建 macOS launcher（flutter build macos --release）..."
  (
    cd "$LAUNCHER_DIR"
    "$FLUTTER_BIN" build macos --release
  )
fi

APP="$LAUNCHER_DIR/build/macos/Build/Products/Release/ct_launcher.app"
if [ ! -d "$APP" ]; then
  echo "[error] launcher 产物缺失: $APP" >&2
  exit 1
fi

echo "[3/6] 嵌入单个原生二进制到 .app/Contents/Resources/runtime/ ..."
RESOURCES="$APP/Contents/Resources"
rm -rf "$RESOURCES/runtime"
mkdir -p "$RESOURCES/runtime"
cp "$RUNTIME_BIN" "$RESOURCES/runtime/ct"
chmod +x "$RESOURCES/runtime/ct"
for extra in VERSION.json RUNTIME-CHECK.txt README.md; do
  if [ -f "$RUNTIME_ROOT/$extra" ]; then
    cp "$RUNTIME_ROOT/$extra" "$RESOURCES/runtime/"
  fi
done

echo "[4/6] 复核：包内不得含解释器，且内置运行时要在无 Python 环境里真跑只读命令"
if find "$APP" \( -name "python[0-9.]*" -o -name "*.py" -o -name "*.pyc" -o -name "site-packages" \) -print | grep -q .; then
  echo "[error] .app 内含 Python 痕迹" >&2
  find "$APP" \( -name "python[0-9.]*" -o -name "*.py" -o -name "site-packages" \) | sed "s/^/        /" >&2
  exit 1
fi
SCRATCH_WS="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_WS"' EXIT
mkdir -p "$SCRATCH_WS/config/schemas"
printf 'primary_lang: zh\nsecondary_langs:\n  - en\n' > "$SCRATCH_WS/config/global.yaml"
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP -u VIRTUAL_ENV -u CONDA_PREFIX \
  PATH="$RESOURCES/runtime" \
  "$RESOURCES/runtime/ct" status --root "$SCRATCH_WS" >/dev/null
echo "      无 Python 环境下 status 通过"

echo "[5/6] ad-hoc 签名..."
codesign --force --deep -s - "$APP"

echo "[6/6] 生成带 Applications 快捷方式的 DMG..."
DMG_STAGE="$(mktemp -d)"
trap 'rm -rf "$SCRATCH_WS" "$DMG_STAGE"' EXIT
ditto "$APP" "$DMG_STAGE/ct_launcher.app"
ln -s /Applications "$DMG_STAGE/Applications"
DMG="$LAUNCHER_DIR/build/macos/ct-launcher-$ARCH.dmg"
hdiutil create -volname 'ct launcher' -srcfolder "$DMG_STAGE" -format UDZO -ov "$DMG" >/dev/null

echo "完成：$APP"
echo "      安装镜像：$DMG"
echo "      桌面壳按内置 -> 显式开发路径两条来源找运行时，无 Python 回退。"
