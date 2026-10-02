# gatekit SessionStart environment check (Windows PowerShell 5.1 compatible).
# Prints nothing when everything is fine. On a problem it prints ONE JSON object:
#   systemMessage                          -> shown to the user
#   hookSpecificOutput.additionalContext   -> shown to Claude
# It never runs `uv sync` or winget (a network call must not block session start),
# spawns no process, stays under a shared 8 second budget, and always exits 0.
# Same rule as setup.ps1, taken from the same file (common.ps1): a program counts as present only
# if it is on the PATH of THIS session. If it is visible only after merging the registry PATH
# (Machine + User) the message says "installed but not visible: close Claude Code completely and open it again" instead
# of "not found", followed once by where to quit the desktop app (its icon in the notification area). (GATEKIT_SETUP_REGISTRY_PATH replaces the registry value; used by tests.)
# PowerShell 7 follows the same product rule as setup.ps1 (Get-PwshProduct in common.ps1): a pwsh on
# PATH is not enough when only a preview build is installed. Here the rule is the light part only:
# the Windows package lookup (Get-AppxPackage, about half a second, no network), the MSI folder and
# the version text stored inside the pwsh.exe files on PATH. No pwsh is started. When none of
# these can tell (an unknown kind of install), nothing is reported.
# (GATEKIT_SETUP_PWSH_PACKAGES replaces the package lookup; used by tests.)
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
    # One wording for a program that is installed but not on this session's PATH (the same
    # sentence setup.ps1 prints). When any problem needs a reopen, $trayNote is added once: the
    # desktop app keeps running after its window is closed, so closing the window is not enough.
    $reopen = $false
    $notVisible = 'installed but not visible in this session - close Claude Code completely (the desktop app, the VS Code window, or the terminal it runs in) and open it again / 설치돼 있지만 이 창에서는 보이지 않습니다 - Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 여세요'
    $trayNote = 'The desktop app keeps running after its window is closed: quit it from the Claude icon in the notification area (bottom right of the taskbar). / 데스크톱 앱은 창을 닫아도 남아 있으니 작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료하세요.'
    # Minimum .venv Python: scripts/packages.json python_min (the single source), 3.14 if unreadable.
    $pyMinMajor = 3
    $pyMinMinor = 14
    # The package names of the stable and the preview PowerShell 7 come from the same file
    # (appx_name / appx_preview_name); unreadable: no package lookup.
    $pwshStableName = ''
    $pwshPreviewName = ''
    try {
        $pkgData = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'packages.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
        $pm = [string]$pkgData.python_min
        if ($pm -match '^(\d+)\.(\d+)$') { $pyMinMajor = [int]$Matches[1]; $pyMinMinor = [int]$Matches[2] }
        foreach ($pk in @($pkgData.packages)) {
            if ("$($pk.key)" -eq 'pwsh') { $pwshStableName = "$($pk.appx_name)"; $pwshPreviewName = "$($pk.appx_preview_name)" }
        }
    } catch { }
    $pyMinText = "$pyMinMajor.$pyMinMinor"

    if (Test-Budget) {
        $where = (Get-App 'uv').where
        if ($where -eq 'registry') {
            $problems += 'uv: ' + $notVisible
            $reopen = $true
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
                            $problems += ('.claude/gatekit/.venv: Python is older than ' + $pyMinText + ' (pyvenv.cfg), rebuild it with /gatekit-setup / .venv 의 Python 이 ' + $pyMinText + ' 보다 낮습니다 - /gatekit-setup 으로 다시 만드세요')
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
        $pwshFound = Get-App 'pwsh'
        $where = $pwshFound.where
        if ($where -eq 'registry') {
            $problems += 'PowerShell 7: ' + $notVisible
            $reopen = $true
        } elseif ($where -eq 'none') {
            $problems += 'PowerShell 7 (pwsh): not found / PowerShell 7 을 찾을 수 없습니다'
        } else {
            # pwsh is on PATH: is a STABLE product installed, or only a preview build?
            $product = Get-PwshProduct $pwshStableName $pwshPreviewName
            if (-not $product.stable) {
                $stableOnPath = $false
                $previewSeen = $product.preview
                foreach ($app in (@($pwshFound.apps) | Select-Object -First 3)) {
                    $kind = Get-PwshFileKind $app.Source $pwshPreviewName
                    if ($kind -eq 'stable') { $stableOnPath = $true }
                    if ($kind -eq 'preview') { $previewSeen = $true }
                }
                if ($previewSeen -and -not $stableOnPath) {
                    $problems += 'PowerShell 7: only a preview build is installed, the stable one is missing / 미리보기(preview) 버전만 있고 안정판이 없습니다'
                }
            }
        }
    }
    # The claude CLI is named only in a project whose settings start it (Test-CliRequired in
    # common.ps1: build.execution = "worker", or a backend in verify.evaluator). With the default
    # settings nothing runs it, so a PC with only the desktop app or the VS Code extension is fine.
    if ((Test-Budget) -and (Test-CliRequired (Split-Path -Parent (Split-Path -Parent $kitRoot)))) {
        $where = (Get-App 'claude').where
        if ($where -eq 'registry') {
            $problems += 'claude CLI: ' + $notVisible
            $reopen = $true
        } elseif ($where -eq 'none') {
            $problems += 'claude CLI: not found on PATH, and this project is set to run it (build.execution or verify.evaluator in .gatekit/config.json) / PATH 에 없음 - 이 프로젝트 설정(.gatekit/config.json 의 build.execution 또는 verify.evaluator)은 이 명령을 실행합니다'
        }
    }

    if ($problems.Count -gt 0) {
        $list = ($problems | ForEach-Object { '- ' + $_ }) -join "`n"
        if ($reopen) { $list = $list + "`n" + $trayNote }
        $user = "gatekit: environment problem / 환경 문제`n" + $list + "`nType /gatekit-setup in the chat. / 채팅에 /gatekit-setup 을 입력하세요."
        $ctx = "gatekit environment check failed:`n" + $list + "`nTell the user to type /gatekit-setup in the chat (gatekit 게이트 훅이 지금 동작하지 않을 수 있음). Do not install anything before the user agrees in the chat."
        $out = [ordered]@{ systemMessage = $user
            hookSpecificOutput = [ordered]@{ hookEventName = 'SessionStart'; additionalContext = $ctx } }
        [Console]::Out.Write((ConvertTo-AsciiJson (ConvertTo-Json -InputObject $out -Depth 3 -Compress)))
    }
} catch {
    # A broken check must never break the session.
}
exit 0
