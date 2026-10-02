# gatekit setup (Windows PowerShell 5.1 compatible).
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 [switches]
#
# Switches
#   (none)            check only: nothing is installed or updated. The one exception is the
#                     project's own .venv: if it is missing, ONE `uv sync --frozen --no-dev
#                     --no-python-downloads` is tried (it never downloads Python and never
#                     deletes anything). Everything else needs a name in -Install / -Update.
#   -Install <list>   install the listed items. Allowed names: winget, pwsh, uv, claude, git, venv.
#                     "winget" is always done first: it asks Windows to register the App Installer
#                     that is already on the PC and, only if that is not enough, downloads the
#                     Microsoft.WinGet.Client module into the user's folders and runs
#                     Repair-WinGetPackageManager (no administrator rights). Still missing: the
#                     Microsoft Store link and exit 2 (exit 4 when policy or the network blocks it).
#                     "venv" builds .claude/gatekit/.venv WITH downloads (Python and packages,
#                     tens of MB) and deletes and rebuilds a broken .venv. Only this switch may.
#   -Update <list>    update the listed programs (pwsh, uv, claude, git; not venv, not winget).
#   -Reinstall <list> reinstall the listed programs. Allowed names: uv, pwsh, claude only (git is
#                     never reinstalled here; venv is rebuilt with -Install venv). uv: winget
#                     --force when uv came from winget, otherwise the official installer script
#                     (this also repairs a broken uv-receipt.json). pwsh: winget MSIX --force.
#                     claude: the official installer script. The version is read again afterwards.
#   -RetryFailed      retry ONLY the items recorded as failed in .gatekit/runs/setup-last.json, with the
#                     same action (install / update / reinstall). Nothing recorded: an info line.
#                     A failed action is recorded there (time, item, action, exit code, class,
#                     message) and removed again when the same item succeeds.
#   -Status           check only, but skip the .venv / config / doctor steps: the programs, the
#                     package table (installed version, update available, install method) and the
#                     failure record. Cannot be combined with -Install/-Update/-Reinstall/-RetryFailed.
#   -Json             print ONE ASCII-only JSON object {exit_code, exit_meaning, items:[{id,level,
#                     name,verdict,detail,action,hints}]}. Non-ASCII text is written as \uXXXX.
#                     Every line (skipped / done / progress too) is one item.
#   -Lang ko|en       output language, one language per line. Default: ko if the Windows UI
#                     language is Korean, otherwise en.
# Any other name in -Install / -Update / -Reinstall is refused with exit code 1.
# -Install / -Update / -Reinstall are the user's permission: the chat asked first. Only calls
# made for a listed name pass --accept-source-agreements / --accept-package-agreements.
# Only user-scope installs run automatically. Anything that needs administrator
# rights (git) is never run here; the script prints what to do instead.
#
# Every line: [ok|warn|fail|unverified|info] name: result - next action
# Nothing here asks a question (no Read-Host); winget always gets --disable-interactivity.
# Every external call has a timeout; on timeout the whole process tree is killed (taskkill /T /F).
#
# The check looks at the PATH of THIS session only (the same rule as session-check.ps1: both use
# Get-App from common.ps1). A program that is visible only after merging the registry PATH
# (Machine + User) is reported as warn and exit 3: close Claude Code completely (the desktop app,
# the VS Code window, or the terminal it runs in) and open it again.
#
# PowerShell 7 is judged by the installed stable PRODUCT, not by the PATH order: the Windows package
# (Get-AppxPackage, names from packages.json), then the MSI folder <Program Files>\PowerShell\7, then
# the version text of the pwsh on PATH (no "-preview" suffix). A preview build alone does not count.
#
# Exit codes (when several problems mix, the FIRST matching row wins):
#   1  something failed that a permission cannot fix (bad switch, .venv or config
#      could not be built, doctor failed, an install failed for an unknown reason)
#   4  blocked by policy or network (winget policy block, no network, TLS, a group policy that
#      pins the execution policy to AllSigned / Restricted, or Windows refusing to start uv.exe
#      or the .venv python.exe because of an application control policy)
#   3  a program is installed but not visible in this session (PATH), or a reboot is
#      needed: close Claude Code completely and open it again
#   2  the user must allow or do something (a required program is missing or too
#      old, Python must be downloaded, .venv is broken, or a program needs administrator rights)
#   0  ready
# The claude CLI (S6) is recommended, not required: with the default settings nothing starts it
# (build.execution = "host", the reviewer is a subagent). Missing, not visible in this session or
# older than the recommended version is then a warn that leaves the exit code alone. It is
# required (missing: fail, exit 2; not visible: exit 3) only in a project whose
# .gatekit/config.json says build.execution = "worker" or names a backend in verify.evaluator
# (Test-CliRequired in common.ps1).
# Test hooks (environment): GATEKIT_SETUP_KEEP_PATH=1 never reads the registry PATH;
#   GATEKIT_SETUP_REGISTRY_PATH replaces the registry PATH value (these two are read by
#   common.ps1, so session-check.ps1 honors them too); GATEKIT_SETUP_SYNC_TIMEOUT
#   (seconds) replaces the 300 second uv sync limit; GATEKIT_SETUP_MIN_PYTHON (major.minor)
#   replaces the required 3.14 for the .venv Python; GATEKIT_SETUP_LIST_TIMEOUT (seconds) replaces
#   the 30 second `winget list` limit of the package table; GATEKIT_SETUP_OFFICIAL_RUNNER is an
#   executable run instead of the official installer script (it receives the script URL);
#   GATEKIT_SETUP_PWSH_PACKAGES replaces the Get-AppxPackage lookup of PowerShell 7: "none", or
#   "<package name>=<version>" pairs separated by ";" (an empty value counts as not set; read by
#   common.ps1, so session-check.ps1 honors it too);
#   GATEKIT_SETUP_WINGET_RUNNER is an executable run instead of the two winget install steps (it
#   receives "register" or "repair" and the package family name). The MSI folder is looked up
#   under the ProgramFiles environment variable, so a test can point it at a scratch folder.
#   GATEKIT_SETUP_EXECUTION_POLICY replaces Get-ExecutionPolicy -List: "<scope>=<policy>" pairs
#   separated by ";" (MachinePolicy, UserPolicy; a scope left out counts as Undefined);
#   GATEKIT_SETUP_LONG_PATHS (0 or 1) replaces the registry value LongPathsEnabled;
#   GATEKIT_SETUP_EXEC_DENIED lists program names (file name without extension, separated by
#   ";" or ",") that are not started and answer like a policy refusal (Windows error 1260).

