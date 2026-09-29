# 构建「内置原生内核运行时」的 Windows launcher（需在 Windows 机器上执行）。
#
# 前置：Flutter SDK（在 PATH 中）、Visual Studio 桌面开发工作负载，以及已产出的原生
#       运行时包：在 native/ 下执行 `cargo run -p ct-xtask -- dist`。
#
# 产物：launcher/build/windows/x64/runner/Release/
#       （ct_launcher.exe + runtime\ct.exe，整个目录即可分发；不含也不需要 Python）
#
# 用法：pwsh launcher/tool/build_windows.ps1 [-RuntimePackage <dir>] [-SkipFlutterBuild]
#
# 正式入口只有「原生运行时」一条路：不再保留 Python 面板运行时回退，
# 桌面构建不再用 PyInstaller 冻结面板；构建后可用 check_payload.ps1 复核负载无 Python。
param(
    # 指定运行时包目录；默认取 native/dist 下最新的 ct-native-*windows* 包。
    [string]$RuntimePackage = "",
    # 复用已有 flutter build 产物（只换运行时）。
    [switch]$SkipFlutterBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LauncherDir = Join-Path $RepoRoot "launcher"
$DistRoot = Join-Path $RepoRoot "native\dist"
$RuntimeBin = $null

Write-Host "[1/4] 定位原生运行时包"
if ($RuntimePackage -ne "") {
  $RuntimeBin = Join-Path $RuntimePackage "bin\ct.exe"
} else {
  $candidates = @(
    if (Test-Path $DistRoot) {
      Get-ChildItem -Directory $DistRoot -Filter "ct-native-*windows*" |
        Sort-Object LastWriteTime -Descending
    }
  )
  if ($candidates.Count -gt 0) {
    $RuntimeBin = Join-Path $candidates[0].FullName "bin\ct.exe"
  }
}
if ($null -eq $RuntimeBin -or -not (Test-Path $RuntimeBin)) {
  Write-Host "[error] 没有可用的原生运行时包。请先在 native/ 执行 cargo run -p ct-xtask -- dist，" -ForegroundColor Red
  Write-Host "        或显式传 -RuntimePackage <包目录>。" -ForegroundColor Yellow
  exit 1
}
Write-Host "      内置运行时: $RuntimeBin"
& $RuntimeBin --version

# 原生包内不得混入解释器（无 Python 依赖是可交付的硬条件）。
$RuntimeRoot = Split-Path (Split-Path $RuntimeBin)
$Strays = @(
  Get-ChildItem -Recurse -File $RuntimeRoot -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(python[\d\.]*\.exe|py\.exe)$' -or $_.Extension -in '.py', '.pyc' }
)
if ($Strays.Count -gt 0) {
  Write-Host "[error] 运行时目录含解释器文件: $($Strays.Name -join ', ')" -ForegroundColor Red
  exit 1
}

if ($SkipFlutterBuild) {
  Write-Host "[2/4] 跳过 flutter build（-SkipFlutterBuild）"
} else {
  Write-Host "[2/4] flutter build windows --release"
  Push-Location $LauncherDir
  & flutter build windows --release
  if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
  Pop-Location
}
$ReleaseDir = Join-Path $LauncherDir "build\windows\x64\runner\Release"
if (-not (Test-Path $ReleaseDir)) {
  Write-Host "[error] launcher 产物目录缺失: $ReleaseDir" -ForegroundColor Red
  exit 1
}

# 3) 嵌入 runtime（PanelService 期望 <exe 同级>\runtime\ct.exe）
Write-Host "[3/4] 嵌入 runtime"
$RuntimeTarget = Join-Path $ReleaseDir "runtime"
if (Test-Path $RuntimeTarget) { Remove-Item -Recurse -Force $RuntimeTarget }
New-Item -ItemType Directory -Path $RuntimeTarget | Out-Null
Copy-Item -Force $RuntimeBin (Join-Path $RuntimeTarget "ct.exe")
foreach ($extra in @("VERSION.json", "RUNTIME-CHECK.txt", "README.md")) {
  $src = Join-Path (Split-Path (Split-Path $RuntimeBin)) $extra
  if (Test-Path $src) { Copy-Item -Force $src (Join-Path $RuntimeTarget $extra) }
}
if (-not (Test-Path (Join-Path $RuntimeTarget "ct.exe"))) {
  Write-Host "[error] 嵌入后仍缺少 runtime\ct.exe" -ForegroundColor Red
  exit 1
}

Write-Host "[4/4] 完成：$ReleaseDir"
Write-Host "      分发整个 Release 目录即可；桌面壳按内置 → 显式开发路径两条来源找运行时，无 Python 回退。"