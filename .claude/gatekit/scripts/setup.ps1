# gatekit setup (Windows PowerShell 5.1 compatible).
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1
#
# Steps, one line each ([ok] / [warn] / [fail]):
#   1 uv present   2 uv sync --frozen   3 .gatekit/config.json   4 claude CLI
#   5 node/npm (information only)       6 doctor
# Exit code: 0 = ready, 1 = a step failed, 2 = uv is missing (this script only
# PRINTS the install commands; install uv only after the user agrees).

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONUTF8 = '1'

$kit = Split-Path -Parent $PSScriptRoot            # <project>\.claude\gatekit
$projectRoot = Split-Path -Parent (Split-Path -Parent $kit)
$venvPy = Join-Path $kit '.venv\Scripts\python.exe'
$launcher = Join-Path $kit 'bin\gatekit.py'
$failed = $false

function Say([string]$tag, [string]$msg) { Write-Host ('[' + $tag + '] ' + $msg) }

Say 'info' ('project: ' + $projectRoot)

# 1. uv ---------------------------------------------------------------------
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Say 'fail' 'uv not found / uv 를 찾을 수 없습니다. gatekit needs uv (it fetches Python by itself).'
    Write-Host ''
    Write-Host 'Install uv (run ONE of these, only after the user agrees) / 사용자 허락 후 아래 중 하나를 실행하세요:'
    Write-Host '  winget install --id=astral-sh.uv -e'
    Write-Host '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Write-Host 'Then open a new terminal and run this script again. / 설치 후 새 터미널에서 다시 실행하세요.'
    exit 2
}
$uvVersion = (& uv --version 2>&1 | ForEach-Object { "$_" }) -join ' '
Say 'ok' ('uv: ' + $uvVersion)

# 2. uv sync ----------------------------------------------------------------
$syncOut = & uv sync --project $kit --frozen 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $venvPy)) {
    $pyVersion = (& $venvPy -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>&1 | ForEach-Object { "$_" }) -join ''
    Say 'ok' ('uv sync --frozen: .venv ready, python ' + $pyVersion + ' / .venv 준비됨')
} else {
    Say 'fail' 'uv sync --frozen failed / 실패 (the first run needs network to fetch Python):'
    $syncOut | Select-Object -Last 8 | ForEach-Object { Write-Host ('       ' + $_) }
    exit 1
}

# 3. .gatekit/config.json ---------------------------------------------------
$cfg = Join-Path $projectRoot '.gatekit\config.json'
if (Test-Path -LiteralPath $cfg) {
    Say 'ok' '.gatekit/config.json exists, left as is / 이미 있어 그대로 둡니다'
} else {
    $out = & $venvPy $launcher workers set-default claude --root $projectRoot 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $cfg)) {
        Say 'ok' '.gatekit/config.json created (default worker: claude) / 생성함'
    } else {
        Say 'fail' '.gatekit/config.json could not be created / 생성 실패'
        $out | Select-Object -Last 5 | ForEach-Object { Write-Host ('       ' + $_) }
        $failed = $true
    }
}

# 4. claude CLI -------------------------------------------------------------
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Say 'ok' 'claude CLI found on PATH / claude CLI 확인'
} else {
    Say 'warn' 'claude CLI not found on PATH: workers cannot start / PATH 에 claude 가 없어 워커를 실행할 수 없습니다'
}

# 5. node / npm (information only) ------------------------------------------
if (Test-Path -LiteralPath (Join-Path $projectRoot 'package.json')) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    $nodeText = 'missing / 없음'
    $npmText = 'missing / 없음'
    if ($node) { $nodeText = (& node --version 2>&1 | ForEach-Object { "$_" }) -join '' }
    if ($npm) { $npmText = (& npm --version 2>&1 | ForEach-Object { "$_" }) -join '' }
    Say 'info' ('package.json found; node ' + $nodeText + ', npm ' + $npmText +
        ' (gatekit itself does not need Node; npm is for your project gates / gatekit 자체는 Node 불필요, 사용자 프로젝트 게이트용)')
} else {
    Say 'info' 'no package.json in the project root: node/npm not checked / package.json 없음, node/npm 점검 생략'
}

# 6. doctor -----------------------------------------------------------------
$doctorOut = & $venvPy $launcher doctor --root $projectRoot 2>&1 | ForEach-Object { "$_" }
$doctorCode = $LASTEXITCODE
$doctorOut | ForEach-Object { Write-Host ('       ' + $_) }
if ($doctorCode -eq 0) {
    Say 'ok' 'doctor: no failing axis / 실패한 축 없음'
} else {
    Say 'fail' 'doctor: at least one axis failed (see the fix lines above) / 실패한 축 있음'
    $failed = $true
}

if ($failed) { exit 1 }
exit 0