param(
    [string[]]$Install = @(),
    [string[]]$Update = @(),
    [string[]]$Reinstall = @(),
    [switch]$RetryFailed,
    [switch]$Status,
    [switch]$Json,
    [string]$Lang = ''
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONUTF8 = '1'

$kit = Split-Path -Parent $PSScriptRoot            # <project>\.claude\gatekit
$projectRoot = Split-Path -Parent (Split-Path -Parent $kit)
$venvDir = Join-Path $kit '.venv'
$venvPy = Join-Path $venvDir 'Scripts\python.exe'
$launcher = Join-Path $kit 'bin\gatekit.py'
$dash = [string][char]0x2014
$allowed = @('winget', 'pwsh', 'uv', 'claude', 'git', 'venv')
$allowedReinstall = @('uv', 'pwsh', 'claude')

# The PATH rule and the ASCII-only JSON live in common.ps1 (shared with session-check.ps1).
# Nothing below can run without it.
# If it cannot be read, no shared function exists yet (no PATH lookup, no language helper), so the
# advice names both ways: with Git, and without it (a zip download has no Git to restore from).
try { . "$PSScriptRoot\common.ps1" } catch {
    $commonRel = '.claude/gatekit/scripts/common.ps1'
    $commonWhy = [regex]::Replace("$($_.Exception.Message)", '[^\x20-\x7E]', '?')
    $commonKo = ($Lang -eq 'ko')
    if (-not $Lang) { try { $commonKo = ((Get-UICulture).TwoLetterISOLanguageName -eq 'ko') } catch { } }
    if ($Json) {
        $commonItem = [ordered]@{ id = 'common'; level = 'required'; name = 'scripts/common.ps1'; verdict = 'fail'
            detail = ('could not be read: ' + $commonWhy)
            action = 'restore the file'
            hints = @(('with Git: git checkout ' + $commonRel), ('without Git: download the repository again and overwrite ' + $commonRel)) }
        Write-Output (ConvertTo-Json -InputObject ([ordered]@{ exit_code = 1; exit_meaning = 'failed'; items = @($commonItem) }) -Depth 4)
    } elseif ($commonKo) {
        Write-Host ('[fail] scripts/common.ps1: ' + $commonWhy)
        Write-Host ('       Git 이 있으면: git checkout ' + $commonRel)
        Write-Host ('       Git 이 없으면: 저장소를 다시 내려받아 이 파일을 덮어쓰세요 (' + $commonRel + ')')
    } else {
        Write-Host ('[fail] scripts/common.ps1: ' + $commonWhy)
        Write-Host ('       with Git: git checkout ' + $commonRel)
        Write-Host ('       without Git: download the repository again and overwrite this file (' + $commonRel + ')')
    }
    exit 1
}

# scripts/packages.json is the single source for winget ids, installer types, official script
# urls and minimum versions. Nothing below hard-codes them.
$script:pkgs = @{}
$script:pkgLoadError = ''
try {
    $pkgData = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'packages.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
    foreach ($pk in @($pkgData.packages)) { $script:pkgs[[string]$pk.key] = $pk }
} catch { $script:pkgLoadError = "$_" }
$uvMinimum = [version]'0.0.0'
$claudeRecommended = [version]'0.0.0'
$pwshMinimum = [version]'0.0.0'
try {
    if ($script:pkgs['uv'].min_version) { $uvMinimum = [version]$script:pkgs['uv'].min_version }
    if ($script:pkgs['claude'].min_version) { $claudeRecommended = [version]$script:pkgs['claude'].min_version }
    if ($script:pkgs['pwsh'].min_version) { $pwshMinimum = [version]$script:pkgs['pwsh'].min_version }
} catch { }
$pythonMinimum = [version]'3.14'
try { if ("$($pkgData.python_min)" -match '^\d+\.\d+$') { $pythonMinimum = [version]$pkgData.python_min } } catch { }
if ($env:GATEKIT_SETUP_MIN_PYTHON -match '^\d+\.\d+$') { $pythonMinimum = [version]$env:GATEKIT_SETUP_MIN_PYTHON }
$syncTimeout = 300
$listTimeout = 30
if ($env:GATEKIT_SETUP_LIST_TIMEOUT -match '^\d+$') { $listTimeout = [int]$env:GATEKIT_SETUP_LIST_TIMEOUT }
if ($env:GATEKIT_SETUP_SYNC_TIMEOUT -match '^\d+$') { $syncTimeout = [int]$env:GATEKIT_SETUP_SYNC_TIMEOUT }

$script:sessionPath = $env:Path                     # the PATH this session was started with
$script:items = New-Object System.Collections.ArrayList
$script:flags = @{ fail = $false; blocked = $false; restart = $false; needs = $false }
$script:done = New-Object System.Collections.ArrayList
$script:failedActions = New-Object System.Collections.ArrayList
$script:langMode = 'en'
$script:lastScriptFail = $null
$script:lastWingetFail = $null
$script:wingetInstall = ''                          # '' / failed / restart: how -Install winget ended in this run
$script:venvDenied = 0                              # Windows error number when the .venv python.exe was refused by policy
$script:showSummary = $true
$script:currentAction = ''
$script:agreementOk = $false
$script:pkgInfo = @{}
$script:failureFile = Join-Path $projectRoot '.gatekit\runs\setup-last.json'
try { if ((Get-UICulture).TwoLetterISOLanguageName -eq 'ko') { $script:langMode = 'ko' } } catch { }

# ---- output helpers -----------------------------------------------------------
function T([string]$ko, [string]$en) {
    if ($script:langMode -eq 'ko') { return $ko }
    return $en
}

function Out-Human([string]$text) { if (-not $Json) { Write-Host $text } }

function Add-Item([string]$id, [string]$level, [string]$name, [string]$verdict,
                  [string]$detail, [string]$action = '', [string[]]$hints = @()) {
    $item = [pscustomobject]@{ id = $id; level = $level; name = $name; verdict = $verdict;
                               detail = $detail; action = $action; hints = @($hints) }
    [void]$script:items.Add($item)
    $line = '[' + $verdict + '] ' + $name + ': ' + $detail
    if ($action) { $line = $line + ' ' + $dash + ' ' + $action }
    Out-Human $line
    foreach ($h in $hints) { Out-Human ('       ' + $h) }
}

# A progress / skipped / done line: also recorded in items (-Json shows every line).
function Say([string]$verdict, [string]$id, [string]$name, [string]$detail) {
    Add-Item $id 'info' $name $verdict $detail
}

function Set-Flag([string]$name) { $script:flags[$name] = $true }

# How to get a missing or damaged kit file back. Git on the PATH of this session and the project
# root is a Git work tree (a .git folder or file): the git command. Git but no .git (a zip file
# unpacked on a PC that has Git): git checkout would fail, so the advice is the same as without Git.
# No Git (the project came as a zip file): download the repository again and overwrite the file.
function Get-RestoreAdvice([string]$rel) {
    $hasGit = ((Find-App 'git' $script:sessionPath).Count -gt 0)
    $isWorkTree = (Test-Path -LiteralPath (Join-Path $projectRoot '.git'))
    if ($hasGit -and -not $isWorkTree) {
        return (T ('이 폴더는 Git 저장소가 아니므로 저장소를 다시 내려받아 그 파일을 덮어쓰세요(' + $rel + ')') ('this folder is not a Git repository, so download the repository again and overwrite that file (' + $rel + ')'))
    }
    if ($hasGit) {
        return (T ('저장소에서 복원하세요(git checkout ' + $rel + ')') ('restore it from the repository (git checkout ' + $rel + ')'))
    }
    return (T ('Git 이 없으므로 저장소를 다시 내려받아 그 파일을 덮어쓰세요(' + $rel + ')') ('Git is not installed, so download the repository again and overwrite that file (' + $rel + ')'))
}

function Get-ExitCode {
    if ($script:flags.fail) { return 1 }
    if ($script:flags.blocked) { return 4 }
    if ($script:flags.restart) { return 3 }
    if ($script:flags.needs) { return 2 }
    return 0
}

# -Json must be pure ASCII: ConvertTo-AsciiJson (common.ps1) turns every char above 0x7E into \uXXXX.
function Complete-Run {
    $code = Get-ExitCode
    if ($script:showSummary -and ($code -ne 0 -or $script:done.Count -gt 0 -or $script:failedActions.Count -gt 0)) {
        $remaining = @()
        foreach ($i in $script:items) {
            if ($i.level -eq 'required' -and $i.verdict -eq 'fail') { $remaining += $i.name }
        }
        $parts = @()
        if ($script:done.Count -gt 0) { $d = $script:done -join ', '; $parts += (T ('성공: ' + $d) ('done: ' + $d)) }
        if ($script:failedActions.Count -gt 0) { $f = $script:failedActions -join ', '; $parts += (T ('실패: ' + $f) ('failed: ' + $f)) }
        if ($remaining.Count -gt 0) { $r = $remaining -join ', '; $parts += (T ('남은 것: ' + $r) ('remaining: ' + $r)) }
        $detail = ($parts -join '; ')
        if (-not $detail) { $detail = T '문제 없음' 'no problem' }
        $verdict = 'ok'
        if ($code -ne 0) { $verdict = 'warn' }
        Add-Item 'S11' 'required' (T '요약' 'summary') $verdict $detail
    }
    $meaning = @{
        0 = (T '준비됨' 'ready')
        1 = (T '실패' 'failed')
        2 = (T '사용자 허락·조치 필요' 'needs the user to allow or do something')
        3 = (T '재시작 필요: Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 여세요' 'restart needed: close Claude Code completely (the desktop app, the VS Code window, or the terminal it runs in) and open it again')
        4 = (T '정책·네트워크로 불가' 'blocked by policy or network')
    }
    if ($Json) {
        $obj = [ordered]@{ exit_code = $code; exit_meaning = $meaning[$code]; items = @($script:items.ToArray()) }
        Write-Output (ConvertTo-AsciiJson (ConvertTo-Json -InputObject $obj -Depth 6))
    } else {
        Write-Host ('[info] ' + (T '종료 코드 ' 'exit code ') + $code + ': ' + $meaning[$code])
    }
    exit $code
}

# ---- failure record (.gatekit/runs/setup-last.json) -----------------------------
function Read-FailureRecords {
    $list = @()
    try {
        if (Test-Path -LiteralPath $script:failureFile) {
            $data = (Get-Content -LiteralPath $script:failureFile -Raw -Encoding UTF8 | ConvertFrom-Json)
            foreach ($f in @($data.failures)) { if ($f -and $f.item) { $list += $f } }
        }
    } catch { }
    return $list
}

function Write-FailureRecords($records) {
    try {
        $dir = Split-Path -Parent $script:failureFile
        if (-not (Test-Path -LiteralPath $dir)) { [void](New-Item -ItemType Directory -Path $dir -Force) }
        $obj = [ordered]@{ schema = 1; failures = @($records) }
        $json = ConvertTo-AsciiJson (ConvertTo-Json -InputObject $obj -Depth 5)
        [System.IO.File]::WriteAllText($script:failureFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}

# One record per item+action; a new failure replaces the older one of the same item and action.
function Add-FailureRecord([string]$item, [string]$action, [string]$cls, [string]$hex, [string]$message) {
    if (-not $action) { return }
    $code = 0
    $hexText = ''
    try {
        if ($hex -match '^[0-9A-Fa-f]{8}$') { $code = [Convert]::ToInt32($hex, 16); $hexText = '0x' + $hex.ToUpper() }
        elseif ($hex -match '^-?\d+$') { $code = [int]$hex; $hexText = '' }
    } catch { }
    $kept = @()
    foreach ($f in @(Read-FailureRecords)) { if (-not ("$($f.item)" -eq $item -and "$($f.action)" -eq $action)) { $kept += $f } }
    $kept += [pscustomobject][ordered]@{ time = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz'); item = $item; action = $action
        exit_code = $code; exit_hex = $hexText; class = $cls; message = $message }
    Write-FailureRecords $kept
}

# A success removes every record of that item (the item works now).
function Remove-FailureRecord([string]$item) {
    $all = @(Read-FailureRecords)
    if ($all.Count -eq 0) { return }
    $kept = @()
    foreach ($f in $all) { if ("$($f.item)" -ne $item) { $kept += $f } }
    if ($kept.Count -ne $all.Count) { Write-FailureRecords $kept }
}

# ---- argument validation ------------------------------------------------------
function Split-List($value) {
    $result = @()
    foreach ($v in @($value)) {
        foreach ($p in ("$v" -split '[,;\s]+')) { if ($p) { $result += $p.ToLower() } }
    }
    return , $result
}

$argsBad = $false
if ($Lang -ne '') {
    $l = $Lang.ToLower()
    if ($l -eq 'ko' -or $l -eq 'en') { $script:langMode = $l }
    else {
        $argsBad = $true
        Add-Item 'args' 'required' '-Lang' 'fail' (T ('알 수 없는 언어: ' + $Lang) ('unknown language ' + $Lang)) (T '-Lang ko 또는 -Lang en 을 쓰세요' 'use -Lang ko or -Lang en')
    }
}
$installList = Split-List $Install
$updateList = Split-List $Update
$reinstallList = Split-List $Reinstall
if ($RetryFailed -and -not $Status) {
    $retried = @()
    foreach ($f in @(Read-FailureRecords)) {
        $n = "$($f.item)".ToLower()
        $a = "$($f.action)".ToLower()
        if ($a -eq 'install' -and $allowed -contains $n) {
            if ($installList -notcontains $n) { $installList += $n }
            $retried += ($n + ' ' + (T '설치' 'install'))
        } elseif ($a -eq 'update' -and $allowed -contains $n -and $n -ne 'venv' -and $n -ne 'winget') {
            if ($updateList -notcontains $n) { $updateList += $n }
            $retried += ($n + ' ' + (T '업데이트' 'update'))
        } elseif ($a -eq 'reinstall' -and $allowedReinstall -contains $n) {
            if ($reinstallList -notcontains $n) { $reinstallList += $n }
            $retried += ($n + ' ' + (T '재설치' 'reinstall'))
        }
    }
    if ($retried.Count -eq 0) {
        Say 'info' 'retry' '-RetryFailed' (T '다시 시도할 실패 기록이 없습니다.' 'no recorded failure to retry.')
    } else {
        $rt = $retried -join ', '
        Say 'info' 'retry' '-RetryFailed' (T ('기록된 실패 항목만 같은 동작으로 다시 시도합니다: ' + $rt) ('retrying only the recorded failures with the same action: ' + $rt))
    }
}
if ($script:pkgs.Count -lt 5) {
    $argsBad = $true
    Add-Item 'args' 'required' 'packages.json' 'fail' (T ('scripts/packages.json 을 읽지 못했습니다: ' + $script:pkgLoadError) ('could not read scripts/packages.json: ' + $script:pkgLoadError)) (Get-RestoreAdvice '.claude/gatekit/scripts/packages.json')
}
foreach ($n in (@($installList) + @($updateList))) {
    if ($allowed -notcontains $n) {
        $argsBad = $true
        Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T ('거부됨: "' + $n + '" 은(는) 허용 목록에 없습니다') ('refused: "' + $n + '" is not in the allowed list')) (T ('허용: ' + ($allowed -join ', ')) ('allowed: ' + ($allowed -join ', ')))
    }
}
foreach ($n in $reinstallList) {
    if ($allowedReinstall -notcontains $n) {
        $argsBad = $true
        $why = T ('거부됨: "' + $n + '" 은(는) -Reinstall 허용 목록에 없습니다') ('refused: "' + $n + '" is not in the -Reinstall allowed list')
        $hint = T ('허용: ' + ($allowedReinstall -join ', ')) ('allowed: ' + ($allowedReinstall -join ', '))
        if ($n -eq 'git') { $hint = (T 'git 은 관리자 권한이 필요할 수 있어 자동으로 다시 설치하지 않습니다. 직접 설치하세요: winget install --id ' 'git may need administrator rights, so it is never reinstalled automatically. Install it yourself: winget install --id ') + $script:pkgs['git'].winget_id + ' -e' }
        if ($n -eq 'venv') { $hint = T '.venv 는 -Install venv 로 다시 만듭니다' 'the .venv is rebuilt with -Install venv' }
        Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' $why $hint
    }
}
if ($Status -and ($RetryFailed -or $installList.Count -gt 0 -or $updateList.Count -gt 0 -or $reinstallList.Count -gt 0)) {
    $argsBad = $true
    Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T '거부됨: -Status 는 점검만 하므로 -Install/-Update/-Reinstall/-RetryFailed 와 함께 쓸 수 없습니다' 'refused: -Status only looks, so it cannot be combined with -Install/-Update/-Reinstall/-RetryFailed') ''
}
if ($updateList -contains 'venv') {
    $argsBad = $true
    Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T '거부됨: venv 는 -Update 가 아니라 -Install venv 로만 만듭니다' 'refused: venv is built only with -Install venv, not -Update') ''
}
if ($updateList -contains 'winget') {
    $argsBad = $true
    Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T '거부됨: winget 은 Microsoft Store 가 업데이트하므로 -Update 로는 하지 않습니다' 'refused: winget is updated by the Microsoft Store, not by -Update') (T '없을 때만 -Install winget 을 쓰세요' 'use -Install winget only when it is missing')
}
if ($argsBad) { $script:showSummary = $false; Set-Flag 'fail'; Complete-Run }
# winget goes first: the other installs may need it (-Install winget,pwsh).
if ($installList -contains 'winget') { $installList = @('winget') + @($installList | Where-Object { $_ -ne 'winget' }) }

# ---- process and version helpers (the PATH rule, Find-App and Get-App, and Quote-Arg are in common.ps1) ----
# Kills a process and all its children (a plain Kill leaves grandchildren running).
function Stop-ProcTree($p) {
    try {
        $tk = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        if (Test-Path -LiteralPath $tk) { & $tk /T /F /PID $p.Id 2>&1 | Out-Null }
    } catch { }
    try { if (-not $p.HasExited) { $p.Kill() } } catch { }
}

# Runs a program without a shell: stdin closed (nothing can prompt), stdout+stderr
# captured, whole process tree killed after $timeoutSec. Returns Started / TimedOut / Code / Out /
# StartError. StartError is the Windows error number when the program could not be started at all
# (Started stays $false): 2 = file not found, 193 = not a program, 5 = access denied,
# 1260 = blocked by a group policy (AppLocker, software restriction), 4551 = blocked by an
# application control policy. 0 = it started, or the failure carried no Windows error number.
$script:execDenied = @("$env:GATEKIT_SETUP_EXEC_DENIED".ToLower() -split '[,;\s]+' | Where-Object { $_ })
function Invoke-Proc([string]$file, [string[]]$argList, [int]$timeoutSec = 20) {
    $res = [pscustomobject]@{ Started = $false; TimedOut = $false; Code = -1; Out = ''; StartError = 0 }
    if ($script:execDenied.Count -gt 0 -and $script:execDenied -contains [System.IO.Path]::GetFileNameWithoutExtension($file).ToLower()) {
        $res.StartError = 1260
        $res.Out = 'This program is blocked by group policy.'
        return $res
    }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $file
        $psi.Arguments = (($argList | ForEach-Object { Quote-Arg $_ }) -join ' ')
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
        if ($so.IsCompleted) { $res.Out += $so.Result }
        if ($se.IsCompleted) { $res.Out += $se.Result }
    } catch {
        $res.Out = "$_"
        $inner = $_.Exception
        while ($inner) {
            if ($inner -is [System.ComponentModel.Win32Exception]) { $res.StartError = [int]$inner.NativeErrorCode; break }
            $inner = $inner.InnerException
        }
    }
    return $res
}

# Windows refused to START the program because of a policy. Only these two error numbers say so
# without doubt; every other start failure (5 access denied, 193 damaged file, ...) keeps the
# older "could not run it" handling, because a reinstall may well fix those.
function Test-ExecDenied($r) {
    return (-not $r.Started -and ($r.StartError -eq 1260 -or $r.StartError -eq 4551))
}

