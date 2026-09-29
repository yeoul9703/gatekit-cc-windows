# gatekit SessionStart environment check (Windows PowerShell 5.1 compatible).
# Prints nothing when everything is fine. On a problem it prints ONE JSON object:
#   systemMessage                          -> shown to the user
#   hookSpecificOutput.additionalContext   -> shown to Claude
# It never runs `uv sync` (a network download must not block session start) and
# always exits 0. Non-ASCII text is emitted as \uXXXX so the output does not
# depend on the console code page.
$ErrorActionPreference = 'Stop'

function ConvertTo-JsonString([string]$s) {
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in $s.ToCharArray()) {
        $code = [int]$ch
        if ($ch -eq '"') { [void]$sb.Append('\"') }
        elseif ($ch -eq '\') { [void]$sb.Append('\') }
        elseif ($code -eq 10) { [void]$sb.Append('\n') }
        elseif ($code -eq 13) { }
        elseif ($code -lt 32 -or $code -gt 126) { [void]$sb.AppendFormat('\u{0:x4}', $code) }
        else { [void]$sb.Append($ch) }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

try {
    $kitRoot = Split-Path -Parent $PSScriptRoot        # .claude\gatekit
    $venvPy = Join-Path $kitRoot '.venv\Scripts\python.exe'
    $problems = @()

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $problems += 'uv: not found / uv 를 찾을 수 없습니다'
    }
    if (-not (Test-Path -LiteralPath $venvPy)) {
        $problems += '.claude/gatekit/.venv: missing, so gatekit hooks are silently inactive / 없음 - gatekit 훅이 동작하지 않습니다'
    }
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        $problems += 'claude CLI: not found on PATH (workers cannot start) / PATH 에 없음 (워커 실행 불가)'
    }

    if ($problems.Count -gt 0) {
        $list = ($problems | ForEach-Object { '- ' + $_ }) -join "`n"
        $user = "gatekit: environment problem / 환경 문제`n" + $list + "`nRun /gatekit:setup to fix. / /gatekit:setup 을 실행하세요."
        $ctx = "gatekit environment check failed:`n" + $list + "`nTell the user, and run /gatekit:setup (gatekit 게이트 훅이 지금 동작하지 않을 수 있음). If uv is missing, show the install command and install only after the user agrees."
        $json = '{"systemMessage":' + (ConvertTo-JsonString $user) +
            ',"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":' +
            (ConvertTo-JsonString $ctx) + '}}'
        [Console]::Out.Write($json)
    }
} catch {
    # A broken check must never break the session.
}
exit 0
