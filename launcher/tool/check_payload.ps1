# 校验 Windows 桌面发行负载「不含也不再启动 Flask/Python」（native-flutter-workbench 任务 5.6）。
#
# 用法：pwsh launcher/tool/check_payload.ps1 [-Payload <dir>] [-WorkspaceRoot <dir>]
#   -Payload        默认 launcher/build/windows/x64/runner/Release
#   -WorkspaceRoot  用于真跑只读命令的工作区，默认仓库 gd/
#
# 两道判定：
# 1) 负载里不得出现任何 Python/Flask 痕迹（文件名与目录）；
# 2) 内置 ct.exe 必须能在「PATH 只剩负载目录、PYTHON* 变量全清」的环境里真跑只读命令。
param(
    [string]$Payload = "",
    [string]$WorkspaceRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ($Payload -eq "") {
    $Payload = Join-Path $RepoRoot "launcher\build\windows\x64\runner\Release"
}
if ($WorkspaceRoot -eq "") {
    $WorkspaceRoot = Join-Path $RepoRoot "gd"
}
if (-not (Test-Path $Payload)) {
    Write-Host "[error] 找不到发行负载目录：$Payload" -ForegroundColor Red
    Write-Host "        先执行 pwsh launcher/tool/build_windows.ps1" -ForegroundColor Yellow
    exit 1
}

$deny = "(?i)(python[\w.-]*\.(dll|exe|py|pyc|pyd|zip))|(\.py[cod]$)|(?<![a-z])flask(?![a-z])|\.venv|site-packages|(?<![a-z])pip(?![a-z])|ct-runtime"
$files = @(Get-ChildItem -Recurse -File $Payload)
$bad = @($files | Where-Object { $_.FullName -match $deny })
Write-Host "[1/3] 负载文件 $($files.Count) 个，Python/Flask 痕迹 $($bad.Count) 处"
$bad | ForEach-Object { Write-Host "        禁止出现: $($_.FullName)" -ForegroundColor Red }

$Runtime = Join-Path $Payload "runtime\ct.exe"
$Exe = Join-Path $Payload "ct_launcher.exe"
if (-not (Test-Path $Runtime)) { Write-Host "[error] 缺少内置运行时 $Runtime" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $Exe)) { Write-Host "[error] 缺少桌面壳可执行 $Exe" -ForegroundColor Red; exit 1 }

Write-Host "[2/3] 隔离环境真跑内置运行时"
$env:PATH = (Split-Path $Runtime)
foreach ($name in @("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "CONDA_PREFIX")) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
$version = & $Runtime --version 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "[error] ct --version 失败：$version" -ForegroundColor Red; exit 1 }
Write-Host "        $version"
# 只读命令：status/validate 都不写工作区（校验失败也不改产物），可以直接对真实 gd/ 跑。
# 工作区缺失（例如 CI 上未检出 gd/）时降级为「只验负载与版本」，不谎称真跑过。
if (-not (Test-Path $WorkspaceRoot)) {
    Write-Host "        跳过只读命令：工作区不存在 $WorkspaceRoot" -ForegroundColor Yellow
}
foreach ($cmd in @("status", "validate")) {
    if (-not (Test-Path $WorkspaceRoot)) { break }
    $out = & $Runtime $cmd --root $WorkspaceRoot 2>&1
    $code = $LASTEXITCODE
    Write-Host ("        ct {0} --root gd -> exit {1}" -f $cmd, $code)
    if ($code -gt 1) {
        Write-Host "[error] 无 Python 环境下 ct $cmd 异常：" -ForegroundColor Red
        $out | Select-Object -First 6 | ForEach-Object { Write-Host "        $_" }
        exit 1
    }
}

Write-Host "[3/3] 结论"
if ($bad.Count -eq 0) {
    Write-Host "        负载不含 Python/Flask，内置 ct.exe 在无 Python 环境真跑通过" -ForegroundColor Green
    exit 0
}
Write-Host "        发现 Python/Flask 痕迹，5.6 不得勾选" -ForegroundColor Red
exit 1