function New-ExecDeniedInquiry([string]$what, [int]$code) {
    return (T ('IT 담당자님, 제 PC(Windows)에서 ' + $what + ' 실행이 조직 정책으로 차단됩니다(Windows 오류 ' + $code + '). AppLocker 나 앱 제어 정책에서 이 프로그램을 사용자 권한으로 실행할 수 있게 허용해 주실 수 있나요?') `
             ('Hi IT team, on my Windows PC running ' + $what + ' is blocked by an organisation policy (Windows error ' + $code + '). Could you allow this program to run at user level in AppLocker or the application control policy?'))
}

function Get-VersionFrom([string]$text) {
    if ($text -match '(\d+)\.(\d+)\.(\d+)') { return [version]($Matches[1] + '.' + $Matches[2] + '.' + $Matches[3]) }
    return $null
}

# $setFlag = $false: the line is shown but the exit code stays as it is (a program this project
# does not need right now).
function Add-RestartItem([string]$id, [string]$level, [string]$name, [string]$found, [bool]$setFlag = $true) {
    if ($setFlag) { Set-Flag 'restart' }
    Add-Item $id $level $name 'warn' (T ('설치되어 있지만(' + $found + ') 지금 창의 PATH 에는 보이지 않습니다.') ('installed (' + $found + ') but not visible on the PATH of this session.')) `
        (T 'Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 여세요. 그런 다음 /gatekit-setup 을 다시 실행하세요' 'close Claude Code completely (the desktop app, the VS Code window, or the terminal it runs in) and open it again, then run /gatekit-setup again')
}

$winPs = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tlsPrefix = '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; '

# ---- winget failure table (S16) ----------------------------------------------
# key = exit code as 8 hex digits. class: ok / policy / network / agreement / reboot / unknown
function New-PolicyFailure([string]$hex) {
    return @{ cls = 'policy'; hex = $hex
        ko = '회사·학교 정책이 winget 사용을 막고 있습니다.'; en = 'a company or school policy blocks winget.'
        can = (T 'uv·claude 를 새로 설치할 때는 공식 설치 스크립트를 자동으로 시도합니다. 그 밖의 프로그램(PowerShell 7 등)은 IT 담당자가 필요합니다.' 'for a new uv or claude install the official installer script is tried automatically. Other programs (such as PowerShell 7) need your IT contact.'); it = $true }
}

function New-AgreementFailure([string]$hex) {
    return @{ cls = 'agreement'; hex = $hex
        ko = 'winget 소스 약관에 아직 동의하지 않았습니다.'; en = 'the winget source agreements have not been accepted yet.'
        can = (T '터미널에서 winget search git 을 한 번 실행해 약관에 직접 동의하거나, 설치를 다시 허락해 주세요.' 'run winget search git once in a terminal and accept the agreements yourself, or allow the install again.'); it = $false }
}

function Get-WingetFailure([int]$code) {
    $hex = '{0:X8}' -f $code
    switch ($hex) {
        '8A15002B' { return @{ cls = 'ok'; hex = $hex; ko = '업데이트할 것이 없습니다(이미 최신).'; en = 'nothing to update (already current).'; can = ''; it = $false } }
        '8A150061' { return @{ cls = 'ok'; hex = $hex; ko = '이미 설치되어 있습니다.'; en = 'already installed.'; can = ''; it = $false } }
        '8A15003A' { return (New-PolicyFailure $hex) }
        '8A15010F' { return (New-PolicyFailure $hex) }
        '8A15001B' { return (New-PolicyFailure $hex) }
        '8A15001C' { return (New-PolicyFailure $hex) }
        '8A150109' { return @{ cls = 'reboot'; hex = $hex
            ko = '설치는 끝났지만 PC 를 다시 시작해야 합니다.'; en = 'the install finished but the PC must be restarted.'
            can = (T 'PC 를 다시 시작한 뒤 /gatekit-setup 을 다시 실행하세요.' 'restart the PC, then run /gatekit-setup again.'); it = $false } }
        '8A150107' { return @{ cls = 'network'; hex = $hex
            ko = '설치 서버에 연결하지 못했습니다(네트워크).'; en = 'could not reach the install source (network).'
            can = (T '인터넷·VPN·프록시 연결을 확인하고 잠시 뒤 다시 시도하세요.' 'check the internet, VPN and proxy, then try again in a moment.'); it = $true } }
        '80072EFD' { return @{ cls = 'network'; hex = $hex
            ko = '보안 연결(TLS)이나 서버 연결에 실패했습니다.'; en = 'the secure connection (TLS) or the server connection failed.'
            can = (T '회사 프록시·방화벽·보안 프로그램이 막고 있을 수 있습니다. 집 네트워크/핫스팟에서 다시 시도해 보세요.' 'a company proxy, firewall or security tool may be blocking it. Try again from a home network or a hotspot.'); it = $true } }
        '8A150046' { return (New-AgreementFailure $hex) }
        '8A150041' { return (New-AgreementFailure $hex) }
    }
    return @{ cls = 'unknown'; hex = $hex
        ko = ('알 수 없는 오류(0x' + $hex + ')입니다.'); en = ('unknown error (0x' + $hex + ').')
        can = (T '아래 출력의 마지막 줄을 확인하고, 다시 시도해 보세요.' 'look at the last output lines below and try again.'); it = $true }
}

function New-InquiryText([string]$what, [string]$code) {
    return (T ('IT 담당자님, 제 PC(Windows)에서 ' + $what + ' 설치가 오류 ' + $code + ' 로 실패했습니다. 조직 정책(AppLocker/Intune)이나 프록시·방화벽이 winget, astral.sh, claude.ai 접속을 막고 있는지 확인하고, 사용자 권한으로 허용해 주실 수 있나요?') `
             ('Hi IT team, installing ' + $what + ' on my Windows PC failed with error ' + $code + '. Could you check whether a policy (AppLocker/Intune) or a proxy/firewall blocks winget, astral.sh or claude.ai, and allow them at user level?'))
}

# Records one failed install/update and sets the right flag.
function Report-InstallFailure([string]$name, [string]$what, $fail, [string]$out) {
    [void]$script:failedActions.Add($name)
    Add-FailureRecord $name $script:currentAction $fail.cls $fail.hex (T $fail.ko $fail.en)
    $hints = @()
    if ($fail.can) { $hints += ((T '지금 할 수 있는 것: ' 'What you can do now: ') + $fail.can) }
    if ($fail.it) { $hints += ((T 'IT 담당자에게 보낼 문의문: ' 'Message for your IT contact: ') + (New-InquiryText $what ('0x' + $fail.hex))) }
    $last = @(($out -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -Last 4)
    foreach ($l in $last) { $hints += ('  ' + $l.Trim()) }
    Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T $fail.ko $fail.en) '' $hints
    if ($fail.cls -eq 'policy' -or $fail.cls -eq 'network') { Set-Flag 'blocked' }
    elseif ($fail.cls -eq 'agreement') { Set-Flag 'needs' }
    else { Set-Flag 'fail' }
}

# Word boundaries: "openssl" or "rustls" must not count as an ssl / tls network problem.
function Test-NetworkText([string]$text) {
    return ($text -match '(?i)\b(error sending request|dns error|timed out|timeout|could not resolve|unable to connect|certificate|tls|ssl|proxy|connection (refused|reset)|no such host|name or service)\b')
}

# ---- actions (only for names the user allowed) -------------------------------
# With $defer the failure is NOT reported: the caller decides (fallback) and reports it via
# Report-WingetDeferred. Returns $true on success.
function Invoke-WingetAction([string]$verb, [string]$id, [string]$name, [string]$what, [string[]]$extra = @(), [bool]$defer = $false) {
    $script:lastWingetFail = $null
    $winget = Find-App 'winget' $script:sessionPath
    if ($winget.Count -eq 0) {
        [void]$script:failedActions.Add($name)
        $label = $name
        if ($name -eq 'pwsh') { $label = 'PowerShell 7' }
        $cls = 'winget-missing'
        $msg = T 'winget 이 없어 자동 설치를 할 수 없습니다.' 'winget is missing, so it cannot install automatically.'
        $act = T '먼저 winget 설치를 허락하거나(-Install winget), Microsoft Store 에서 "앱 설치 관리자(App Installer)"를 설치한 뒤 다시 실행하세요.' 'allow the winget install first (-Install winget), or install "App Installer" from the Microsoft Store, then run again.'
        # -Install winget,<name>: the winget install of THIS run did not work, so "allow -Install
        # winget first" would send the user in a circle. Point at the cause instead.
        if ($script:wingetInstall -eq 'failed') {
            $cls = 'winget-failed'
            $msg = T ('winget 설치가 실패해서 ' + $label + ' 을(를) 설치하지 못했습니다.') ('the winget install failed, so ' + $label + ' could not be installed.')
            $act = T '위의 winget 설치 줄에 나온 안내를 먼저 해결한 뒤 다시 실행하세요.' 'resolve what the winget install line above says first, then run again.'
        } elseif ($script:wingetInstall -eq 'restart') {
            $cls = 'winget-restart'
            $msg = T ('winget 은 설치됐지만 이 창에서 아직 보이지 않아 ' + $label + ' 을(를) 설치하지 못했습니다.') ('winget was installed but is not visible in this session yet, so ' + $label + ' could not be installed.')
            $act = T 'Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 연 뒤 다시 실행하세요.' 'close Claude Code completely (the desktop app, the VS Code window, or the terminal it runs in), open it again, then run again.'
        }
        Add-FailureRecord $name $script:currentAction $cls '' $msg
        Set-Flag 'needs'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' $msg $act
        return $false
    }
    Say 'info' ('A-' + $name) $name (T ('winget ' + $verb + ' ' + $id + ' 실행 중...') ('running winget ' + $verb + ' ' + $id + ' ...'))
    $wargs = @($verb, '--id', $id, '-e', '--source', 'winget', '--disable-interactivity',
               '--accept-source-agreements', '--accept-package-agreements') + @($extra)
    $r = Invoke-Proc $winget[0].Source $wargs 900
    if ($r.TimedOut) {
        [void]$script:failedActions.Add($name)
        Add-FailureRecord $name $script:currentAction 'timeout' '' (T 'winget 이 제한 시간 안에 끝나지 않아 중단했습니다.' 'winget did not finish in time and was stopped.')
        Set-Flag 'blocked'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T 'winget 이 제한 시간 안에 끝나지 않아 중단했습니다.' 'winget did not finish in time and was stopped.') `
            (T '네트워크를 확인하고 다시 시도하세요. 계속되면 IT 담당자에게 문의하세요.' 'check the network and try again. If it keeps happening, ask your IT contact.')
        return $false
    }
    if ($r.Code -eq 0) { return $true }
    $f = Get-WingetFailure $r.Code
    if ($f.cls -eq 'ok') { Say 'ok' ('A-' + $name) $name (T $f.ko $f.en); return $true }
    if ($f.cls -eq 'reboot') {
        Add-FailureRecord $name $script:currentAction 'reboot' $f.hex (T $f.ko $f.en)
        Set-Flag 'restart'
        Add-Item ('S16-' + $name) 'required' $name 'warn' (T $f.ko $f.en) $f.can
        return $false
    }
    if ($defer) { $script:lastWingetFail = @{ fail = $f; out = $r.Out; what = $what; name = $name }; return $false }
    Report-InstallFailure $name $what $f $r.Out
    return $false
}

# Runs an official install.ps1. On failure returns $false and leaves the failure
# description in $script:lastScriptFail; the CALLER reports it (Report-InstallFailure)
# so a fallback (winget) can be tried first.
function Invoke-OfficialScript([string]$url, [string]$name) {
    Say 'info' ('A-' + $name) $name (T ('공식 설치 스크립트를 실행합니다: ' + $url) ('running the official installer: ' + $url))
    if ($env:GATEKIT_SETUP_OFFICIAL_RUNNER) {
        $r = Invoke-Proc $env:GATEKIT_SETUP_OFFICIAL_RUNNER @($url) 600
    } else {
        $cmd = $tlsPrefix + 'irm ' + $url + ' | iex'
        $r = Invoke-Proc $winPs @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd) 600
    }
    if ($r.Started -and -not $r.TimedOut -and $r.Code -eq 0) { return $true }
    $cls = 'unknown'
    $hex = '{0:X8}' -f [int]$r.Code
    if ($r.TimedOut -or (Test-NetworkText $r.Out)) { $cls = 'network'; $hex = '80072EFD' }
    $script:lastScriptFail = @{ fail = @{ cls = $cls; hex = $hex; it = $true
        ko = ('공식 설치 스크립트가 실패했습니다(' + $url + ').'); en = ('the official installer script failed (' + $url + ').')
        can = (T '인터넷 연결을 확인하고 다시 시도하세요.' 'check the internet connection and try again.') }; out = $r.Out }
    return $false
}

function Report-ScriptFailure([string]$name) {
    Report-InstallFailure $name $name $script:lastScriptFail.fail $script:lastScriptFail.out
}

function Get-UvMethod($uvPath) {
    $receipt = ''
    if ($env:LOCALAPPDATA) { $receipt = Join-Path $env:LOCALAPPDATA 'uv\uv-receipt.json' }
    $receiptState = 'none'
    if ($receipt -and (Test-Path -LiteralPath $receipt)) {
        $receiptState = 'valid'
        try { $null = (Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json) } catch { $receiptState = 'broken' }
    }
    $method = 'unknown'
    if ($uvPath -match '(?i)\\WinGet\\') { $method = 'winget' }
    elseif ($uvPath -match '(?i)\\scoop\\') { $method = 'scoop' }
    elseif ($uvPath -match '(?i)\\Python[^\\]*\\Scripts\\') { $method = 'pip' }
    elseif ($receiptState -ne 'none' -or $uvPath -match '(?i)\\\.local\\bin\\') { $method = 'standalone' }
    return @{ method = $method; receipt = $receiptState }
}

function Get-UvUpdateAdvice([string]$method) {
    switch ($method) {
        'standalone' { return 'uv self update' }
        'winget' { return ('winget upgrade --id ' + $script:pkgs['uv'].winget_id + ' -e') }
        'scoop' { return 'scoop update uv' }
        'pip' { return 'python -m pip install -U uv' }
    }
    return (T '설치한 방법에 맞춰 업데이트하세요' 'update it the same way you installed it')
}

# pwsh installed by the old MSI package lives here; a MSIX install/update may ask for UAC.
function Test-PwshMsiPath([string]$path) {
    return ($path -match '(?i)\\Program Files( \(x86\))?\\PowerShell\\')
}

# After a reinstall: read the version again and (for uv) check the receipt.
function Confirm-Reinstalled([string]$name, [string]$path, [string]$known = '') {
    if (-not $path) {
        # A package install with no pwsh on this session PATH: the package version is all there is.
        if ($known -and $known -ne '?') { Say 'ok' ('A-' + $name + '-version') $name ((T '재설치 후 버전 확인: ' 'version after the reinstall: ') + $known) }
        else { Say 'unverified' ('A-' + $name + '-version') $name (T '재설치했지만 버전을 다시 읽지 못했습니다.' 'reinstalled, but the version could not be read again.') }
        return
    }
    if ($name -eq 'pwsh') {
        $r = Invoke-Proc $path @('-NoProfile', '-NoLogo', '-Command', '$PSVersionTable.PSVersion.ToString()') 20
    } else {
        $r = Invoke-Proc $path @('--version') 20
    }
    $vt = ($r.Out.Trim() -split "`r?`n")[0]
    if ($r.Code -eq 0 -and $vt) {
        Say 'ok' ('A-' + $name + '-version') $name ((T '재설치 후 버전 확인: ' 'version after the reinstall: ') + $vt)
    } else {
        Say 'unverified' ('A-' + $name + '-version') $name (T '재설치했지만 버전을 다시 읽지 못했습니다.' 'reinstalled, but the version could not be read again.')
    }
    if ($name -eq 'uv') {
        $m = Get-UvMethod $path
        if ($m.receipt -eq 'broken') {
            Say 'warn' 'A-uv-receipt' 'uv' (T 'uv-receipt.json 이 아직 깨져 있습니다.' 'uv-receipt.json is still broken.')
        } elseif ($m.receipt -eq 'valid') {
            Say 'ok' 'A-uv-receipt' 'uv' (T 'uv-receipt.json 이 정상입니다(uv self update 사용 가능).' 'uv-receipt.json is valid (uv self update works).')
        }
    }
}

# ---- PowerShell 7: the installed stable PRODUCT decides, not the PATH order --------------------
# Order: (1) the Windows package and (2) the MSI folder <Program Files>\PowerShell\7: both are
# Get-PwshProduct in common.ps1, the rule session-check.ps1 uses too (the package names come from
# packages.json); (3) the version text of each pwsh on the session PATH (a "-preview" style
# suffix means preview), which needs a process and is therefore only done here.
# The first three pwsh on the session PATH: path, version text ('?' = unreadable), kind.
function Get-PwshOnPath {
    $list = @()
    foreach ($a in (@(Find-App 'pwsh' $script:sessionPath) | Select-Object -First 3)) {
        $r = Invoke-Proc $a.Source @('-NoProfile', '-NoLogo', '-Command', '$PSVersionTable.PSVersion.ToString()') 20
        $vt = ($r.Out.Trim() -split "`r?`n")[0]
        $kind = 'unknown'
        if ($vt -match '^(\d+)\.(\d+)\.(\d+)(-\S+)?$') {
            $kind = 'stable'
            if ($Matches[4]) { $kind = 'preview' }
        } else { $vt = '?' }
        $list += [pscustomobject]@{ path = $a.Source; text = $vt; kind = $kind }
    }
    return , $list
}

