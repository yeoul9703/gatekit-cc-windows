# gatekit verify: everything a change must pass, in one command.
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/verify.ps1 [-Fast]
#   -Fast  quick check: the unit tests skip the slow integration modules (the ones that start
#          PowerShell scripts many times, SLOW_MODULES in tests/run_parallel.py) and the
#          unittest line says so. Run it once without -Fast before a commit.
# Exit code 1 if any check is [fail]. [unverified] (a check that is not
# configured) does not fail the run but is never reported as ok.
# The unit tests run in parallel, one process per test class (tests/run_parallel.py).
# Every step has a time limit (the *Timeout values below, in seconds). Past it the whole
# process tree of that step is killed (taskkill /T /F) and the step is reported as [fail].
# Each line ends with the time the step took.
# Windows PowerShell 5.1 compatible.

param([switch]$Fast)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONUTF8 = '1'

# Time limit per step, in seconds.
$compileTimeout = 120
$testTimeout = 900
$doctorTimeout = 60
$settingsTimeout = 30
$pyrightTimeout = 180
$ruffTimeout = 60

$kit = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $kit)
$venvPy = Join-Path $kit '.venv\Scripts\python.exe'
$launcher = Join-Path $kit 'bin\gatekit.py'
$runner = Join-Path $kit 'tests\run_parallel.py'
$failCount = 0
$totalWatch = [System.Diagnostics.Stopwatch]::StartNew()

function Say([string]$tag, [string]$msg) { Write-Host ('[' + $tag + '] ' + $msg) }
function Fail([string]$msg, $lines) {
    $script:failCount++
    Say 'fail' $msg
    if ($lines) { $lines | Select-Object -Last 15 | ForEach-Object { Write-Host ('       ' + $_) } }
}
function Format-Secs([double]$s) {
    return '(' + $s.ToString('0.0', [System.Globalization.CultureInfo]::InvariantCulture) + 's)'
}
function Fail-Timeout([string]$name, [int]$limit, $r) {
    Fail ($name + ': stopped at the ' + $limit + 's time limit, process tree killed / 제한 시간 ' + $limit + '초 초과, 프로세스 트리 종료 ' + (Format-Secs $r.Seconds)) $r.Lines
}

# ---- process helpers (the same way as Invoke-Proc in setup.ps1) --------------
# Quotes one argument for CreateProcess: backslashes before a quote and at the end are doubled.
function Quote-Arg([string]$a) {
    if ($a -eq '') { return '""' }
    if ($a -notmatch '[\s"]') { return $a }
    $s = $a -replace '(\\*)"', '$1$1\"'
    $s = $s -replace '(\\+)$', '$1$1'
    return '"' + $s + '"'
}

# Kills a process and all its children (a plain Kill leaves grandchildren running).
function Stop-ProcTree($p) {
    try {
        $tk = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        if (Test-Path -LiteralPath $tk) { & $tk /T /F /PID $p.Id 2>&1 | Out-Null }
    } catch { }
    try { if (-not $p.HasExited) { $p.Kill() } } catch { }
}

function Split-Lines([string]$text) {
    return @(($text -split '\r?\n') | Where-Object { $_.Trim() -ne '' })
}

# Runs a program without a shell in $workDir: stdin closed (nothing can prompt), stdout and
# stderr captured, whole process tree killed after $timeoutSec. Returns Started / TimedOut /
# Code / Seconds / OutLines (stdout) / Lines (stdout, then stderr), empty lines dropped.
function Invoke-Proc([string]$file, [string[]]$argList, [int]$timeoutSec, [string]$workDir) {
    $res = [pscustomobject]@{ Started = $false; TimedOut = $false; Code = -1; Seconds = 0.0; OutLines = @(); Lines = @() }
    $stdout = ''
    $stderr = ''
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $file
        $psi.Arguments = (($argList | ForEach-Object { Quote-Arg $_ }) -join ' ')
        $psi.WorkingDirectory = $workDir
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        $p = [System.Diagnostics.Process]::Start($psi)
        $res.Started = $true
        $p.StandardInput.Close()
        $so = $p.StandardOutput.ReadToEndAsync()
        $se = $p.StandardError.ReadToEndAsync()
        if ($p.WaitForExit($timeoutSec * 1000)) {
            $p.WaitForExit()
            $res.Code = $p.ExitCode
        } else {
            $res.TimedOut = $true
            Stop-ProcTree $p
        }
        [void]$so.Wait(3000)
        [void]$se.Wait(1000)
        if ($so.IsCompleted) { $stdout = $so.Result }
        if ($se.IsCompleted) { $stderr = $se.Result }
    } catch {
        $stderr = "$_"
    }
    $watch.Stop()
    $res.Seconds = $watch.Elapsed.TotalSeconds
    $res.OutLines = @(Split-Lines $stdout)
    $res.Lines = @(Split-Lines ($stdout + "`n" + $stderr))
    return $res
}

# The last stdout line (stderr comes after stdout in Lines, so it would win otherwise).
function Get-LastLine($r) {
    $src = @($r.OutLines)
    if ($src.Count -eq 0) { $src = @($r.Lines) }
    if ($src.Count -eq 0) { return '' }
    return $src[$src.Count - 1]
}

if (-not (Test-Path -LiteralPath $venvPy)) {
    Say 'fail' '.claude/gatekit/.venv missing: run scripts/setup.ps1 first / .venv 없음, 먼저 setup.ps1 실행'
    exit 1
}

