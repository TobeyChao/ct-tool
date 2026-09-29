# 单条命令的墙钟耗时与峰值 RSS（Windows：.NET Process.PeakWorkingSet64，即 GetProcessMemoryInfo）。
# 输出压缩 JSON：{"wallMs":..,"peakRssKb":..,"exitRssKb":..,"exit":..}
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string]$ExeArgs = '',
    [Parameter(Mandatory = $true)][string]$Workspace,
    [string]$StdinFile = '',
    [int]$PollMs = 5,
    [int]$TreePollMs = 40
)
$ErrorActionPreference = 'Stop'
$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $Exe
$psi.Arguments = $ExeArgs
$psi.WorkingDirectory = $Workspace
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.RedirectStandardInput = $true
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = [Diagnostics.Process]::Start($psi)
$outTask = $p.StandardOutput.ReadToEndAsync()
$errTask = $p.StandardError.ReadToEndAsync()
if ($StdinFile -ne '') {
    $stdin = $p.StandardInput
    $stdin.Write([IO.File]::ReadAllText($StdinFile))
    $stdin.Close()
}
$peak = [int64]0
# 进程树峰值：pip/PyInstaller 的 ct.exe 可能是宿主存根，真实解释器是子进程，
# 因此同时统计「自身 PeakWorkingSet64」与「父子树当前工作集之和的峰值」。
$peakTree = [int64]0
$pid0 = $p.Id
$nextTree = [DateTime]::MinValue
while (-not $p.HasExited) {
    $p.Refresh()
    if ($p.PeakWorkingSet64 -gt $peak) { $peak = $p.PeakWorkingSet64 }
    if ((Get-Date) -ge $nextTree) {
        $nextTree = (Get-Date).AddMilliseconds($TreePollMs)
        try {
            $sum = (Get-Process -Id $pid0).WorkingSet64
            if ($sum -gt $peakTree) { $peakTree = $sum }
        } catch { }
        try {
            $kids = @(Get-CimInstance -ErrorAction Stop Win32_Process -Filter "ParentProcessId=$pid0")
            foreach ($kid in $kids) {
                try { $sum += (Get-Process -Id $kid.ProcessId).WorkingSet64 } catch { }
            }
            if ($sum -gt $peakTree) { $peakTree = $sum }
        } catch { }
    }
    Start-Sleep -Milliseconds $PollMs
}
$p.WaitForExit()
$p.Refresh()
if ($p.PeakWorkingSet64 -gt $peak) { $peak = $p.PeakWorkingSet64 }
if ($peakTree -le 0) {
    # 单进程被测对象（原生 ct 不起子进程）时，自身峰值即进程树峰值
    $peakTree = $peak
}
$sw.Stop()
$work = 0
try { $work = $p.WorkingSet64 } catch { }
$result = [ordered]@{
    wallMs    = [int64]$sw.Elapsed.TotalMilliseconds
    peakRssKb = [int64]($peak / 1KB)
    peakTreeRssKb = [int64]($peakTree / 1KB)
    exitRssKb = [int64]($work / 1KB)
    exit      = $p.ExitCode
    stdoutLen = $outTask.Result.Length
    stderrLen = $errTask.Result.Length
}
if ($p.ExitCode -ne 0 -or $errTask.Result.Trim().Length -gt 0) {
    $result['stderr'] = $errTask.Result.Substring(0, [Math]::Min(400, $errTask.Result.Length))
}
$result | ConvertTo-Json -Compress