# stable: a stable product is installed. source: package / msi / path. version: its text ('?' if
# unreadable). preview: a preview build was seen. onPath: Get-PwshOnPath (empty unless probed).
# where: session / registry / none for the name pwsh. With $probePath = $false the PATH is only
# probed when neither the package nor the MSI folder shows a stable product.
function Get-PwshState([bool]$probePath = $true) {
    $st = Get-PwshProduct "$($script:pkgs['pwsh'].appx_name)" "$($script:pkgs['pwsh'].appx_preview_name)"
    $st.onPath = @()
    $st.where = (Get-App 'pwsh' $script:sessionPath).where
    if ($probePath -or -not $st.stable) {
        $st.onPath = Get-PwshOnPath
        foreach ($o in $st.onPath) {
            if ($o.kind -eq 'preview') { $st.preview = $true }
            if ($o.kind -ne 'stable') { continue }
            if (-not $st.stable) { $st.stable = $true; $st.source = 'path'; $st.version = $o.text }
            if (-not $st.path) { $st.path = $o.path }
        }
    }
    return $st
}

# ---- winget (App Installer) ---------------------------------------------------------------------
# Step "register" asks Windows to register the App Installer package that is already on the PC
# (nothing is downloaded). Step "repair" downloads the Microsoft.WinGet.Client module from the
# PowerShell Gallery into the user's own folders (-Scope CurrentUser on both cmdlets: Windows
# PowerShell 5.1 would default to AllUsers, which needs administrator rights) and runs
# Repair-WinGetPackageManager without -AllUsers (only -AllUsers needs administrator rights).
# -Force answers the NuGet and the repository questions, so nothing can prompt.
function Invoke-WingetStep([string]$step) {
    $family = "$($script:pkgs['winget'].appx_name)" + '_8wekyb3d8bbwe'
    if ($env:GATEKIT_SETUP_WINGET_RUNNER) { return (Invoke-Proc $env:GATEKIT_SETUP_WINGET_RUNNER @($step, $family) 600) }
    $pre = '$ErrorActionPreference = ''Stop''; $ProgressPreference = ''SilentlyContinue''; '
    if ($step -eq 'register') {
        $cmd = $pre + 'Add-AppxPackage -RegisterByFamilyName -MainPackage ' + $family
        return (Invoke-Proc $winPs @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd) 180)
    }
    $cmd = $pre + $tlsPrefix + 'Install-PackageProvider -Name NuGet -Scope CurrentUser -Force | Out-Null; ' +
        'Install-Module -Name Microsoft.WinGet.Client -Scope CurrentUser -Force -Repository PSGallery | Out-Null; ' +
        'Import-Module Microsoft.WinGet.Client; Repair-WinGetPackageManager'
    return (Invoke-Proc $winPs @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd) 600)
}