# 1. syntax -------------------------------------------------------------------
$r = Invoke-Proc $venvPy @('-m', 'compileall', '-q', $kit) $compileTimeout $kit
if ($r.TimedOut) { Fail-Timeout 'compileall' $compileTimeout $r }
elseif ($r.Code -eq 0) { Say 'ok' ('compileall: no syntax errors / 문법 오류 없음 ' + (Format-Secs $r.Seconds)) }
else { Fail ('compileall failed / 실패 ' + (Format-Secs $r.Seconds)) $r.Lines }

# 2. unit tests (parallel, one process per test class) --------------------------
$testName = 'unittest'
$testArgs = @($runner)
if ($Fast) {
    $testName = 'unittest (빠른 검사, 통합 테스트 제외 / quick check, integration tests skipped)'
    $testArgs += '--fast'
}
$r = Invoke-Proc $venvPy $testArgs $testTimeout $kit
$ran = [string]($r.OutLines | Where-Object { $_ -match '^Ran \d+ tests? in ' } | Select-Object -Last 1)
$verdict = [string]($r.OutLines | Where-Object { $_ -match '^(OK|FAILED)\b' } | Select-Object -Last 1)
if ($r.TimedOut) { Fail-Timeout $testName $testTimeout $r }
elseif (($r.Code -eq 0) -and ($verdict -match '^OK')) {
    Say 'ok' ($testName + ': ' + $ran + ', ' + $verdict + ' ' + (Format-Secs $r.Seconds))
}
else {
    Fail ($testName + ' failed / 실패: ' + $ran + ', ' + $verdict + ' ' + (Format-Secs $r.Seconds)) $r.Lines
    Write-Host '       full output / 전체 출력: cd .claude/gatekit; uv run --frozen python tests/run_parallel.py [module]'
}

# 3. doctor -------------------------------------------------------------------
$r = Invoke-Proc $venvPy @($launcher, 'doctor', '--root', $projectRoot) $doctorTimeout $projectRoot
if ($r.TimedOut) { Fail-Timeout 'doctor' $doctorTimeout $r }
elseif ($r.Code -eq 0) {
    # Exit 0 only means "no axis failed"; keep unverified/warn visible.
    $first = ''
    if ($r.OutLines.Count -gt 0) { $first = $r.OutLines[0] }
    $tag = 'ok'
    if ($first -match '\s\S\s(ok|warn|unverified) \(root') { $tag = $Matches[1] }
    Say $tag ('doctor: ' + $first + ' ' + (Format-Secs $r.Seconds))
}
else { Fail ('doctor: an axis failed / 실패한 축 있음 ' + (Format-Secs $r.Seconds)) $r.Lines }

# 4. settings.json ------------------------------------------------------------
$settings = Join-Path $projectRoot '.claude\settings.json'
$r = Invoke-Proc $venvPy @('-c', "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))", $settings) $settingsTimeout $projectRoot
if ($r.TimedOut) { Fail-Timeout '.claude/settings.json check' $settingsTimeout $r }
elseif ($r.Code -eq 0) { Say 'ok' ('.claude/settings.json is valid JSON / 유효한 JSON ' + (Format-Secs $r.Seconds)) }
else { Fail ('.claude/settings.json is not valid JSON / JSON 오류 ' + (Format-Secs $r.Seconds)) $r.Lines }

# 5. type check and lint ------------------------------------------------------
# pyright and ruff live in the uv dev group. pyproject.toml sets default-groups = [], so a plain
# `uv run --frozen` (what the commands use) never installs them: only these two calls ask for
# the group. --frozen never rewrites uv.lock.
$uv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $uv) {
    Fail 'uv not found: type check and lint cannot run / uv 없음, 타입검사·린트 실행 불가' $null
}
else {
    $uvExe = $uv.Source
    $r = Invoke-Proc $uvExe @('run', '--frozen', '--group', 'dev', 'pyright') $pyrightTimeout $kit
    if ($r.TimedOut) { Fail-Timeout 'type check (pyright)' $pyrightTimeout $r }
    elseif ($r.Code -eq 0) { Say 'ok' ('type check (pyright): ' + (Get-LastLine $r) + ' ' + (Format-Secs $r.Seconds)) }
    else { Fail ('type check (pyright) failed / 실패 ' + (Format-Secs $r.Seconds)) $r.Lines }

    $r = Invoke-Proc $uvExe @('run', '--frozen', '--group', 'dev', 'ruff', 'check', 'gatekit') $ruffTimeout $kit
    if ($r.TimedOut) { Fail-Timeout 'lint (ruff)' $ruffTimeout $r }
    elseif ($r.Code -eq 0) { Say 'ok' ('lint (ruff): ' + (Get-LastLine $r) + ' ' + (Format-Secs $r.Seconds)) }
    else { Fail ('lint (ruff) failed / 실패 ' + (Format-Secs $r.Seconds)) $r.Lines }
}

$totalWatch.Stop()
$tail = ' ' + (Format-Secs $totalWatch.Elapsed.TotalSeconds)
if ($Fast) { $tail = ' - 빠른 검사, 통합 테스트 제외 / quick check, integration tests skipped' + $tail }
if ($failCount -gt 0) {
    Say 'fail' ($failCount.ToString() + ' check(s) failed / 검사 실패' + $tail)
    exit 1
}
Say 'ok' ('all configured checks passed / 설정된 검사 모두 통과' + $tail)
exit 0
