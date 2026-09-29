# gatekit SessionStart environment check (Windows PowerShell 5.1 compatible).
# Prints nothing when everything is fine. On a problem it prints ONE JSON object:
#   systemMessage                          -> shown to the user
#   hookSpecificOutput.additionalContext   -> shown to Claude
# It never runs `uv sync` or winget (a network call must not block session start),
# spawns no process, stays under a shared 8 second budget, and always exits 0.
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

try {
    $kitRoot = Split-Path -Parent $PSScriptRoot        # .claude\gatekit
    $venvDir = Join-Path $kitRoot '.venv'
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'
    $problems = @()

    if ((Test-Budget) -and -not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
        $problems += 'uv: not found / uv 를 찾을 수 없습니다'
    }
    if (Test-Budget) {
        if (-not (Test-Path -LiteralPath $venvPy)) {
            $problems += '.claude/gatekit/.venv: missing, so gatekit hooks are silently inactive / 없음 - gatekit 훅이 동작하지 않습니다'
        } else {
            # pyvenv.cfg "home" points at the Python the venv was built from; if that
            # folder is gone the venv python cannot start and every hook is silent.
            $cfgFile = Join-Path $venvDir 'pyvenv.cfg'
            if (Test-Path -LiteralPath $cfgFile) {
                foreach ($line in (Get-Content -LiteralPath $cfgFile -ErrorAction SilentlyContinue)) {
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
        $problems += 'claude CLI: not found on PATH (workers cannot start) / PATH 에 없음 (워커 실행 불가)'
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