function Install-Winget {
    $script:currentAction = 'install'
    if ((Get-App 'winget' $script:sessionPath).where -ne 'none') {
        Remove-FailureRecord 'winget'
        Say 'ok' 'A-winget' 'winget' (T '이미 설치되어 있어 건너뜁니다.' 'already installed, skipped.')
        return
    }
    $outs = @()
    $timedOut = $false
    Say 'info' 'A-winget' 'winget' (T 'Windows 에 이미 있는 앱 설치 관리자(App Installer)의 등록을 요청합니다. 내려받는 것은 없습니다.' 'asking Windows to register the App Installer that is already on this PC. Nothing is downloaded.')
    $r = Invoke-WingetStep 'register'
    $outs += $r.Out
    if ($r.TimedOut) { $timedOut = $true }
    if ((Get-App 'winget' $script:sessionPath).where -eq 'none') {
        Say 'info' 'A-winget' 'winget' (T '등록만으로는 되지 않아, PowerShell Gallery 에서 Microsoft.WinGet.Client 모듈을 사용자 폴더에 내려받아 winget 을 복구합니다(관리자 권한은 필요 없고 네트워크가 필요합니다).' 'registering was not enough, so the Microsoft.WinGet.Client module is downloaded from the PowerShell Gallery into your user folder to repair winget (no administrator rights, network needed).')
        $r = Invoke-WingetStep 'repair'
        $outs += $r.Out
        if ($r.TimedOut) { $timedOut = $true }
    }
    $after = Get-App 'winget' $script:sessionPath
    if ($after.where -eq 'session') {
        Remove-FailureRecord 'winget'
        [void]$script:done.Add('winget ' + (T '설치' 'install'))
        Say 'ok' 'A-winget' 'winget' ((T '완료' 'done') + ' (' + (T '설치' 'install') + ')')
        return
    }
    [void]$script:failedActions.Add('winget')
    $script:wingetInstall = 'failed'
    if ($after.where -eq 'registry') {
        $script:wingetInstall = 'restart'
        Add-FailureRecord 'winget' 'install' 'restart' '' (T '설치했지만 PATH 를 다시 읽어도 보이지 않습니다.' 'installed, but still not visible after re-reading PATH.')
        Add-RestartItem 'S9-winget' 'recommended' 'winget' $after.apps[0].Source
        return
    }
    $text = ($outs -join "`n")
    $cls = 'store'
    if ($text -match '(?i)(policy|administrator|access (is )?denied|0x80070005)') { $cls = 'policy' }
    elseif ($timedOut -or (Test-NetworkText $text) -or $text -match '(?i)(rate limit|unable to download|no match was found|could not be resolved)') { $cls = 'network' }
    $msg = T 'winget 을 자동으로 설치하지 못했습니다.' 'winget could not be installed automatically.'
    $act = T 'Microsoft Store 에서 "앱 설치 관리자(App Installer)"를 설치한 뒤 다시 실행하세요(아래 링크).' 'install "App Installer" from the Microsoft Store, then run again (link below).'
    if ($cls -eq 'policy') {
        Set-Flag 'blocked'
        $msg = T '회사·학교 정책이나 권한 문제로 winget 을 설치하지 못했습니다.' 'a company or school policy, or missing rights, kept winget from being installed.'
        $act = T 'IT 담당자에게 문의하세요. 정책을 우회하지 마세요.' 'ask your IT contact. Do not work around the policy.'
    } elseif ($cls -eq 'network') {
        Set-Flag 'blocked'
        $msg = T '네트워크 문제로 winget 을 설치하지 못했습니다.' 'a network problem kept winget from being installed.'
        $act = T '인터넷·VPN·프록시 연결을 확인하고 다시 시도하거나, Microsoft Store 에서 "앱 설치 관리자(App Installer)"를 설치하세요(아래 링크).' 'check the internet, VPN and proxy and try again, or install "App Installer" from the Microsoft Store (link below).'
    } else { Set-Flag 'needs' }
    Add-FailureRecord 'winget' 'install' $cls '' $msg
    $hints = @("$($script:pkgs['winget'].store_url)")
    foreach ($l in @(($text -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -Last 4)) { $hints += ('  ' + $l.Trim()) }
    Add-Item 'S16-winget' 'recommended' ('winget ' + (T '설치' 'install')) 'fail' $msg $act $hints
}

function Invoke-Action([string]$name, [string]$mode) {
    if ($name -eq 'venv') { return }                     # handled by the .venv step below
    if ($name -eq 'winget') { Install-Winget; return }
    $script:currentAction = $mode
    $found = Get-App $name $script:sessionPath
    $apps = $found.apps
    $present = ($found.where -ne 'none')
    # pwsh: a preview build on PATH is not "installed"; the stable product decides.
    $pwState = $null
    if ($name -eq 'pwsh') { $pwState = Get-PwshState $false; $present = $pwState.stable }
    if ($mode -eq 'install' -and $present) {
        Remove-FailureRecord $name
        Say 'ok' ('A-' + $name) $name (T '이미 설치되어 있어 건너뜁니다.' 'already installed, skipped.')
        return
    }
    if ($mode -eq 'reinstall' -and -not $present) {
        Say 'info' ('A-' + $name) $name (T '설치되어 있지 않아 재설치 대신 새로 설치합니다.' 'not installed, so a fresh install is done instead of a reinstall.')
        Invoke-Action $name 'install'
        return
    }
    if ($mode -eq 'update' -and -not $present) {
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '업데이트' 'update')) 'warn' (T '설치되어 있지 않아 업데이트할 수 없습니다.' 'not installed, so nothing to update.') (T '-Install 로 먼저 설치하세요.' 'install it first (-Install).')
        Set-Flag 'needs'
        return
    }
    if ($mode -eq 'update' -and $name -eq 'git') {
        Say 'ok' ('A-git') 'git' (T '이미 설치되어 있습니다. 관리자 권한이 필요할 수 있어 자동 업데이트는 하지 않습니다(필요하면 직접 업데이트하세요).' 'already installed. It may need administrator rights, so it is not updated automatically (update it yourself if you want).')
        return
    }
    $ok = $false
    switch ($name) {
        'pwsh' {
            $verb = 'upgrade'
            $pwshExtra = @('--installer-type', $script:pkgs['pwsh'].installer_type)
            if ($mode -eq 'install') { $verb = 'install' }
            if ($mode -eq 'reinstall') { $verb = 'install'; $pwshExtra += '--force' }
            if (($mode -eq 'update' -or $mode -eq 'reinstall') -and ($pwState.source -eq 'msi' -or (Test-PwshMsiPath $pwState.path))) {
                Say 'info' 'A-pwsh' 'pwsh' (T '기존 MSI 설치본이라 업데이트 중 관리자 확인 창(UAC)이 뜰 수 있습니다. 창이 뜨면 허용하거나 IT 담당자에게 문의하세요.' 'this is an older MSI install, so a Windows administrator prompt (UAC) may appear during the update. Allow it, or ask your IT contact.')
            }
            $ok = Invoke-WingetAction $verb $script:pkgs['pwsh'].winget_id 'pwsh' ('PowerShell 7 (winget ' + $script:pkgs['pwsh'].winget_id + ')') $pwshExtra
        }
        'uv' {
            if ($mode -eq 'reinstall') {
                $m = Get-UvMethod $apps[0].Source
                if ($m.method -eq 'winget') {
                    $ok = Invoke-WingetAction 'install' $script:pkgs['uv'].winget_id 'uv' ('uv (winget ' + $script:pkgs['uv'].winget_id + ' --force)') @('--force')
                } elseif ($m.method -eq 'scoop' -or $m.method -eq 'pip') {
                    Set-Flag 'needs'
                    Add-Item 'S16-uv' 'required' (T 'uv 재설치' 'uv reinstall') 'warn' (T ('이 uv 는 ' + $m.method + ' 로 설치되어 자동 재설치하지 않습니다.') ('this uv was installed with ' + $m.method + ', so it is not reinstalled automatically.')) (Get-UvUpdateAdvice $m.method)
                    return
                } else {
                    $why = T 'uv 를 공식 설치 스크립트로 다시 설치합니다.' 'reinstalling uv with the official installer script.'
                    if ($m.receipt -eq 'broken') { $why = T '깨진 uv-receipt.json 을 복구하려고 공식 설치 스크립트로 다시 설치합니다.' 'reinstalling uv with the official installer script to repair the broken uv-receipt.json.' }
                    Say 'info' 'A-uv' 'uv' $why
                    $ok = Invoke-OfficialScript $script:pkgs['uv'].official_script_url 'uv'
                    if (-not $ok) { Report-ScriptFailure 'uv' }
                }
            } elseif ($mode -eq 'install') {
                if ((Find-App 'winget' $script:sessionPath).Count -gt 0) {
                    $ok = Invoke-WingetAction 'install' $script:pkgs['uv'].winget_id 'uv' ('uv (winget ' + $script:pkgs['uv'].winget_id + ')') @() $true
                    if (-not $ok -and $script:lastWingetFail) {
                        $wf = $script:lastWingetFail
                        if ($wf.fail.cls -eq 'policy') {
                            Say 'info' 'A-uv' 'uv' (T 'winget 이 정책으로 막혀 있어 공식 설치 스크립트로 다시 시도합니다.' 'winget is blocked by policy, so the official installer script is tried instead.')
                            $ok = Invoke-OfficialScript $script:pkgs['uv'].official_script_url 'uv'
                            if (-not $ok) { Report-InstallFailure 'uv' $wf.what $wf.fail $wf.out }
                        } else {
                            Report-InstallFailure 'uv' $wf.what $wf.fail $wf.out
                        }
                    }
                } else {
                    $ok = Invoke-OfficialScript $script:pkgs['uv'].official_script_url 'uv'
                    if (-not $ok) { Report-ScriptFailure 'uv' }
                }
            } else {
                $m = Get-UvMethod $apps[0].Source
                if ($m.method -eq 'winget') { $ok = Invoke-WingetAction 'upgrade' $script:pkgs['uv'].winget_id 'uv' ('uv (winget ' + $script:pkgs['uv'].winget_id + ')') }
                elseif ($m.method -eq 'standalone' -and $m.receipt -eq 'broken') {
                    $ok = Invoke-OfficialScript $script:pkgs['uv'].official_script_url 'uv'
                    if (-not $ok) { Report-ScriptFailure 'uv' }
                }
                elseif ($m.method -eq 'standalone') {
                    Say 'info' 'A-uv' 'uv' (T 'uv self update 실행 중...' 'running uv self update ...')
                    $r = Invoke-Proc $apps[0].Source @('self', 'update') 180
                    if ($r.Code -eq 0 -and -not $r.TimedOut) { $ok = $true }
                    else {
                        $fail = @{ cls = 'unknown'; hex = ('{0:X8}' -f [int]$r.Code); it = $true; ko = 'uv self update 가 실패했습니다.'; en = 'uv self update failed.'
                            can = (T '네트워크를 확인하세요. receipt 가 깨졌다면 -Update uv 를 다시 허락하면 공식 설치 스크립트로 복구합니다.' 'check the network. If the receipt is broken, allow -Update uv again to repair it with the official installer.') }
                        if (Test-NetworkText $r.Out) { $fail.cls = 'network' }
                        Report-InstallFailure 'uv' 'uv self update' $fail $r.Out
                    }
                } else {
                    Set-Flag 'needs'
                    Add-Item 'S16-uv' 'required' (T 'uv 업데이트' 'uv update') 'warn' (T '이 설치 방법은 자동 업데이트하지 않습니다.' 'this install method is not updated automatically.') (Get-UvUpdateAdvice $m.method)
                    return
                }
            }
        }
        'claude' {
            if ($mode -eq 'reinstall') {
                Say 'info' 'A-claude' 'claude' (T 'claude 를 공식 설치 스크립트로 다시 설치합니다.' 'reinstalling claude with the official installer script.')
                $ok = Invoke-OfficialScript $script:pkgs['claude'].official_script_url 'claude'
                if (-not $ok) { Report-ScriptFailure 'claude' }
            } elseif ($mode -eq 'install') {
                $ok = Invoke-OfficialScript $script:pkgs['claude'].official_script_url 'claude'
                if (-not $ok) {
                    if ((Find-App 'winget' $script:sessionPath).Count -gt 0) {
                        $ok = Invoke-WingetAction 'install' $script:pkgs['claude'].winget_id 'claude' ('Claude Code (winget ' + $script:pkgs['claude'].winget_id + ')')
                    } else { Report-ScriptFailure 'claude' }
                }
            } else {
                Say 'info' 'A-claude' 'claude' (T 'claude update 실행 중...' 'running claude update ...')
                $r = Invoke-Proc $apps[0].Source @('update') 300
                if ($r.Code -eq 0 -and -not $r.TimedOut) { $ok = $true }
                else {
                    $fail = @{ cls = 'unknown'; hex = ('{0:X8}' -f [int]$r.Code); it = $true; ko = 'claude update 가 실패했습니다.'; en = 'claude update failed.'
                        can = (T '네트워크를 확인하고 다시 시도하세요.' 'check the network and try again.') }
                    if (Test-NetworkText $r.Out) { $fail.cls = 'network' }
                    Report-InstallFailure 'claude' 'claude update' $fail $r.Out
                }
            }
        }
        'git' {
            # S10: Git for Windows normally asks for administrator rights and this
            # script cannot tell beforehand, so it never runs it.
            Set-Flag 'needs'
            Add-Item 'S10-git' 'info' 'git' 'warn' (T '관리자 권한이 필요할 수 있어 자동으로 실행하지 않습니다.' 'it may need administrator rights, so it is not run automatically.') `
                (T '직접 설치하세요(선택 사항).' 'install it yourself (optional).') `
                @(('winget install --id ' + $script:pkgs['git'].winget_id + ' -e --source winget'), $script:pkgs['git'].docs_url)
            return
        }
    }
    if ($ok) {
        $after = Get-App $name $script:sessionPath
        $visible = ($after.where -ne 'none')
        $afterPath = ''
        $afterVersion = ''
        if ($visible) { $afterPath = $after.apps[0].Source }
        if ($name -eq 'pwsh') {
            $pwAfter = Get-PwshState $false
            $visible = $pwAfter.stable
            $afterPath = $pwAfter.path
            $afterVersion = $pwAfter.version
        }
        if (-not $visible) {
            Set-Flag 'restart'
            [void]$script:failedActions.Add($name)
            Add-FailureRecord $name $mode 'restart' '' (T '설치했지만 PATH 를 다시 읽어도 보이지 않습니다.' 'installed, but still not visible after re-reading PATH.')
            Add-Item ('S9-' + $name) 'required' $name 'warn' (T '설치했지만 PATH 를 다시 읽어도 보이지 않습니다.' 'installed, but still not visible after re-reading PATH.') `
                (T 'Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 여세요. 그런 다음 /gatekit-setup 을 다시 실행하세요.' 'close Claude Code completely (the desktop app, the VS Code window, or the terminal it runs in) and open it again, then run /gatekit-setup again.')
        } else {
            Remove-FailureRecord $name
            $modeKo = '업데이트'
            if ($mode -eq 'install') { $modeKo = '설치' }
            if ($mode -eq 'reinstall') { $modeKo = '재설치' }
            [void]$script:done.Add($name + ' ' + (T $modeKo $mode))
            Say 'ok' ('A-' + $name) $name ((T '완료' 'done') + ' (' + (T $modeKo $mode) + ')')
            if ($mode -eq 'reinstall') { Confirm-Reinstalled $name $afterPath $afterVersion }
        }
    }
}

# ---- start ---------------------------------------------------------------------
Say 'info' 'project' (T '프로젝트' 'project') $projectRoot

# Actions run first so the report below shows the state AFTER them.
foreach ($n in $installList) { Invoke-Action $n 'install' }
foreach ($n in $updateList) { Invoke-Action $n 'update' }
foreach ($n in $reinstallList) { Invoke-Action $n 'reinstall' }

# S1 system --------------------------------------------------------------------
$arch = $env:PROCESSOR_ARCHITEW6432
if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
$osv = [Environment]::OSVersion.Version
if ($arch -eq 'ARM64') {
    Add-Item 'S1' 'info' 'Windows' 'unverified' ('Windows ' + $osv.ToString() + ', ARM64: ' + (T 'uv·Python 의 ARM64 빌드 사용 가능 여부는 확인하지 못했습니다' 'not checked whether uv and Python ARM64 builds are available')) (T 'uv 설치 후 uv python list 로 확인하세요' 'after uv is installed, check with uv python list')
} else {
    Add-Item 'S1' 'info' 'Windows' 'info' ('Windows ' + $osv.ToString() + ', ' + $arch)
}

# S17 path ---------------------------------------------------------------------
# Windows refuses a full path of 260 characters or more (MAX_PATH is 260 including the closing
# NUL, so 259 usable) unless long paths are enabled. What counts is the project folder plus "\"
# plus the longest relative path below it, not the folder alone. Measured on 2026-10-02:
#    75  longest tracked file (git ls-files):
#        .claude/gatekit/tests/fixtures/spec/<case>/spec/03-architecture.md
#    55  longest file of a fresh user .venv (uv sync --frozen --no-dev, 17 files):
#        .claude/gatekit/.venv/Lib/site-packages/_virtualenv.pth
#    79  the same .venv after its Python ran once (the hooks do that):
#        .claude/gatekit/.venv/Lib/site-packages/__pycache__/_virtualenv.cpython-314.pyc
#    68  longest bytecode file Python writes next to the kernel:
#        .claude/gatekit/gatekit/gates/__pycache__/_bootstrap.cpython-314.pyc
#   169  a developer .venv WITH the dev group (pyright, ruff and their node files). verify.ps1
#        asks for that group; a user's --no-dev .venv never has it, so it is not counted here.
# The larger of the tracked files and the user .venv decides. Measure again when either grows.
# LongPathsEnabled = 1 in the registry lifts the limit (read only; GATEKIT_SETUP_LONG_PATHS
# replaces the value in tests).
$longestTrackedPath = 75
$longestVenvPath = 79
$pathLimit = 259
$longestInside = [Math]::Max($longestTrackedPath, $longestVenvPath)
$pathTotal = $projectRoot.Length + 1 + $longestInside
$longPathsOn = $false
if ($env:GATEKIT_SETUP_LONG_PATHS -eq '1') { $longPathsOn = $true }
elseif ($env:GATEKIT_SETUP_LONG_PATHS -ne '0') {
    try {
        $lp = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name 'LongPathsEnabled' -ErrorAction Stop
        if ([int]$lp.LongPathsEnabled -eq 1) { $longPathsOn = $true }
    } catch { }
}
if ($projectRoot -match '(?i)OneDrive') {
    Add-Item 'S17' 'info' (T '경로' 'path') 'warn' (T 'OneDrive 폴더 안입니다(동기화가 .venv 를 방해할 수 있음)' 'the project is inside OneDrive (sync can disturb .venv)') (T 'OneDrive 밖(예: C:\dev)으로 옮기는 것을 권장합니다' 'moving it outside OneDrive (for example C:\dev) is recommended')
} elseif ($pathTotal -gt $pathLimit -and -not $longPathsOn) {
    Add-Item 'S17' 'info' (T '경로' 'path') 'warn' (T ('경로가 너무 깁니다: 프로젝트 폴더 ' + $projectRoot.Length + '자에 그 안의 가장 긴 파일 경로 ' + $longestInside + '자를 더하면 ' + $pathTotal + '자로, Windows 기본 한도 ' + $pathLimit + '자를 넘습니다') ('the path is too long: the project folder (' + $projectRoot.Length + ' characters) plus the longest file path inside it (' + $longestInside + ') is ' + $pathTotal + ' characters, over the Windows default limit of ' + $pathLimit)) (T '더 짧은 폴더(예: C:\dev)로 옮기세요' 'move it to a shorter folder (for example C:\dev)')
} elseif ($pathTotal -gt $pathLimit) {
    Add-Item 'S17' 'info' (T '경로' 'path') 'ok' (T ('가장 긴 파일까지 ' + $pathTotal + '자로 기본 한도 ' + $pathLimit + '자를 넘지만, 이 PC 는 긴 경로를 허용합니다(LongPathsEnabled = 1)') ('' + $pathTotal + ' characters to the longest file, over the default limit of ' + $pathLimit + ', but this PC allows long paths (LongPathsEnabled = 1)'))
} else {
    Add-Item 'S17' 'info' (T '경로' 'path') 'ok' (T ('경로 문제 없음(가장 긴 파일까지 ' + $pathTotal + '자, 한도 ' + $pathLimit + '자)') ('no path problem (' + $pathTotal + ' characters to the longest file, limit ' + $pathLimit + ')'))
}

# S20 execution policy set by group policy ------------------------------------------
# Every hook and this script start with -ExecutionPolicy Bypass. That flag sets the Process
# scope, and the two group policy scopes win over it (MachinePolicy first, then UserPolicy).
# AllSigned / Restricted there: the unsigned gatekit scripts do not run at all, and nothing the
# user may allow changes that, so it is a policy block (exit code 4). In practice such a policy
# usually keeps this script from starting too ("... cannot be loaded ..."); the item is shown
# when the script does run (for example it was started another way than the hooks are).
# RemoteSigned there: only files that carry the internet mark are refused (see S8 below).
$policy = @{ MachinePolicy = 'Undefined'; UserPolicy = 'Undefined' }
$policyRead = $false
if ($env:GATEKIT_SETUP_EXECUTION_POLICY) {
    foreach ($pair in ($env:GATEKIT_SETUP_EXECUTION_POLICY -split ';')) {
        $kv = @($pair -split '=', 2)
        if ($kv.Count -eq 2 -and $policy.ContainsKey($kv[0].Trim())) { $policy[$kv[0].Trim()] = $kv[1].Trim() }
    }
    $policyRead = $true
} else {
    try {
        foreach ($row in @(Get-ExecutionPolicy -List -ErrorAction Stop)) {
            if ($policy.ContainsKey("$($row.Scope)")) { $policy["$($row.Scope)"] = "$($row.ExecutionPolicy)" }
        }
        $policyRead = $true
    } catch { }
}
$policyScope = 'MachinePolicy'
if ($policy.MachinePolicy -eq 'Undefined') { $policyScope = 'UserPolicy' }
$policyValue = $policy[$policyScope]                # the group policy value that is in effect
$policyText = 'MachinePolicy=' + $policy.MachinePolicy + ', UserPolicy=' + $policy.UserPolicy
$policyName = T '실행 정책' 'execution policy'
if (-not $policyRead) {
    $policyValue = 'Undefined'
    Add-Item 'S20' 'required' $policyName 'unverified' (T '그룹 정책의 실행 정책을 읽지 못했습니다' 'the execution policy set by group policy could not be read')
} elseif ($policyValue -eq 'AllSigned' -or $policyValue -eq 'Restricted') {
    Set-Flag 'blocked'
    Add-Item 'S20' 'required' $policyName 'fail' (T ('그룹 정책이 실행 정책을 ' + $policyValue + ' 로 고정했습니다(' + $policyText + '). 훅의 -ExecutionPolicy Bypass 가 통하지 않아 gatekit 스크립트와 훅이 실행되지 않습니다.') ('group policy pins the execution policy to ' + $policyValue + ' (' + $policyText + '). The -ExecutionPolicy Bypass of the hooks has no effect, so the gatekit scripts and hooks do not run.')) `
        (T 'IT 담당자에게 문의하세요. 정책을 우회하지 마세요.' 'ask your IT contact. Do not work around the policy.') `
        @((T 'IT 담당자에게 보낼 문의문: ' 'Message for your IT contact: ') + (T ('IT 담당자님, 제 PC(Windows)의 그룹 정책이 PowerShell 실행 정책을 ' + $policyValue + ' 로 고정해 두어(' + $policyScope + '), 서명되지 않은 gatekit 스크립트(프로젝트의 .claude/gatekit/scripts 폴더에 있는 .ps1 파일)가 실행되지 않습니다. 이 폴더의 스크립트를 실행할 수 있게 허용해 주실 수 있나요?') `
            ('Hi IT team, group policy on my Windows PC pins the PowerShell execution policy to ' + $policyValue + ' (' + $policyScope + '), so the unsigned gatekit scripts (the .ps1 files in the project folder .claude/gatekit/scripts) do not run. Could you allow the scripts in that folder to run?')))
} elseif ($policyValue -eq 'Undefined') {
    Add-Item 'S20' 'required' $policyName 'ok' (T ('그룹 정책이 실행 정책을 고정하지 않습니다(' + $policyText + ')') ('group policy does not pin the execution policy (' + $policyText + ')'))
} else {
    Add-Item 'S20' 'required' $policyName 'ok' (T ('그룹 정책의 실행 정책은 ' + $policyValue + ' 입니다(' + $policyText + '). gatekit 스크립트는 실행됩니다.') ('the execution policy set by group policy is ' + $policyValue + ' (' + $policyText + '). The gatekit scripts run.'))
}

# S8 internet mark on the scripts -------------------------------------------------
# A zip downloaded with a browser leaves the mark (the Zone.Identifier stream) on every file it
# held. All of scripts/*.ps1 is looked at: the hook runs session-check.ps1 and both scripts load
# common.ps1, so a mark on any of them matters as much as one on this file. Nothing is unblocked
# here; the command is printed for the user.
$scriptFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -ErrorAction SilentlyContinue | Sort-Object Name)
$marked = @()
foreach ($sf in $scriptFiles) {
    $mark = $null
    try { $mark = Get-Item -LiteralPath $sf.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue } catch { }
    if ($mark) { $marked += $sf.Name }
}
$scriptsName = T '스크립트' 'scripts'
$unblockHints = @((T '해제하려면 프로젝트 폴더에서 아래 한 줄을 직접 실행하세요(자동으로 실행하지 않습니다):' 'to remove the mark, run this one line yourself in the project folder (it is never run automatically):'),
                  'Get-ChildItem .claude\gatekit\scripts\*.ps1 | Unblock-File')
