# 构建「内置 ct 运行时」的 Windows launcher（需在 Windows 机器上执行）。
#
# 前置：Flutter SDK（在 PATH 中）、ct/.venv（Windows，按根 AGENTS.md 创建）、
#       Visual Studio 桌面开发工作负载（flutter build windows 需要）。
#
# 产物：launcher/build/windows/x64/runner/Release/
#       （ct_launcher.exe + runtime\，分发整个目录或打包 zip，用户无需安装 Python）
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$CtDir = Join-Path $RepoRoot "ct"
$LauncherDir = Join-Path $RepoRoot "launcher"
$VenvPy = Join-Path $CtDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
  Write-Host "[error] 未找到 ct venv: $VenvPy（请先按根 AGENTS.md 创建）" -ForegroundColor Red
  exit 1
}

Write-Host "[1/4] 冻结 ct CLI（PyInstaller onedir）..."
& $VenvPy -m pip install -q pyinstaller
Push-Location $CtDir
& $VenvPy -m PyInstaller --noconfirm --distpath dist --workpath build packaging\ct.spec
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

$RuntimeDir = Join-Path $CtDir "dist\ct-runtime"
if (-not (Test-Path (Join-Path $RuntimeDir "ct.exe"))) {
  Write-Host "[error] 冻结产物缺失: $RuntimeDir\ct.exe" -ForegroundColor Red
  exit 1
}

Write-Host "[2/4] 构建 Windows launcher（flutter build windows --release）..."
Push-Location $LauncherDir
& flutter build windows --release
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

$ReleaseDir = Join-Path $LauncherDir "build\windows\x64\runner\Release"
if (-not (Test-Path (Join-Path $ReleaseDir "ct_launcher.exe"))) {
  Write-Host "[error] launcher 产物缺失: $ReleaseDir\ct_launcher.exe" -ForegroundColor Red
  exit 1
}

Write-Host "[3/4] 嵌入 runtime 到 exe 同级 runtime\ ..."
$RuntimeTarget = Join-Path $ReleaseDir "runtime"
if (Test-Path $RuntimeTarget) { Remove-Item -Recurse -Force $RuntimeTarget }
New-Item -ItemType Directory -Path $RuntimeTarget | Out-Null
Copy-Item -Recurse -Force (Join-Path $RuntimeDir "*") $RuntimeTarget

Write-Host "[4/4] 完成：$ReleaseDir（分发整个 Release 目录或打包 zip）"
