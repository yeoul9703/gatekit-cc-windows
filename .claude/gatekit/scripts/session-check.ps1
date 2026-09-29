# gatekit SessionStart environment check (Windows PowerShell 5.1 compatible).
# Prints nothing when everything is fine. On a problem it prints ONE JSON object:
#   systemMessage                          -> shown to the user
#   hookSpecificOutput.additionalContext   -> shown to Claude
# It never runs `uv sync` or winget (a network call must not block session start),
# spawns no process, stays under a shared 8 second budget, and always exits 0.
# Same rule as setup.ps1: a program counts as present only if it is on the PATH of THIS
# session. If it is visible only after merging the registry PATH (Machine + User) the
# message says "installed but not visible: restart the Claude app" instead of "not found".
# (GATEKIT_SETUP_REGISTRY_PATH replaces the registry value; used by tests.)
# Non-ASCII text is emitted as \uXXXX so the output does not depend on the
# console code page.
$ErrorActionPreference = 'Stop'

function ConvertTo-JsonString([string]$s) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in $s.ToCharArray()) {
        $code = [int]$ch
        if ($ch -eq '"') { [void]$sb.Append('\"') }
        elseif ($ch -eq '\') { [void]$sb.Append('\\') }
        elseif ($code -eq 10) { [void]$sb.Append('\n') }
        elseif ($code -eq 13) { }
        elseif ($code -lt 32 -or $code -gt 126) { [void]$sb.AppendFormat('\u{0:x4}', $code) }
        else { [void]$sb.Append($ch) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$budgetMs = 8000      # the whole check must stay well under 10 seconds

# Only lookups that cannot hang for long: no winget, no network, no child process.
# Each step is skipped once the shared time budget is used up.
function Test-Budget { return ($sw.ElapsedMilliseconds -lt $budgetMs) }

# Looks the program up on the PATH after merging the registry PATH; never changes the session.
function Test-RegistryVisible([string]$name) {
    if ($env:GATEKIT_SETUP_KEEP_PATH -eq '1') { return $false }
    $saved = $env:Path
    try {
        if ($env:GATEKIT_SETUP_REGISTRY_PATH) {
            $reg = $env:GATEKIT_SETUP_REGISTRY_PATH
        } else {
            $reg = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
        }
        $env:Path = $reg + ';' + $saved
        return [bool](Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)
    } catch { return $false }
    finally { $env:Path = $saved }
}

try {
    $kitRoot = Split-Path -Parent $PSScriptRoot        # .claude\gatekit
    $venvDir = Join-Path $kitRoot '.venv'
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'
    $problems = @()

    if ((Test-Budget) -and -not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
        if (Test-RegistryVisible 'uv') {
            $problems += 'uv: installed but not visible in this session - close the Claude app (VS Code window) completely and open it again / 설치돼 있지만 이 창에서는 보이지 않습니다 - Claude 앱을 완전히 닫고 다시 여세요'
        } else {
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
                        if (([int]$Matches[2] * 1000 + [int]$Matches[3]) -lt 3014) {
                            $problems += '.claude/gatekit/.venv: Python is older than 3.14 (pyvenv.cfg), rebuild it with /gatekit:setup / .venv 의 Python 이 3.14 보다 낮습니다 - /gatekit:setup 으로 다시 만드세요'
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
    if ((Test-Budget) -and -not (Get-Command claude -CommandType Application -ErrorAction SilentlyContinue)) {
        if (Test-RegistryVisible 'claude') {
            $problems += 'claude CLI: installed but not visible in this session - close the Claude app completely and open it again / 설치돼 있지만 이 창에서는 보이지 않습니다 - Claude 앱을 완전히 닫고 다시 여세요'
        } else {
            $problems += 'claude CLI: not found on PATH (workers cannot start) / PATH 에 없음 (워커 실행 불가)'
        }
    }

    if ($problems.Count -gt 0) {
        $list = ($problems | ForEach-Object { '- ' + $_ }) -join "`n"
        $user = "gatekit: environment problem / 환경 문제`n" + $list + "`nType /gatekit:setup in the chat. / 채팅에 /gatekit:setup 을 입력하세요."
        $ctx = "gatekit environment check failed:`n" + $list + "`nTell the user to type /gatekit:setup in the chat (gatekit 게이트 훅이 지금 동작하지 않을 수 있음). Do not install anything before the user agrees in the chat."
        $json = '{"systemMessage":' + (ConvertTo-JsonString $user) +
            ',"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":' +
            (ConvertTo-JsonString $ctx) + '}}'
        [Console]::Out.Write($json)
    }
} catch {
    # A broken check must never break the session.
}
exit 0