if ($marked.Count -eq 0) {
    Add-Item 'S8' 'required' $scriptsName 'ok' (T ('"인터넷에서 받음" 표시가 없습니다(.ps1 파일 ' + $scriptFiles.Count + '개)') ('no "downloaded from the internet" mark (' + $scriptFiles.Count + ' .ps1 files)'))
} elseif ($policyValue -eq 'RemoteSigned') {
    Set-Flag 'needs'
    Add-Item 'S8' 'required' $scriptsName 'warn' (T ('"인터넷에서 받음" 표시가 있는 파일: ' + ($marked -join ', ') + '. 그룹 정책의 실행 정책이 RemoteSigned 라서 이 파일들은 실행되지 않습니다.') ('files that carry the "downloaded from the internet" mark: ' + ($marked -join ', ') + '. Group policy sets the execution policy to RemoteSigned, so these files do not run.')) `
        (T '표시를 직접 해제하세요' 'remove the mark yourself') $unblockHints
} else {
    Add-Item 'S8' 'required' $scriptsName 'info' (T ('"인터넷에서 받음" 표시가 있는 파일: ' + ($marked -join ', ') + '. 자동으로 해제하지 않습니다.') ('files that carry the "downloaded from the internet" mark: ' + ($marked -join ', ') + '. It is not unblocked automatically.')) `
        (T '항상 powershell -NoProfile -ExecutionPolicy Bypass -File 로 실행하면 그대로 동작합니다' 'it works as it is when always run with powershell -NoProfile -ExecutionPolicy Bypass -File') $unblockHints
}

