# gatekit verify: everything a change must pass, in one command.
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/verify.ps1
# Exit code 1 if any check is [fail]. [unverified] (a check that is not
# configured) does not fail the run but is never reported as ok.
# Windows PowerShell 5.1 compatible.

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONUTF8 = '1'

$kit = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $kit)
$venvPy = Join-Path $kit '.venv\Scripts\python.exe'
$launcher = Join-Path $kit 'bin\gatekit.py'
$failCount = 0

function Say([string]$tag, [string]$msg) { Write-Host ('[' + $tag + '] ' + $msg) }
function Fail([string]$msg, $lines) {
    $script:failCount++
    Say 'fail' $msg
    if ($lines) { $lines | Select-Object -Last 15 | ForEach-Object { Write-Host ('       ' + $_) } }
}

if (-not (Test-Path -LiteralPath $venvPy)) {
    Say 'fail' '.claude/gatekit/.venv missing: run scripts/setup.ps1 first / .venv 없음, 먼저 setup.ps1 실행'
    exit 1
}

# 1. syntax -------------------------------------------------------------------
$out = & $venvPy -m compileall -q $kit 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -eq 0) { Say 'ok' 'compileall: no syntax errors / 문법 오류 없음' }
else { Fail 'compileall failed / 실패' $out }

# 2. unit tests ---------------------------------------------------------------
Push-Location $kit
$out = & $venvPy -m unittest discover -s tests 2>&1 | ForEach-Object { "$_" }
$code = $LASTEXITCODE
Pop-Location
$ran = ($out | Where-Object { $_ -match '^Ran \d+ tests?' } | Select-Object -Last 1)
if ($code -eq 0) { Say 'ok' ('unittest: ' + $ran + ', OK') }
else { Fail ('unittest failed / 실패: ' + $ran) $out }

# 3. doctor -------------------------------------------------------------------
$out = & $venvPy $launcher doctor --root $projectRoot 2>&1 | ForEach-Object { "$_" }
$code = $LASTEXITCODE
if ($code -eq 0) {
    # Exit 0 only means "no axis failed"; keep unverified/warn visible.
    $tag = 'ok'
    if ($out[0] -match '\s\S\s(ok|warn|unverified) \(root') { $tag = $Matches[1] }
    Say $tag ('doctor: ' + $out[0])
}
else { Fail 'doctor: an axis failed / 실패한 축 있음' $out }

# 4. settings.json ------------------------------------------------------------
$settings = Join-Path $projectRoot '.claude\settings.json'
$out = & $venvPy -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))" $settings 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -eq 0) { Say 'ok' '.claude/settings.json is valid JSON / 유효한 JSON' }
else { Fail '.claude/settings.json is not valid JSON / JSON 오류' $out }

# 5. type check and lint ------------------------------------------------------
# Not in the dev group yet: report unverified, never ok.
Say 'unverified' 'type check: not configured / 타입검사 도구 미설정'
Say 'unverified' 'lint: not configured / 린트 도구 미설정'

if ($failCount -gt 0) {
    Say 'fail' ($failCount.ToString() + ' check(s) failed / 검사 실패')
    exit 1
}
Say 'ok' 'all configured checks passed / 설정된 검사 모두 통과'
exit 0
