# gatekit SessionStart environment check (Windows PowerShell 5.1 compatible).
# Prints nothing when everything is fine. On a problem it prints ONE JSON object:
#   systemMessage                          -> shown to the user
#   hookSpecificOutput.additionalContext   -> shown to Claude
# It never runs `uv sync` or winget (a network call must not block session start),
# spawns no process, stays under a shared 8 second budget, and always exits 0.
# Same rule as setup.ps1, taken from the same file (common.ps1): a program counts as present only
# if it is on the PATH of THIS session. If it is visible only after merging the registry PATH
# (Machine + User) the message says "installed but not visible: restart the Claude app" instead
# of "not found". (GATEKIT_SETUP_REGISTRY_PATH replaces the registry value; used by tests.)
# Non-ASCII text is emitted as \uXXXX (ConvertTo-AsciiJson) so the output does not depend on the
# console code page.
$ErrorActionPreference = 'Stop'

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$budgetMs = 8000      # the whole check must stay well under 10 seconds

# Only lookups that cannot hang for long: no winget, no network, no child process.
# Each step is skipped once the shared time budget is used up.
function Test-Budget { return ($sw.ElapsedMilliseconds -lt $budgetMs) }

try {
    . "$PSScriptRoot\common.ps1"        # PATH rule and ASCII-only JSON, shared with setup.ps1
    $kitRoot = Split-Path -Parent $PSScriptRoot        # .claude\gatekit
    $venvDir = Join-Path $kitRoot '.venv'
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'
    $problems = @()
    # Minimum .venv Python: scripts/packages.json python_min (the single source), 3.14 if unreadable.
    $pyMinMajor = 3
    $pyMinMinor = 14
    try {
        $pm = [string](Get-Content -LiteralPath (Join-Path $PSScriptRoot 'packages.json') -Raw -Encoding UTF8 | ConvertFrom-Json).python_min
        if ($pm -match '^(\d+)\.(\d+)$') { $pyMinMajor = [int]$Matches[1]; $pyMinMinor = [int]$Matches[2] }
    } catch { }
    $pyMinText = "$pyMinMajor.$pyMinMinor"

    if (Test-Budget) {
        $where = (Get-App 'uv').where
        if ($where -eq 'registry') {
            $problems += 'uv: installed but not visible in this session - close the Claude app (VS Code window) completely and open it again / 설치돼 있지만 이 창에서는 보이지 않습니다 - Claude 앱을 완전히 닫고 다시 여세요'
        } elseif ($where -eq 'none') {
            $problems += 'uv: not found / uv 를 찾을 수 없습니다'
        }
    }
    if (Test-Budget) {
        if (-not (Test-Path -LiteralPath $venvPy)) {
            $problems += '.claude/gatekit/.venv: missing, so gatekit hooks are silently inactive / 없음 - gatekit 훅이 동작하지 않습니다'
        } elseif ((Get-Item -LiteralPath $venvPy).Length -eq 0) {
            $problems += '.claude/gatekit/.venv: python.exe is 0 bytes (damaged), so the hooks cannot start / python.exe 가 0바이트로 손상되어 훅이 시작되지 않습니다'
        } else {
            # pyvenv.cfg "home" points at the Python the venv was built from; if that
            # folder is gone the venv python cannot start and every hook is silent.
            $cfgFile = Join-Path $venvDir 'pyvenv.cfg'
            if (Test-Path -LiteralPath $cfgFile) {
                foreach ($line in (Get-Content -LiteralPath $cfgFile -ErrorAction SilentlyContinue)) {
                    if ($line -match '^\s*version(_info)?\s*=\s*(\d+)\.(\d+)') {
                        if (([int]$Matches[2] * 1000 + [int]$Matches[3]) -lt ($pyMinMajor * 1000 + $pyMinMinor)) {
                            $problems += ('.claude/gatekit/.venv: Python is older than ' + $pyMinText + ' (pyvenv.cfg), rebuild it with /gatekit:setup / .venv 의 Python 이 ' + $pyMinText + ' 보다 낮습니다 - /gatekit:setup 으로 다시 만드세요')
                        }
                    }
                    if ($line -match '^\s*home\s*=\s*(.+?)\s*$') {
                        if (-not (Test-Path -LiteralPath $Matches[1])) {
                            $problems += '.claude/gatekit/.venv: its Python folder is gone (pyvenv.cfg home), so the hooks cannot start / .venv 가 가리키는 Python 폴더가 없어 훅이 시작되지 않습니다'
                        }
                    }
                }
            }
        }
    }
    if (Test-Budget) {
        $where = (Get-App 'claude').where
        if ($where -eq 'registry') {
            $problems += 'claude CLI: installed but not visible in this session - close the Claude app completely and open it again / 설치돼 있지만 이 창에서는 보이지 않습니다 - Claude 앱을 완전히 닫고 다시 여세요'
        } elseif ($where -eq 'none') {
            $problems += 'claude CLI: not found on PATH (workers cannot start) / PATH 에 없음 (워커 실행 불가)'
        }
    }

    if ($problems.Count -gt 0) {
        $list = ($problems | ForEach-Object { '- ' + $_ }) -join "`n"
        $user = "gatekit: environment problem / 환경 문제`n" + $list + "`nType /gatekit:setup in the chat. / 채팅에 /gatekit:setup 을 입력하세요."
        $ctx = "gatekit environment check failed:`n" + $list + "`nTell the user to type /gatekit:setup in the chat (gatekit 게이트 훅이 지금 동작하지 않을 수 있음). Do not install anything before the user agrees in the chat."
        $out = [ordered]@{ systemMessage = $user
            hookSpecificOutput = [ordered]@{ hookEventName = 'SessionStart'; additionalContext = $ctx } }
        [Console]::Out.Write((ConvertTo-AsciiJson (ConvertTo-Json -InputObject $out -Depth 3 -Compress)))
    }
} catch {
    # A broken check must never break the session.
}
exit 0