# S3 winget ---------------------------------------------------------------------
$wingetFound = Get-App 'winget' $script:sessionPath
$wingetApp = $wingetFound.apps
if ($wingetFound.where -eq 'none') {
    Add-Item 'S3' 'recommended' 'winget' 'warn' (T '없음' 'not found') (T '허락하면 설치합니다 (-Install winget). uv·claude 는 winget 없이도 설치할 수 있습니다' 'installed if you allow it (-Install winget). uv and claude can be installed without winget') `
        @((T '직접 하려면 Microsoft Store 에서 "앱 설치 관리자(App Installer)"를 설치하세요:' 'to do it yourself, install "App Installer" from the Microsoft Store:'), "$($script:pkgs['winget'].store_url)")
} elseif ($wingetFound.where -eq 'registry') {
    Add-RestartItem 'S3' 'recommended' 'winget' $wingetApp[0].Source
} else {
    $wv = Invoke-Proc $wingetApp[0].Source @('--version') 15
    $wvText = ($wv.Out.Trim() -split "`r?`n")[0]
    if ($wv.Code -eq 0 -and (Get-VersionFrom $wvText)) {
        Add-Item 'S3' 'recommended' 'winget' 'ok' (T ('있음, ' + $wvText) ('present, ' + $wvText))
    } else {
        Add-Item 'S3' 'recommended' 'winget' 'unverified' (T 'winget 은 있지만 버전을 읽지 못했습니다' 'winget is there but its version could not be read')
    }
    $agName = T 'winget 소스 약관' 'winget source agreements'
    $ag = Invoke-Proc $wingetApp[0].Source @('search', '--id', $script:pkgs['uv'].winget_id, '-e', '--source', 'winget', '--disable-interactivity') 30
    if ($ag.TimedOut -or -not $ag.Started) {
        Add-Item 'S3-agreement' 'recommended' $agName 'unverified' (T '제한 시간 안에 확인하지 못했습니다' 'could not be checked in time')
    } elseif ($ag.Code -eq 0) {
        $script:agreementOk = $true
        Add-Item 'S3-agreement' 'recommended' $agName 'ok' (T '소스 조회 성공(약관 동의됨)' 'source lookup worked (agreements accepted)')
    } else {
        $agFail = Get-WingetFailure $ag.Code
        if ($agFail.cls -eq 'agreement') {
            Add-Item 'S3-agreement' 'recommended' $agName 'warn' (T $agFail.ko $agFail.en) (T '설치를 허락하면 그 항목에 한해 동의를 포함해 실행합니다' 'if you allow an install, agreement is included for that item only')
        } else {
            Add-Item 'S3-agreement' 'recommended' $agName 'unverified' ((T '확인하지 못했습니다' 'could not be checked') + ' (0x' + $agFail.hex + ')')
        }
    }
}

# S2 pwsh -----------------------------------------------------------------------
# The stable product decides (Get-PwshState): a preview build that comes first on PATH is only noted.
$pw = Get-PwshState $true
$pathSeen = @()
$seenVersions = @{}
foreach ($o in $pw.onPath) {
    # The same version behind an alias path is one install: show it once.
    if ($o.text -eq '?' -or -not $seenVersions.ContainsKey($o.text)) {
        $pathSeen += ($o.path + ' = ' + $o.text)
        $seenVersions[$o.text] = $true
    }
}
$pathText = $pathSeen -join '; '
$pwshInstallAct = T '허락하면 설치합니다 (-Install pwsh). 직접 하려면 아래를 실행하세요' 'installed if you allow it (-Install pwsh). To do it yourself run this'
if ($wingetFound.where -eq 'none') {
    $pwshInstallAct = T 'winget 도 없습니다. 허락하면 둘 다 설치합니다 (-Install winget,pwsh). 직접 하려면 아래를 실행하세요' 'winget is missing too. Both are installed if you allow it (-Install winget,pwsh). To do it yourself run this'
}
$pwshInstallHints = @(('winget install --id ' + $script:pkgs['pwsh'].winget_id + ' -e --source winget --installer-type ' + $script:pkgs['pwsh'].installer_type), (T 'winget 없이 하려면 Microsoft Store 에서 "PowerShell" 을 설치하세요.' 'without winget, install "PowerShell" from the Microsoft Store.'))
$script:pkgInfo['pwsh'] = @{ where = $pw.where; path = ''; version = ''; source = '' }
if ($pw.stable) {
    $srcText = ''
    if ($pw.source -eq 'package') { $srcText = (T '패키지 ' 'package ') + $script:pkgs['pwsh'].appx_name }
    elseif ($pw.source -eq 'msi') { $srcText = 'MSI ' + $pw.path }
    $tail = $srcText
    if ($pathText) {
        if ($tail) { $tail += '; ' }
        $tail += 'PATH: ' + $pathText
    }
    $infoWhere = 'registry'
    if ($pw.where -eq 'session') { $infoWhere = 'session' }
    $script:pkgInfo['pwsh'] = @{ where = $infoWhere; path = $pw.path; version = $(if ($pw.version -ne '?') { $pw.version } else { '' }); source = $pw.source }
    $uacHint = @()
    if ($pw.source -eq 'msi' -or (Test-PwshMsiPath $pw.path)) {
        $uacHint = @(T '기존 MSI 설치본이라 업데이트할 때 관리자 확인 창(UAC)이 뜰 수 있습니다.' 'this is an older MSI install, so the update may show a Windows administrator prompt (UAC).')
    }
    if ($pw.version -eq '?') {
        Add-Item 'S2' 'required' 'pwsh' 'unverified' ((T '버전을 읽지 못했습니다: ' 'could not read the version: ') + $tail)
    } elseif ([version]$pw.version -lt $pwshMinimum) {
        Set-Flag 'needs'
        Add-Item 'S2' 'required' 'pwsh' 'fail' ((T '안정판이 ' 'the stable build is older than ') + $pwshMinimum + (T ' 보다 낮습니다: ' ': ') + $pw.version + ' (' + $tail + ')') (T '허락하면 업데이트합니다 (-Update pwsh)' 'updated if you allow it (-Update pwsh)') $uacHint
    } elseif ($pw.where -ne 'session') {
        Add-RestartItem 'S2' 'required' 'pwsh' ((T '안정판 ' 'stable ') + $pw.version + ', ' + $srcText)
    } else {
        $note = ''
        if ($pw.onPath.Count -gt 0 -and $pw.onPath[0].kind -eq 'preview') {
            $note = T '; PATH 에서는 미리보기(preview) 버전이 먼저 잡힙니다' '; a preview build comes first on PATH'
        }
        Add-Item 'S2' 'required' 'pwsh' 'ok' ((T '안정판 ' 'stable ') + $pw.version + ' (' + $tail + ')' + $note)
    }
} elseif ($pw.preview) {
    Set-Flag 'needs'
    if ($pw.onPath.Count -gt 0) {
        $script:pkgInfo['pwsh'] = @{ where = 'session'; path = $pw.onPath[0].path; version = $(if ($pw.onPath[0].text -ne '?') { $pw.onPath[0].text } else { '' }); source = 'path' }
    }
    $only = T '미리보기(preview) 버전만 있고 안정판이 없습니다' 'only a preview build is installed, no stable one'
    if ($pathText) { $only += ': ' + $pathText }
    Add-Item 'S2' 'required' 'pwsh' 'fail' $only $pwshInstallAct $pwshInstallHints
} elseif ($pw.onPath.Count -gt 0) {
    $script:pkgInfo['pwsh'] = @{ where = 'session'; path = $pw.onPath[0].path; version = ''; source = 'path' }
    Add-Item 'S2' 'required' 'pwsh' 'unverified' ((T '버전을 읽지 못했습니다: ' 'could not read the version: ') + $pathText)
} elseif ($pw.where -eq 'registry') {
    Add-RestartItem 'S2' 'required' 'pwsh' (Get-App 'pwsh' $script:sessionPath).apps[0].Source
} else {
    Set-Flag 'needs'
    Add-Item 'S2' 'required' 'pwsh' 'fail' (T 'PowerShell 7 이 없습니다. Claude Code 의 PowerShell 도구가 이것으로 실행됩니다.' 'PowerShell 7 not found. Claude Code runs its PowerShell tool with it.') $pwshInstallAct $pwshInstallHints
}

# S4 uv -------------------------------------------------------------------------
$uvFound = Get-App 'uv' $script:sessionPath
$uvApps = $uvFound.apps
$uvOk = $false
$uvPath = ''
$script:pkgInfo['uv'] = @{ where = $uvFound.where; path = ''; version = ''; method = '' }
if ($uvFound.where -eq 'none') {
    Set-Flag 'needs'
    Add-Item 'S4' 'required' 'uv' 'fail' (T 'uv 를 찾을 수 없습니다. gatekit 은 uv 가 필요합니다(Python 은 uv 가 알아서 받습니다).' 'uv not found. gatekit needs uv (it fetches Python by itself).') `
        (T '허락하면 설치합니다 (-Install uv). 직접 하려면 아래 중 하나를 실행하세요' 'installed if you allow it (-Install uv). To do it yourself run ONE of these') `
        @(('winget install --id=' + $script:pkgs['uv'].winget_id + ' -e'), ('powershell -ExecutionPolicy ByPass -c "irm ' + $script:pkgs['uv'].official_script_url + ' | iex"'), (T '설치 후 새 터미널(또는 Claude 창 재시작)에서 다시 실행하세요' 'after installing, run this again from a new terminal (or restart the Claude window)'))
} elseif ($uvFound.where -eq 'registry') {
    Add-RestartItem 'S4' 'required' 'uv' $uvApps[0].Source
} else {
    $uvPath = $uvApps[0].Source
    $uvProbe = Invoke-Proc $uvPath @('--version') 20
    $uvVer = Get-VersionFrom $uvProbe.Out
    $m = Get-UvMethod $uvPath
    $script:pkgInfo['uv'] = @{ where = 'session'; path = $uvPath; version = $(if ($uvVer) { $uvVer.ToString() } else { '' }); method = $m.method }
    if (Test-ExecDenied $uvProbe) {
        # Present but Windows refuses to start it: a reinstall puts the same file back and is
        # refused again, so it is a policy block, not "reinstall it".
        Set-Flag 'blocked'
        Add-Item 'S4' 'required' 'uv' 'fail' (T ('조직 정책이 uv 실행을 막고 있습니다(Windows 오류 ' + $uvProbe.StartError + '): ' + $uvPath) ('an organisation policy blocks uv from running (Windows error ' + $uvProbe.StartError + '): ' + $uvPath)) `
            (T '다시 설치해도 해결되지 않습니다. IT 담당자에게 문의하세요. 정책을 우회하지 마세요.' 'a reinstall does not fix this. Ask your IT contact. Do not work around the policy.') `
            @((T 'IT 담당자에게 보낼 문의문: ' 'Message for your IT contact: ') + (New-ExecDeniedInquiry $uvPath $uvProbe.StartError))
    } elseif (-not $uvVer) {
        Set-Flag 'needs'
        Add-Item 'S4' 'required' 'uv' 'fail' ((T '실행해서 버전을 읽지 못했습니다: ' 'could not run it to read the version: ') + $uvPath) (T '허락하면 다시 설치합니다 (-Install uv 또는 -Update uv)' 'reinstalled if you allow it (-Install uv or -Update uv)')
    } elseif ($uvVer -lt $uvMinimum) {
        Set-Flag 'needs'
        Add-Item 'S4' 'required' 'uv' 'fail' ('uv ' + $uvVer + ' < ' + $uvMinimum + ' (' + $m.method + ')') ((T '업데이트가 필요합니다: ' 'update needed: ') + (Get-UvUpdateAdvice $m.method) + (T ' (허락하면 -Update uv)' ' (or -Update uv if you allow it)'))
    } elseif ($m.receipt -eq 'broken') {
        Add-Item 'S4' 'required' 'uv' 'warn' ('uv ' + $uvVer + ' (' + $m.method + '); ' + (T 'uv-receipt.json 이 깨져 uv self update 가 실패합니다' 'uv-receipt.json is broken so uv self update fails')) (T '허락하면 공식 설치 스크립트로 복구합니다 (-Update uv)' 'repaired with the official installer if you allow it (-Update uv)')
        $uvOk = $true
    } else {
        Add-Item 'S4' 'required' 'uv' 'ok' ('uv ' + $uvVer + ' (' + $m.method + ', ' + (T '최신 여부는 확인하지 않음' 'latest not checked') + ')')
        $uvOk = $true
    }
}

# S5 .venv ----------------------------------------------------------------------
# state: ok (python runs) / missing (nothing there) / broken (python.exe 0 bytes, its Python
# home is gone, or it does not start) / old (below the minimum) / denied (python.exe is there but
# Windows refuses to start it because of a policy: never deleted, never rebuilt).
function Get-PythonVersion {
    $pv = Invoke-Proc $venvPy @('-c', "import sys;print('%d.%d.%d' % sys.version_info[:3])") 20
    $script:venvDenied = 0
    if (Test-ExecDenied $pv) { $script:venvDenied = $pv.StartError }
    if ($pv.Code -eq 0 -and -not $pv.TimedOut -and $pv.Out.Trim()) { return $pv.Out.Trim() }
    return ''
}

function Test-VenvHealth {
    $cfgFile = Join-Path $venvDir 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $venvPy)) {
        if (Test-Path -LiteralPath $cfgFile) { return @{ state = 'broken'; reason = (T 'python.exe 가 없습니다' 'python.exe is missing'); version = '' } }
        return @{ state = 'missing'; reason = ''; version = '' }
    }
    if ((Get-Item -LiteralPath $venvPy).Length -eq 0) {
        return @{ state = 'broken'; reason = (T 'python.exe 가 0바이트입니다' 'python.exe is 0 bytes'); version = '' }
    }
    if (Test-Path -LiteralPath $cfgFile) {
        $home_ = $null
        foreach ($cl in (Get-Content -LiteralPath $cfgFile -ErrorAction SilentlyContinue)) {
            if ($cl -match '^\s*home\s*=\s*(.+?)\s*$') { $home_ = $Matches[1] }
        }
        if ($home_ -and -not (Test-Path -LiteralPath $home_)) {
            return @{ state = 'broken'; reason = (T ('pyvenv.cfg 의 Python 경로가 없습니다(' + $home_ + ')') ('the Python path in pyvenv.cfg is gone (' + $home_ + ')')); version = '' }
        }
    }
    $v = Get-PythonVersion
    if (-not $v -and $script:venvDenied) { return @{ state = 'denied'; reason = ''; version = '' } }
    if (-not $v) { return @{ state = 'broken'; reason = (T 'python.exe 가 실행되지 않습니다' 'python.exe does not start'); version = '' } }
    $pv = Get-VersionFrom $v
    if ($pv -and $pv -lt $pythonMinimum) {
        return @{ state = 'old'; reason = (T ('python ' + $v + ' 은(는) 필요한 ' + $pythonMinimum.Major + '.' + $pythonMinimum.Minor + ' 보다 낮습니다') ('python ' + $v + ' is older than the required ' + $pythonMinimum.Major + '.' + $pythonMinimum.Minor)); version = $v }
    }
    return @{ state = 'ok'; reason = ''; version = $v }
}

# The .venv python.exe exists but a policy keeps it from starting. The hooks start the same file,
# so they are off too. Rebuilding the folder would put the same file back: nothing is deleted.
function Add-VenvDeniedItem {
    Set-Flag 'blocked'
    Add-Item 'S5' 'required' '.venv' 'fail' (T ('조직 정책이 .venv 의 python.exe 실행을 막고 있습니다(Windows 오류 ' + $script:venvDenied + '). gatekit 훅도 같은 이유로 동작하지 않습니다: ' + $venvPy) ('an organisation policy blocks the .venv python.exe from running (Windows error ' + $script:venvDenied + '). The gatekit hooks are off for the same reason: ' + $venvPy)) `
        (T '.venv 를 다시 만들어도 해결되지 않습니다. IT 담당자에게 문의하세요. 정책을 우회하지 마세요.' 'rebuilding the .venv does not fix this. Ask your IT contact. Do not work around the policy.') `
        @((T 'IT 담당자에게 보낼 문의문: ' 'Message for your IT contact: ') + (New-ExecDeniedInquiry $venvPy $script:venvDenied))
}

$venvReady = $false
$wantVenv = ($installList -contains 'venv')
$script:currentAction = 'install'
if ($Status) {
    Say 'info' 'S5' '.venv' (T '-Status 는 .venv, 설정, 닥터를 건너뜁니다' '-Status skips the .venv, the config and doctor')
} elseif (-not $uvOk) {
    Add-Item 'S5' 'required' '.venv' 'unverified' (T 'uv 가 준비되지 않아 확인하지 못했습니다' 'not checked because uv is not ready')
} else {
    $health = Test-VenvHealth
    $venvRel = '.claude/gatekit/.venv'
    if ($health.state -eq 'ok') {
        $msg = T ('python ' + $health.version + ' 준비됨') ('python ' + $health.version + ' ready')
        if ($wantVenv) { $msg = (T '이미 준비되어 있어 건너뜁니다: ' 'already ready, skipped: ') + $msg }
        Add-Item 'S5' 'required' '.venv' 'ok' $msg
        $venvReady = $true
    } elseif ($health.state -eq 'denied') {
        Add-VenvDeniedItem
    } elseif (($health.state -eq 'broken' -or $health.state -eq 'old') -and -not $wantVenv) {
        Set-Flag 'needs'
        $damageVerdict = 'fail'
        $damage = T ('.venv 가 손상되었습니다: ' + $health.reason) ('the .venv is damaged: ' + $health.reason)
        if ($health.state -eq 'old') { $damageVerdict = 'warn'; $damage = T ('.venv 의 Python 이 너무 낮습니다: ' + $health.reason) ('the .venv Python is too old: ' + $health.reason) }
        Add-Item 'S5' 'required' '.venv' $damageVerdict $damage `
            (T ('허락하면 손상된 ' + $venvRel + ' 폴더를 지우고 다시 만듭니다. Python 과 패키지를 내려받을 수 있습니다(수십 MB) (-Install venv)') ('if you allow it, the damaged ' + $venvRel + ' folder is deleted and rebuilt. Python and packages may be downloaded (tens of MB) (-Install venv)'))
    } else {
        if ($health.state -eq 'broken' -or $health.state -eq 'old') {
            Say 'warn' 'S5-delete' '.venv' (T ('손상되었거나 낮은 버전의 폴더를 지우고 다시 만듭니다: ' + $venvDir + ' (' + $health.reason + ')') ('deleting the damaged or outdated folder and rebuilding it: ' + $venvDir + ' (' + $health.reason + ')'))
            if ((Split-Path -Leaf $venvDir) -eq '.venv') { Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue }
        }
        $syncArgs = @('sync', '--project', $kit, '--frozen', '--no-dev')
        if ($wantVenv) {
            Say 'info' 'S5-sync' '.venv' (T 'uv sync --frozen --no-dev 실행: Python 과 패키지를 내려받으므로(수십 MB) 네트워크가 필요하고 몇 분 걸릴 수 있습니다.' 'running uv sync --frozen --no-dev: it downloads Python and packages (tens of MB), so it needs the network and can take a few minutes.')
        } else {
            $syncArgs += '--no-python-downloads'
            Say 'info' 'S5-sync' '.venv' (T 'uv sync --frozen --no-dev --no-python-downloads 실행: 아무것도 내려받지 않습니다.' 'running uv sync --frozen --no-dev --no-python-downloads: nothing is downloaded.')
        }
        $sync = Invoke-Proc $uvPath $syncArgs $syncTimeout
        $text = $sync.Out
        $hints = @(($text -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -Last 6 | ForEach-Object { '  ' + $_.Trim() })
        if ($sync.TimedOut) {
            Set-Flag 'blocked'
            Add-Item 'S5' 'required' '.venv' 'fail' (T ('uv sync 가 ' + $syncTimeout + '초 안에 끝나지 않아 중단했습니다') ('uv sync did not finish within ' + $syncTimeout + ' seconds and was stopped')) (T '네트워크를 확인하고 다시 시도하세요' 'check the network and try again') $hints
        } elseif ($sync.Code -eq 0) {
            $v = Get-PythonVersion
            if ($v) {
                Add-Item 'S5' 'required' '.venv' 'ok' (T ('uv sync --frozen --no-dev: python ' + $v + ' 준비됨') ('uv sync --frozen --no-dev: python ' + $v + ' ready'))
                $venvReady = $true
            } elseif ($script:venvDenied) {
                Add-VenvDeniedItem
            } else {
                Set-Flag 'fail'
                Add-Item 'S5' 'required' '.venv' 'fail' (T 'uv sync 는 끝났지만 .venv 의 python.exe 가 실행되지 않습니다' 'uv sync finished but the .venv python.exe does not start') '' $hints
            }
        } elseif (-not $wantVenv -and ($text -match '(?i)no interpreter found|no (suitable )?python (interpreter|installation|version)|downloads? (are )?(disabled|not allowed)|python.{0,40}(not found|not available)')) {
            Set-Flag 'needs'
            Add-Item 'S5' 'required' '.venv' 'warn' (T '이 PC 에서 쓸 수 있는 Python 을 찾지 못했습니다. uv 가 Python 을 받아야 합니다(수십 MB, 네트워크 필요).' 'no usable Python was found on this PC. uv must download Python (tens of MB, network needed).') `
                (T '허락하면 Python 과 패키지(수십 MB)를 내려받아 .venv 를 만듭니다 (-Install venv)' 'if you allow it, Python and packages (tens of MB) are downloaded to build the .venv (-Install venv)') $hints
        } elseif (Test-NetworkText $text) {
            Set-Flag 'blocked'
            $hints += (T '프록시/회사 인증서 환경이면 UV_SYSTEM_CERTS=1, SSL_CERT_FILE, HTTPS_PROXY, UV_PYTHON_INSTALL_MIRROR 를 확인하세요. 계속되면 IT 담당자에게 문의하세요.' 'behind a proxy or a company certificate, check UV_SYSTEM_CERTS=1, SSL_CERT_FILE, HTTPS_PROXY and UV_PYTHON_INSTALL_MIRROR. If it keeps failing, ask your IT contact.')
            Add-Item 'S5' 'required' '.venv' 'fail' (T 'uv sync 실패: 네트워크 문제로 보입니다' 'uv sync failed: looks like a network problem') (T '온라인에서 다시 시도하세요' 'try again when online') $hints
        } else {
            Set-Flag 'fail'
            Add-Item 'S5' 'required' '.venv' 'fail' (T 'uv sync 실패' 'uv sync failed') '' $hints
        }
    }
}

if ($wantVenv -and -not $Status) {
    if ($venvReady) { Remove-FailureRecord 'venv' }
    elseif ($uvOk) {
        $venvCls = 'unknown'
        if ($script:flags.blocked) { $venvCls = 'network' }
        if ($script:venvDenied) { $venvCls = 'policy' }
        Add-FailureRecord 'venv' 'install' $venvCls '' (T '.venv 를 만들지 못했습니다' 'the .venv could not be built')
    }
}

# S12 config and settings --------------------------------------------------------
if (-not $Status) {
$cfg = Join-Path $projectRoot '.gatekit\config.json'
if (Test-Path -LiteralPath $cfg) {
    Add-Item 'S12-config' 'required' '.gatekit/config.json' 'ok' (T '이미 있어 그대로 둡니다' 'exists, left as is')
} elseif (-not $venvReady) {
    Add-Item 'S12-config' 'required' '.gatekit/config.json' 'unverified' (T '.venv 가 없어 만들지 못했습니다' 'not created because .venv is not ready')
} else {
    $cr = Invoke-Proc $venvPy @($launcher, 'workers', 'set-default', 'claude', '--root', $projectRoot) 60
    if ($cr.Code -eq 0 -and (Test-Path -LiteralPath $cfg)) {
        Add-Item 'S12-config' 'required' '.gatekit/config.json' 'ok' (T '생성함(기본 워커: claude)' 'created (default worker: claude)')
    } else {
        Set-Flag 'fail'
        $why = ''
        if ($cr.TimedOut) { $why = T '제한 시간(60초)을 넘겨 중단했습니다' 'stopped after the 60 second limit' }
        Add-Item 'S12-config' 'required' '.gatekit/config.json' 'fail' ((T '생성 실패' 'could not be created') + $(if ($why) { ': ' + $why } else { '' })) '' @(($cr.Out -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -Last 5 | ForEach-Object { '  ' + $_.Trim() })
    }
}

# Events whose PowerShell hook lacks -NoProfile -ExecutionPolicy Bypass.
function Get-HooksMissingPsFlags($settings) {
    $bad = @()
    foreach ($ev in $settings.hooks.PSObject.Properties) {
        foreach ($group in @($ev.Value)) {
            foreach ($hook in @($group.hooks)) {
                $leaf = ("$($hook.command)" -replace '\\', '/').Split('/')[-1].ToLower()
                if ($leaf -notmatch '^(powershell|pwsh)(\.exe)?$') { continue }
                $al = @(@($hook.args) | ForEach-Object { "$_".ToLower() })
                $ok = ($al -contains '-noprofile')
                $i = [array]::IndexOf($al, '-executionpolicy')
                if ($i -lt 0 -or ($i + 1) -ge $al.Count -or $al[$i + 1] -ne 'bypass') { $ok = $false }
                if (-not $ok -and $bad -notcontains $ev.Name) { $bad += $ev.Name }
            }
        }
    }
    return $bad
}

$settingsFile = Join-Path $projectRoot '.claude\settings.json'
if (-not (Test-Path -LiteralPath $settingsFile)) {
    Set-Flag 'fail'
    Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T '없습니다: 훅이 등록되지 않았습니다' 'missing: hooks are not registered') (Get-RestoreAdvice '.claude/settings.json')
} else {
    $settings = $null
    try { $settings = (Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
    if (-not $settings -or -not $settings.hooks) {
        Set-Flag 'fail'
        Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T 'JSON 이 깨졌거나 hooks 가 없습니다' 'invalid JSON or no hooks') (Get-RestoreAdvice '.claude/settings.json')
    } else {
        $rawSettings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8
        $hasStart = ($settings.hooks.SessionStart -and $rawSettings -match 'session-check\.ps1')
        $hasGate = ($rawSettings -match 'bin/gatekit\.py')
        $noFlags = @(Get-HooksMissingPsFlags $settings)
        # The PowerShell tool must be on (env) and the input-box ! commands must use it too.
        $psTool = ($settings.env -and [string]$settings.env.CLAUDE_CODE_USE_POWERSHELL_TOOL -eq '1')
        $psShell = ([string]$settings.defaultShell -eq 'powershell')
        if (-not ($hasStart -and $hasGate)) {
            Set-Flag 'fail'
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T 'gatekit 훅 등록이 빠져 있습니다' 'gatekit hook registrations are missing') (Get-RestoreAdvice '.claude/settings.json')
        } elseif ($noFlags.Count -gt 0) {
            Set-Flag 'fail'
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T ('PowerShell 훅에 -NoProfile -ExecutionPolicy Bypass 가 없습니다: ' + ($noFlags -join ', ')) ('PowerShell hook without -NoProfile -ExecutionPolicy Bypass: ' + ($noFlags -join ', '))) (Get-RestoreAdvice '.claude/settings.json')
        } elseif (-not ($psTool -and $psShell)) {
            Set-Flag 'needs'
            $missing = @()
            if (-not $psTool) { $missing += 'env.CLAUDE_CODE_USE_POWERSHELL_TOOL = "1"' }
            if (-not $psShell) { $missing += 'defaultShell = "powershell"' }
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' ((T 'PowerShell 설정이 빠져 있습니다: ' 'PowerShell settings are missing: ') + ($missing -join ', ')) (T '.claude/settings.json 에 위 값을 넣으세요(다른 내용은 그대로 둡니다)' 'add the values above to .claude/settings.json (leave everything else as it is)')
        } else {
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'ok' (T '훅 등록과 PowerShell 도구 설정 확인(SessionStart, 게이트, -NoProfile -ExecutionPolicy Bypass)' 'hooks and PowerShell settings in place (SessionStart, gates, -NoProfile -ExecutionPolicy Bypass, env, defaultShell)')
        }
    }
}

}

# S6 claude ---------------------------------------------------------------------
$claudeFound = Get-App 'claude' $script:sessionPath
$claudeApps = $claudeFound.apps
$script:pkgInfo['claude'] = @{ where = $claudeFound.where; path = ''; version = '' }
# Required only in a project whose settings start the CLI (Test-CliRequired, common.ps1).
# Otherwise recommended: every verdict below is at most a warn and no exit flag is set.
$cliRequired = Test-CliRequired $projectRoot
$claudeLevel = 'recommended'
if ($cliRequired) { $claudeLevel = 'required' }
if ($claudeFound.where -eq 'none' -and -not $cliRequired) {
    Add-Item 'S6' $claudeLevel 'claude CLI' 'warn' (T 'PATH 에 claude 가 없습니다. 지금 설정에서는 필요 없습니다. build 를 워커 방식으로 돌릴 때만 필요합니다.' 'claude is not on PATH. The current settings do not need it; it is needed only when build runs its tasks as workers.') (T '허락하면 설치합니다 (-Install claude)' 'installed if you allow it (-Install claude)')
} elseif ($claudeFound.where -eq 'none') {
    Set-Flag 'needs'
    Add-Item 'S6' $claudeLevel 'claude CLI' 'fail' (T 'PATH 에 claude 가 없습니다(데스크톱 앱만으로는 CLI 가 없습니다). 워커를 실행할 수 없습니다.' 'claude is not on PATH (the desktop app alone does not include the CLI). Workers cannot start.') (T '허락하면 설치합니다 (-Install claude)' 'installed if you allow it (-Install claude)')
} elseif ($claudeFound.where -eq 'registry') {
    Add-RestartItem 'S6' $claudeLevel 'claude CLI' $claudeApps[0].Source $cliRequired
} else {
    $cp = Invoke-Proc $claudeApps[0].Source @('--version') 30
    $cv = Get-VersionFrom $cp.Out
    $script:pkgInfo['claude'] = @{ where = 'session'; path = $claudeApps[0].Source; version = $(if ($cv) { $cv.ToString() } else { '' }) }
    if (-not $cv) {
        Add-Item 'S6' $claudeLevel 'claude CLI' 'unverified' ((T 'PATH 에 있으나 버전을 읽지 못했습니다: ' 'on PATH but the version could not be read: ') + $claudeApps[0].Source)
    } elseif ($cv -lt $claudeRecommended) {
        Add-Item 'S6' $claudeLevel 'claude CLI' 'warn' ('claude ' + $cv + ' < ' + $claudeRecommended + (T ' (권장)' ' (recommended)')) (T '허락하면 업데이트합니다 (-Update claude)' 'updated if you allow it (-Update claude)')
    } else {
        Add-Item 'S6' $claudeLevel 'claude CLI' 'ok' ('claude ' + $cv)
    }
}

# S7 git ------------------------------------------------------------------------
$gitFound = Get-App 'git' $script:sessionPath
$gitApps = $gitFound.apps
$script:pkgInfo['git'] = @{ where = $gitFound.where; path = ''; version = '' }
if ($gitFound.where -eq 'none') {
    Add-Item 'S7' 'info' 'git' 'info' (T 'Git for Windows 가 없습니다. Claude Code 는 PowerShell 도구로 동작합니다.' 'Git for Windows not found. Claude Code works through its PowerShell tool.') (T '필요하면 직접 설치하세요(관리자 권한이 필요할 수 있음)' 'install it yourself if you want it (it may need administrator rights)')
} elseif ($gitFound.where -eq 'registry') {
    Add-RestartItem 'S7' 'info' 'git' $gitApps[0].Source
} else {
    $gp = Invoke-Proc $gitApps[0].Source @('--version') 15
    $gv = Get-VersionFrom $gp.Out
    $script:pkgInfo['git'] = @{ where = 'session'; path = $gitApps[0].Source; version = $(if ($gv) { $gv.ToString() } else { '' }) }
    Add-Item 'S7' 'info' 'git' 'info' $gp.Out.Trim()
}

# S19 package table (winget-managed programs) --------------------------------------
# Parses `winget list --id <id> -e` without relying on the (localized) header: the data line
# is the one that holds the id; the words after it are version, [available], [source].
function Get-WingetListInfo([string]$id) {
    $res = @{ state = 'error'; version = ''; available = ''; source = '' }
    $w = Find-App 'winget' $script:sessionPath
    if ($w.Count -eq 0) { return $res }
    $r = Invoke-Proc $w[0].Source @('list', '--id', $id, '-e', '--disable-interactivity') $listTimeout
    if ($r.TimedOut -or -not $r.Started) { $res.state = 'timeout'; return $res }
    foreach ($line in ($r.Out -split "`r?`n")) {
        $m = [regex]::Match($line, '(?i)(^|\s)' + [regex]::Escape($id) + '(\s+(.*))?$')
        if (-not $m.Success) { continue }
        $tokens = @(("$($m.Groups[3].Value)".Trim()) -split '\s+' | Where-Object { $_ })
        if ($tokens.Count -gt 0 -and ($tokens[-1] -eq 'winget' -or $tokens[-1] -eq 'msstore')) {
            $res.source = $tokens[-1]
            $tokens = @($tokens | Select-Object -First ($tokens.Count - 1))
        }
        if ($tokens.Count -gt 0 -and $tokens[0] -match '^[<>~]+$' -and $tokens.Count -gt 1) { $tokens = @($tokens | Select-Object -Skip 1) }
        if ($tokens.Count -ge 1) { $res.version = ($tokens[0] -replace '^[<>~]+', '') }
        if ($tokens.Count -ge 2) { $res.available = ($tokens[1] -replace '^[<>~]+', '') }
        $res.state = 'found'
        return $res
    }
    if ($r.Code -ne 0) { $res.state = 'notfound' }
    return $res
}

function Get-PkgMethodText([string]$key, $info, [string]$wingetSource) {
    if ($wingetSource -eq 'winget') { return 'winget' }
    $p = "$($info.path)"
    if ($key -eq 'uv') {
        switch ($info.method) {
            'winget' { return 'winget' }
            'standalone' { return (T '공식 스크립트' 'official script') }
            'scoop' { return (T '기타(scoop)' 'other (scoop)') }
            'pip' { return (T '기타(pip)' 'other (pip)') }
        }
        return (T '기타(알 수 없음)' 'other (unknown)')
    }
    if ($p -match '(?i)\\WinGet\\') { return 'winget' }
    if ($key -eq 'claude') {
        if ($p -match '(?i)\\\.local\\bin\\') { return (T '공식 스크립트' 'official script') }
        if ($p -match '(?i)\\npm\\') { return (T '기타(npm)' 'other (npm)') }
    }
    if ($key -eq 'pwsh') {
        if ($info.source -eq 'package') { return (T 'MSIX(winget 또는 스토어)' 'MSIX (winget or Store)') }
        if ($info.source -eq 'msi') { return (T '기타(MSI)' 'other (MSI)') }
        if (Test-PwshMsiPath $p) { return (T '기타(MSI)' 'other (MSI)') }
        if ($p -match '(?i)\\WindowsApps\\') { return (T 'MSIX(winget 또는 스토어)' 'MSIX (winget or Store)') }
    }
    return (T '기타' 'other')
}

if ($script:pkgs.Count -ge 5) {
    $wingetOkForList = ($wingetFound.where -eq 'session' -and $script:agreementOk)
    $noListReason = T 'winget 약관 동의가 확인되지 않아 업데이트 조회를 하지 않았습니다' 'winget agreements are not confirmed, so the update lookup was not run'
    if ($wingetFound.where -eq 'none') { $noListReason = T 'winget 이 없어 업데이트 조회를 하지 않았습니다' 'winget is missing, so the update lookup was not run' }
    foreach ($key in @('pwsh', 'uv', 'claude', 'git')) {
        $pkg = $script:pkgs[$key]
        $info = $script:pkgInfo[$key]
        $lvl = 'info'
        if ($pkg.level -eq '필수') { $lvl = 'required' } elseif ($pkg.level -eq '권장') { $lvl = 'recommended' }
        $rowName = (T '패키지 ' 'package ') + $key
        if (-not $info -or $info.where -eq 'none') {
            Add-Item ('P-' + $key) $lvl $rowName 'info' ((T '설치 안 됨' 'not installed') + ' (winget ' + $pkg.winget_id + ')')
            continue
        }
        if ($info.where -eq 'registry') {
            Add-Item ('P-' + $key) $lvl $rowName 'info' (T '설치되어 있지만 이 창에서는 보이지 않음(재시작 필요)' 'installed but not visible in this session (restart needed)')
            continue
        }
        $verText = $info.version
        if (-not $verText) { $verText = T '버전 모름' 'version unknown' }
        $verdict = 'unverified'
        $upd = $noListReason
        $wsrc = ''
        $action = ''
        if ($wingetOkForList) {
            $wl = Get-WingetListInfo $pkg.winget_id
            $wsrc = $wl.source
            $mismatch = ''
            if ($wl.state -eq 'found' -and $wl.version -and $info.version -and -not ($info.version.StartsWith($wl.version) -or $wl.version.StartsWith($info.version))) {
                $mismatch = T (' (winget 은 다른 설치 ' + $wl.version + ' 를 가리킵니다)') (' (winget lists a different install, ' + $wl.version + ')')
            }
            if ($wl.state -eq 'found' -and $wl.available) {
                $verdict = 'warn'
                $upd = (T '업데이트 가능: ' 'update available: ') + $wl.available + $mismatch
                if ($key -eq 'git') { $action = T '관리자 권한이 필요할 수 있어 직접 업데이트하세요' 'it may need administrator rights, so update it yourself' }
                else { $action = T ('허락하면 업데이트합니다 (-Update ' + $key + ')') ('updated if you allow it (-Update ' + $key + ')') }
            } elseif ($wl.state -eq 'found') {
                $verdict = 'ok'
                $upd = (T '최신입니다(winget 확인)' 'up to date (checked with winget)') + $mismatch
            } elseif ($wl.state -eq 'notfound') {
                $upd = T 'winget 이 관리하는 설치가 아니어서 업데이트 여부를 확인하지 못했습니다' 'not a winget-managed install, so the update state could not be checked'
            } elseif ($wl.state -eq 'timeout') {
                $upd = T '제한 시간 안에 확인하지 못했습니다' 'could not be checked in time'
            } else {
                $upd = T '업데이트 여부를 확인하지 못했습니다' 'the update state could not be checked'
            }
        }
        $method = Get-PkgMethodText $key $info $wsrc
        Add-Item ('P-' + $key) $lvl $rowName $verdict ((T '설치됨 ' 'installed ') + $verText + ' | ' + (T '설치 방법: ' 'method: ') + $method + ' | ' + $upd) $action
    }
    $recorded = @(Read-FailureRecords)
    if ($recorded.Count -gt 0) {
        $lines = @()
        foreach ($f in $recorded) { $lines += ("$($f.item) $($f.action): $($f.class), 0x" + ('{0:X8}' -f [int]$f.exit_code) + ' ' + "$($f.time)") }
        Add-Item 'P-failures' 'info' (T '지난 실패 기록' 'recorded failures') 'warn' ($lines -join '; ') (T '허락하면 같은 동작만 다시 시도합니다 (-RetryFailed)' 'retried with the same action if you allow it (-RetryFailed)')
    } else {
        Add-Item 'P-failures' 'info' (T '지난 실패 기록' 'recorded failures') 'ok' (T '없음' 'none')
    }
}

# S18 node (only with a package.json) ---------------------------------------------
if (Test-Path -LiteralPath (Join-Path $projectRoot 'package.json')) {
    $nodeText = T '없음' 'missing'
    $npmText = T '없음' 'missing'
    $nodeApp = Find-App 'node' $script:sessionPath
    $npmApp = Find-App 'npm' $script:sessionPath
    if ($nodeApp.Count -gt 0) { $nodeText = (Invoke-Proc $nodeApp[0].Source @('--version') 15).Out.Trim() }
    if ($npmApp.Count -gt 0) { $npmText = (Invoke-Proc $npmApp[0].Source @('--version') 20).Out.Trim() }
    Add-Item 'S18' 'info' 'node/npm' 'info' ('node ' + $nodeText + ', npm ' + $npmText + ' (' + (T 'gatekit 자체는 Node 가 필요 없고, 사용자 프로젝트 게이트용입니다' 'gatekit itself does not need Node; it is for your project gates') + ')')
}

# S23 python stub ---------------------------------------------------------------
$pyApp = Find-App 'python' $script:sessionPath
if ($pyApp.Count -gt 0 -and $pyApp[0].Source -match '(?i)\\WindowsApps\\') {
    Add-Item 'S23' 'info' 'python' 'info' (T 'WindowsApps 의 python 은 스토어 안내용 스텁일 수 있어 사용하지 않습니다. gatekit 은 uv 가 관리하는 .venv 의 Python 만 씁니다.' 'the python in WindowsApps may be a Store stub and is not used. gatekit only uses the uv-managed .venv Python.')
}

# S15 doctor --------------------------------------------------------------------
if ($Status) {
    Say 'info' 'S15' 'doctor' (T '-Status 는 닥터를 건너뜁니다' '-Status skips doctor')
} elseif (-not $venvReady) {
    Add-Item 'S15' 'required' 'doctor' 'unverified' (T '.venv 가 없어 실행하지 못했습니다' 'not run because .venv is not ready')
} else {
    $dr = Invoke-Proc $venvPy @($launcher, 'doctor', '--root', $projectRoot, '--lang', $script:langMode) 120
    $doctorOut = @(($dr.Out -split "`r?`n") | Where-Object { $_.Trim() })
    if ($dr.TimedOut) {
        Set-Flag 'fail'
        Add-Item 'S15' 'required' 'doctor' 'fail' (T '제한 시간(120초)을 넘겨 중단했습니다' 'stopped after the 120 second limit') '' $doctorOut
    } elseif ($dr.Code -eq 0) {
        Add-Item 'S15' 'required' 'doctor' 'ok' (T '실패한 축 없음' 'no failing axis') '' $doctorOut
    } else {
        Set-Flag 'fail'
        Add-Item 'S15' 'required' 'doctor' 'fail' (T '실패한 축이 있습니다(아래 해결 줄 참고)' 'at least one axis failed (see the fix lines below)') '' $doctorOut
    }
}

Complete-Run
