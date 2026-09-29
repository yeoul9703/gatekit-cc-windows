# gatekit setup (Windows PowerShell 5.1 compatible).
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 [switches]
#
# Switches
#   (none)            check only: nothing is installed or updated. The one exception is the
#                     project's own .venv: if it is missing, ONE `uv sync --frozen --no-dev
#                     --no-python-downloads` is tried (it never downloads Python and never
#                     deletes anything). Everything else needs a name in -Install / -Update.
#   -Install <list>   install the listed items. Allowed names: pwsh, uv, claude, git, venv.
#                     "venv" builds .claude/gatekit/.venv WITH downloads (Python and packages,
#                     tens of MB) and deletes and rebuilds a broken .venv. Only this switch may.
#   -Update <list>    update the listed programs (pwsh, uv, claude, git; not venv).
#   -Json             print ONE ASCII-only JSON object {exit_code, exit_meaning, items:[{id,level,
#                     name,verdict,detail,action,hints}]}. Non-ASCII text is written as \uXXXX.
#                     Every line (skipped / done / progress too) is one item.
#   -Lang ko|en       output language, one language per line. Default: ko if the Windows UI
#                     language is Korean, otherwise en.
# Any other name in -Install / -Update is refused with exit code 1.
# -Install / -Update are the user's permission: the chat asked first. Only calls
# made for a listed name pass --accept-source-agreements / --accept-package-agreements.
# Only user-scope installs run automatically. Anything that needs administrator
# rights (git) is never run here; the script prints what to do instead.
#
# Every line: [ok|warn|fail|unverified|info] name: result - next action
# Nothing here asks a question (no Read-Host); winget always gets --disable-interactivity.
# Every external call has a timeout; on timeout the whole process tree is killed (taskkill /T /F).
#
# The check looks at the PATH of THIS session only (the same rule as session-check.ps1).
# A program that is visible only after merging the registry PATH (Machine + User) is reported
# as warn and exit 3: close the Claude app (VS Code window) completely and open it again.
#
# Exit codes (when several problems mix, the FIRST matching row wins):
#   1  something failed that a permission cannot fix (bad switch, .venv or config
#      could not be built, doctor failed, an install failed for an unknown reason)
#   4  blocked by policy or network (winget policy block, no network, TLS)
#   3  a program is installed but not visible in this session (PATH), or a reboot is
#      needed: close the Claude app (VS Code window) completely and open it again
#   2  the user must allow or do something (a required program is missing or too
#      old, Python must be downloaded, .venv is broken, or a program needs administrator rights)
#   0  ready
# Test hooks (environment): GATEKIT_SETUP_KEEP_PATH=1 never reads the registry PATH;
#   GATEKIT_SETUP_REGISTRY_PATH replaces the registry PATH value; GATEKIT_SETUP_SYNC_TIMEOUT
#   (seconds) replaces the 300 second uv sync limit; GATEKIT_SETUP_MIN_PYTHON (major.minor)
#   replaces the required 3.14 for the .venv Python; GATEKIT_SETUP_OFFICIAL_RUNNER is an
#   executable run instead of the official installer script (it receives the script URL).

param(
    [string[]]$Install = @(),
    [string[]]$Update = @(),
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
$allowed = @('pwsh', 'uv', 'claude', 'git', 'venv')
$uvMinimum = [version]'0.4.27'
$pythonMinimum = [version]'3.14'
if ($env:GATEKIT_SETUP_MIN_PYTHON -match '^\d+\.\d+$') { $pythonMinimum = [version]$env:GATEKIT_SETUP_MIN_PYTHON }
$claudeRecommended = [version]'2.1.277'
$syncTimeout = 300
if ($env:GATEKIT_SETUP_SYNC_TIMEOUT -match '^\d+$') { $syncTimeout = [int]$env:GATEKIT_SETUP_SYNC_TIMEOUT }

$script:sessionPath = $env:Path                     # the PATH this session was started with
$script:items = New-Object System.Collections.ArrayList
$script:flags = @{ fail = $false; blocked = $false; restart = $false; needs = $false }
$script:done = New-Object System.Collections.ArrayList
$script:failedActions = New-Object System.Collections.ArrayList
$script:langMode = 'en'
$script:lastScriptFail = $null
$script:lastWingetFail = $null
$script:showSummary = $true
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

function Get-ExitCode {
    if ($script:flags.fail) { return 1 }
    if ($script:flags.blocked) { return 4 }
    if ($script:flags.restart) { return 3 }
    if ($script:flags.needs) { return 2 }
    return 0
}

# -Json must be pure ASCII: every char above 0x7E becomes \uXXXX.
function ConvertTo-AsciiJson([string]$json) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $json.ToCharArray()) {
        $code = [int]$ch
        if ($code -gt 126) { [void]$sb.AppendFormat('\u{0:x4}', $code) } else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}

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
        3 = (T '재시작 필요: Claude 앱(VS Code 창)을 완전히 닫고 다시 여세요' 'restart needed: close the Claude app (VS Code window) completely and open it again')
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
foreach ($n in (@($installList) + @($updateList))) {
    if ($allowed -notcontains $n) {
        $argsBad = $true
        Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T ('거부됨: "' + $n + '" 은(는) 허용 목록에 없습니다') ('refused: "' + $n + '" is not in the allowed list')) (T ('허용: ' + ($allowed -join ', ')) ('allowed: ' + ($allowed -join ', ')))
    }
}
if ($updateList -contains 'venv') {
    $argsBad = $true
    Add-Item 'args' 'required' (T '스위치' 'switch') 'fail' (T '거부됨: venv 는 -Update 가 아니라 -Install venv 로만 만듭니다' 'refused: venv is built only with -Install venv, not -Update') ''
}
if ($argsBad) { $script:showSummary = $false; Set-Flag 'fail'; Complete-Run }

# ---- process and PATH helpers ------------------------------------------------
function Quote-Arg([string]$a) {
    if ($a -eq '') { return '""' }
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}

# Kills a process and all its children (a plain Kill leaves grandchildren running).
function Stop-ProcTree($p) {
    try {
        $tk = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        if (Test-Path -LiteralPath $tk) { & $tk /T /F /PID $p.Id 2>&1 | Out-Null }
    } catch { }
    try { if (-not $p.HasExited) { $p.Kill() } } catch { }
}

# Runs a program without a shell: stdin closed (nothing can prompt), stdout+stderr
# captured, whole process tree killed after $timeoutSec. Returns Started / TimedOut / Code / Out.
function Invoke-Proc([string]$file, [string[]]$argList, [int]$timeoutSec = 20) {
    $res = [pscustomobject]@{ Started = $false; TimedOut = $false; Code = -1; Out = '' }
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
    }
    return $res
}

# Looks a program up on $pathValue (default: the current process PATH).
function Find-App([string]$name, [string]$pathValue = '') {
    $saved = $env:Path
    if ($pathValue) { $env:Path = $pathValue }
    try { return @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue) }
    finally { $env:Path = $saved }
}

function Get-VersionFrom([string]$text) {
    if ($text -match '(\d+)\.(\d+)\.(\d+)') { return [version]($Matches[1] + '.' + $Matches[2] + '.' + $Matches[3]) }
    return $null
}

# Machine + User PATH from the registry merged with this session's PATH (installers write the
# registry, not the running process). Never assigned to the session: it is only used to tell
# "installed but not visible in this session" apart from "not installed".
function Get-MergedPath {
    if ($env:GATEKIT_SETUP_KEEP_PATH -eq '1') { return $script:sessionPath }
    if ($env:GATEKIT_SETUP_REGISTRY_PATH) {
        $machine = $env:GATEKIT_SETUP_REGISTRY_PATH
        $user = ''
    } else {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    }
    $seen = @{}
    $merged = @()
    foreach ($src in @($machine, $user, $script:sessionPath)) {
        foreach ($e in ("$src" -split ';')) {
            $t = [Environment]::ExpandEnvironmentVariables($e.Trim())
            if ($t) {
                $key = $t.ToLower().TrimEnd('\')
                if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $merged += $t }
            }
        }
    }
    return ($merged -join ';')
}

# where = session (found on this session's PATH) / registry (only after merging the registry
# PATH: restart needed) / none.
function Get-App([string]$name) {
    $s = Find-App $name $script:sessionPath
    if ($s.Count -gt 0) { return @{ apps = $s; where = 'session' } }
    $m = Find-App $name (Get-MergedPath)
    if ($m.Count -gt 0) { return @{ apps = $m; where = 'registry' } }
    return @{ apps = @(); where = 'none' }
}

function Add-RestartItem([string]$id, [string]$level, [string]$name, [string]$found) {
    Set-Flag 'restart'
    Add-Item $id $level $name 'warn' (T ('설치되어 있지만(' + $found + ') 지금 창의 PATH 에는 보이지 않습니다.') ('installed (' + $found + ') but not visible on the PATH of this session.')) `
        (T 'Claude 앱(VS Code 창)을 완전히 닫고 다시 연 뒤 /gatekit:setup 을 다시 실행하세요' 'close the Claude app (VS Code window) completely, open it again, then run /gatekit:setup again')
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
            can = (T 'PC 를 다시 시작한 뒤 /gatekit:setup 을 다시 실행하세요.' 'restart the PC, then run /gatekit:setup again.'); it = $false } }
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
        Set-Flag 'needs'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T 'winget 이 없어 자동 설치를 할 수 없습니다.' 'winget is missing, so it cannot install automatically.') `
            (T 'Microsoft Store에서 "앱 설치 관리자(App Installer)"를 설치·업데이트한 뒤 다시 실행하세요.' 'install or update "App Installer" from the Microsoft Store, then run again.')
        return $false
    }
    Say 'info' ('A-' + $name) $name (T ('winget ' + $verb + ' ' + $id + ' 실행 중...') ('running winget ' + $verb + ' ' + $id + ' ...'))
    $wargs = @($verb, '--id', $id, '-e', '--source', 'winget', '--disable-interactivity',
               '--accept-source-agreements', '--accept-package-agreements') + @($extra)
    $r = Invoke-Proc $winget[0].Source $wargs 900
    if ($r.TimedOut) {
        [void]$script:failedActions.Add($name)
        Set-Flag 'blocked'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T 'winget 이 제한 시간 안에 끝나지 않아 중단했습니다.' 'winget did not finish in time and was stopped.') `
            (T '네트워크를 확인하고 다시 시도하세요. 계속되면 IT 담당자에게 문의하세요.' 'check the network and try again. If it keeps happening, ask your IT contact.')
        return $false
    }
    if ($r.Code -eq 0) { return $true }
    $f = Get-WingetFailure $r.Code
    if ($f.cls -eq 'ok') { Say 'ok' ('A-' + $name) $name (T $f.ko $f.en); return $true }
    if ($f.cls -eq 'reboot') {
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
        'winget' { return 'winget upgrade --id astral-sh.uv -e' }
        'scoop' { return 'scoop update uv' }
        'pip' { return 'python -m pip install -U uv' }
    }
    return (T '설치한 방법에 맞춰 업데이트하세요' 'update it the same way you installed it')
}

# pwsh installed by the old MSI package lives here; a MSIX install/update may ask for UAC.
function Test-PwshMsiPath([string]$path) {
    return ($path -match '(?i)\\Program Files( \(x86\))?\\PowerShell\\')
}

function Invoke-Action([string]$name, [string]$mode) {
    if ($name -eq 'venv') { return }                     # handled by the .venv step below
    $found = Get-App $name
    $apps = $found.apps
    $present = ($found.where -ne 'none')
    if ($mode -eq 'install' -and $present) {
        Say 'ok' ('A-' + $name) $name (T '이미 설치되어 있어 건너뜁니다.' 'already installed, skipped.')
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
            if ($mode -eq 'install') { $verb = 'install' }
            if ($mode -eq 'update' -and (Test-PwshMsiPath $apps[0].Source)) {
                Say 'info' 'A-pwsh' 'pwsh' (T '기존 MSI 설치본이라 업데이트 중 관리자 확인 창(UAC)이 뜰 수 있습니다. 창이 뜨면 허용하거나 IT 담당자에게 문의하세요.' 'this is an older MSI install, so a Windows administrator prompt (UAC) may appear during the update. Allow it, or ask your IT contact.')
            }
            $ok = Invoke-WingetAction $verb 'Microsoft.PowerShell' 'pwsh' 'PowerShell 7 (winget Microsoft.PowerShell)' @('--installer-type', 'msix')
        }
        'uv' {
            if ($mode -eq 'install') {
                if ((Find-App 'winget' $script:sessionPath).Count -gt 0) {
                    $ok = Invoke-WingetAction 'install' 'astral-sh.uv' 'uv' 'uv (winget astral-sh.uv)' @() $true
                    if (-not $ok -and $script:lastWingetFail) {
                        $wf = $script:lastWingetFail
                        if ($wf.fail.cls -eq 'policy') {
                            Say 'info' 'A-uv' 'uv' (T 'winget 이 정책으로 막혀 있어 공식 설치 스크립트로 다시 시도합니다.' 'winget is blocked by policy, so the official installer script is tried instead.')
                            $ok = Invoke-OfficialScript 'https://astral.sh/uv/install.ps1' 'uv'
                            if (-not $ok) { Report-InstallFailure 'uv' $wf.what $wf.fail $wf.out }
                        } else {
                            Report-InstallFailure 'uv' $wf.what $wf.fail $wf.out
                        }
                    }
                } else {
                    $ok = Invoke-OfficialScript 'https://astral.sh/uv/install.ps1' 'uv'
                    if (-not $ok) { Report-ScriptFailure 'uv' }
                }
            } else {
                $m = Get-UvMethod $apps[0].Source
                if ($m.method -eq 'winget') { $ok = Invoke-WingetAction 'upgrade' 'astral-sh.uv' 'uv' 'uv (winget astral-sh.uv)' }
                elseif ($m.method -eq 'standalone' -and $m.receipt -eq 'broken') {
                    $ok = Invoke-OfficialScript 'https://astral.sh/uv/install.ps1' 'uv'
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
            if ($mode -eq 'install') {
                $ok = Invoke-OfficialScript 'https://claude.ai/install.ps1' 'claude'
                if (-not $ok) {
                    if ((Find-App 'winget' $script:sessionPath).Count -gt 0) {
                        $ok = Invoke-WingetAction 'install' 'Anthropic.ClaudeCode' 'claude' 'Claude Code (winget Anthropic.ClaudeCode)'
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
                @('winget install --id Git.Git -e --source winget', 'https://git-scm.com/download/win')
            return
        }
    }
    if ($ok) {
        $after = Get-App $name
        if ($after.where -eq 'none') {
            Set-Flag 'restart'
            [void]$script:failedActions.Add($name)
            Add-Item ('S9-' + $name) 'required' $name 'warn' (T '설치했지만 PATH 를 다시 읽어도 보이지 않습니다.' 'installed, but still not visible after re-reading PATH.') `
                (T 'Claude 앱(VS Code 창)을 완전히 닫고 다시 연 뒤 /gatekit:setup 을 다시 실행하세요.' 'close the Claude app (VS Code window) completely, open it again, then run /gatekit:setup again.')
        } else {
            [void]$script:done.Add($name + ' ' + (T $(if ($mode -eq 'install') { '설치' } else { '업데이트' }) $mode))
            Say 'ok' ('A-' + $name) $name ((T '완료' 'done') + ' (' + (T $(if ($mode -eq 'install') { '설치' } else { '업데이트' }) $mode) + ')')
        }
    }
}

# ---- start ---------------------------------------------------------------------
Say 'info' 'project' (T '프로젝트' 'project') $projectRoot

# Actions run first so the report below shows the state AFTER them.
foreach ($n in $installList) { Invoke-Action $n 'install' }
foreach ($n in $updateList) { Invoke-Action $n 'update' }

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
if ($projectRoot -match '(?i)OneDrive') {
    Add-Item 'S17' 'info' (T '경로' 'path') 'warn' (T 'OneDrive 폴더 안입니다(동기화가 .venv 를 방해할 수 있음)' 'the project is inside OneDrive (sync can disturb .venv)') (T 'OneDrive 밖(예: C:\dev)으로 옮기는 것을 권장합니다' 'moving it outside OneDrive (for example C:\dev) is recommended')
} elseif ($projectRoot.Length -gt 200) {
    Add-Item 'S17' 'info' (T '경로' 'path') 'warn' (T ('경로가 200자를 넘습니다(' + $projectRoot.Length + ')') ('the path is longer than 200 characters (' + $projectRoot.Length + ')')) (T '더 짧은 폴더로 옮기세요' 'move it to a shorter folder')
} else {
    Add-Item 'S17' 'info' (T '경로' 'path') 'ok' (T '경로 문제 없음' 'no path problem')
}

# S8 script mark ----------------------------------------------------------------
$mark = $null
try { $mark = Get-Item -LiteralPath $PSCommandPath -Stream Zone.Identifier -ErrorAction SilentlyContinue } catch { }
if ($mark) {
    Add-Item 'S8' 'required' (T '스크립트' 'scripts') 'info' (T '이 파일에 "인터넷에서 받음" 표시가 있습니다. 자동으로 해제하지 않습니다.' 'this file carries a "downloaded from the internet" mark. It is not unblocked automatically.') (T '항상 powershell -NoProfile -ExecutionPolicy Bypass -File 로 실행하세요' 'always run it with powershell -NoProfile -ExecutionPolicy Bypass -File')
}

# S3 winget ---------------------------------------------------------------------
$wingetFound = Get-App 'winget'
$wingetApp = $wingetFound.apps
if ($wingetFound.where -eq 'none') {
    Add-Item 'S3' 'recommended' 'winget' 'warn' (T '없음' 'not found') (T 'Microsoft Store 의 "앱 설치 관리자(App Installer)"를 설치·업데이트하세요(자동 설치 안 함). uv·claude 는 winget 없이도 설치할 수 있습니다' 'install or update "App Installer" from the Microsoft Store (not done automatically). uv and claude can be installed without winget')
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
    $ag = Invoke-Proc $wingetApp[0].Source @('search', '--id', 'astral-sh.uv', '-e', '--source', 'winget', '--disable-interactivity') 30
    if ($ag.TimedOut -or -not $ag.Started) {
        Add-Item 'S3-agreement' 'recommended' $agName 'unverified' (T '제한 시간 안에 확인하지 못했습니다' 'could not be checked in time')
    } elseif ($ag.Code -eq 0) {
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
$pwshFound = Get-App 'pwsh'
$pwshApps = $pwshFound.apps
if ($pwshFound.where -eq 'none') {
    Add-Item 'S2' 'recommended' 'pwsh' 'warn' (T 'PowerShell 7 이 없습니다(없어도 동작합니다)' 'PowerShell 7 not found (gatekit works without it)') (T '허락하면 설치합니다 (-Install pwsh)' 'installed if you allow it (-Install pwsh)')
} elseif ($pwshFound.where -eq 'registry') {
    Add-RestartItem 'S2' 'recommended' 'pwsh' $pwshApps[0].Source
} else {
    $found = @()
    $seenVersions = @{}
    $primaryStable = $false
    $primaryText = ''
    $primaryPath = ''
    $anyStable = $false
    $index = 0
    foreach ($a in ($pwshApps | Select-Object -First 3)) {
        $r = Invoke-Proc $a.Source @('-NoProfile', '-NoLogo', '-Command', '$PSVersionTable.PSVersion.ToString()') 20
        $vt = ($r.Out.Trim() -split "`r?`n")[0]
        $stable = $false
        if ($vt -match '^(\d+)\.(\d+)\.(\d+)(-\S+)?$') {
            $ver = [version]($Matches[1] + '.' + $Matches[2] + '.' + $Matches[3])
            if (-not $Matches[4] -and $ver -ge [version]'7.6.0') { $stable = $true }
        } else { $vt = '?' }
        if ($stable) { $anyStable = $true }
        if ($index -eq 0) { $primaryStable = $stable; $primaryText = $vt; $primaryPath = $a.Source }
        # The same version behind an alias path is one install: show it once.
        if ($vt -eq '?' -or -not $seenVersions.ContainsKey($vt)) {
            $found += ($a.Source + ' = ' + $vt)
            $seenVersions[$vt] = $true
        }
        $index++
    }
    $where = $found -join '; '
    $uacHint = @()
    if (Test-PwshMsiPath $primaryPath) {
        $uacHint = @(T '기존 MSI 설치본이라 업데이트할 때 관리자 확인 창(UAC)이 뜰 수 있습니다.' 'this is an older MSI install, so the update may show a Windows administrator prompt (UAC).')
    }
    if ($primaryText -eq '?') {
        Add-Item 'S2' 'recommended' 'pwsh' 'unverified' ((T '버전을 읽지 못했습니다: ' 'could not read the version: ') + $where)
    } elseif ($primaryStable) {
        Add-Item 'S2' 'recommended' 'pwsh' 'ok' ((T '안정판 ' 'stable ') + $primaryText + ' (' + $where + ')')
    } elseif ($primaryText -match '-') {
        $act = T '안정판 7.6 권장, 허락하면 업데이트합니다 (-Update pwsh)' 'stable 7.6 recommended, updated if you allow it (-Update pwsh)'
        if ($anyStable) { $act = T '안정판 7.6 이 다른 경로에 있습니다. PATH 순서를 확인하세요' 'a stable 7.6 exists at another path. Check the PATH order' }
        Add-Item 'S2' 'recommended' 'pwsh' 'warn' ((T '미리보기(preview) 버전이 먼저 잡힙니다: ' 'a preview build is found first: ') + $where) $act $uacHint
    } else {
        Add-Item 'S2' 'recommended' 'pwsh' 'warn' ((T '7.6 안정판보다 낮습니다: ' 'older than stable 7.6: ') + $where) (T '허락하면 업데이트합니다 (-Update pwsh)' 'updated if you allow it (-Update pwsh)') $uacHint
    }
}

# S4 uv -------------------------------------------------------------------------
$uvFound = Get-App 'uv'
$uvApps = $uvFound.apps
$uvOk = $false
$uvPath = ''
if ($uvFound.where -eq 'none') {
    Set-Flag 'needs'
    Add-Item 'S4' 'required' 'uv' 'fail' (T 'uv 를 찾을 수 없습니다. gatekit 은 uv 가 필요합니다(Python 은 uv 가 알아서 받습니다).' 'uv not found. gatekit needs uv (it fetches Python by itself).') `
        (T '허락하면 설치합니다 (-Install uv). 직접 하려면 아래 중 하나를 실행하세요' 'installed if you allow it (-Install uv). To do it yourself run ONE of these') `
        @('winget install --id=astral-sh.uv -e', 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"', (T '설치 후 새 터미널(또는 Claude 창 재시작)에서 다시 실행하세요' 'after installing, run this again from a new terminal (or restart the Claude window)'))
} elseif ($uvFound.where -eq 'registry') {
    Add-RestartItem 'S4' 'required' 'uv' $uvApps[0].Source
} else {
    $uvPath = $uvApps[0].Source
    $uvProbe = Invoke-Proc $uvPath @('--version') 20
    $uvVer = Get-VersionFrom $uvProbe.Out
    $m = Get-UvMethod $uvPath
    if (-not $uvVer) {
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
# home is gone, or it does not start).
function Get-PythonVersion {
    $pv = Invoke-Proc $venvPy @('-c', "import sys;print('%d.%d.%d' % sys.version_info[:3])") 20
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
    if (-not $v) { return @{ state = 'broken'; reason = (T 'python.exe 가 실행되지 않습니다' 'python.exe does not start'); version = '' } }
    $pv = Get-VersionFrom $v
    if ($pv -and $pv -lt $pythonMinimum) {
        return @{ state = 'old'; reason = (T ('python ' + $v + ' 은(는) 필요한 ' + $pythonMinimum.Major + '.' + $pythonMinimum.Minor + ' 보다 낮습니다') ('python ' + $v + ' is older than the required ' + $pythonMinimum.Major + '.' + $pythonMinimum.Minor)); version = $v }
    }
    return @{ state = 'ok'; reason = ''; version = $v }
}

$venvReady = $false
$wantVenv = ($installList -contains 'venv')
if (-not $uvOk) {
    Add-Item 'S5' 'required' '.venv' 'unverified' (T 'uv 가 준비되지 않아 확인하지 못했습니다' 'not checked because uv is not ready')
} else {
    $health = Test-VenvHealth
    $venvRel = '.claude/gatekit/.venv'
    if ($health.state -eq 'ok') {
        $msg = T ('python ' + $health.version + ' 준비됨') ('python ' + $health.version + ' ready')
        if ($wantVenv) { $msg = (T '이미 준비되어 있어 건너뜁니다: ' 'already ready, skipped: ') + $msg }
        Add-Item 'S5' 'required' '.venv' 'ok' $msg
        $venvReady = $true
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

# S12 config and settings --------------------------------------------------------
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
    Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T '없습니다: 훅이 등록되지 않았습니다' 'missing: hooks are not registered') (T '저장소에서 복원하세요(git checkout .claude/settings.json)' 'restore it from the repository (git checkout .claude/settings.json)')
} else {
    $settings = $null
    try { $settings = (Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
    if (-not $settings -or -not $settings.hooks) {
        Set-Flag 'fail'
        Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T 'JSON 이 깨졌거나 hooks 가 없습니다' 'invalid JSON or no hooks') (T '저장소에서 복원하세요' 'restore it from the repository')
    } else {
        $rawSettings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8
        $hasStart = ($settings.hooks.SessionStart -and $rawSettings -match 'session-check\.ps1')
        $hasGate = ($rawSettings -match 'bin/gatekit\.py')
        $noFlags = @(Get-HooksMissingPsFlags $settings)
        if (-not ($hasStart -and $hasGate)) {
            Set-Flag 'fail'
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T 'gatekit 훅 등록이 빠져 있습니다' 'gatekit hook registrations are missing') (T '저장소에서 복원하세요' 'restore it from the repository')
        } elseif ($noFlags.Count -gt 0) {
            Set-Flag 'fail'
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T ('PowerShell 훅에 -NoProfile -ExecutionPolicy Bypass 가 없습니다: ' + ($noFlags -join ', ')) ('PowerShell hook without -NoProfile -ExecutionPolicy Bypass: ' + ($noFlags -join ', '))) (T '저장소에서 복원하세요' 'restore it from the repository')
        } else {
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'ok' (T '훅 등록 확인(SessionStart, 게이트, -NoProfile -ExecutionPolicy Bypass)' 'hooks registered (SessionStart, gates, -NoProfile -ExecutionPolicy Bypass)')
        }
    }
}

# S6 claude ---------------------------------------------------------------------
$claudeFound = Get-App 'claude'
$claudeApps = $claudeFound.apps
if ($claudeFound.where -eq 'none') {
    Set-Flag 'needs'
    Add-Item 'S6' 'required' 'claude CLI' 'fail' (T 'PATH 에 claude 가 없습니다(데스크톱 앱만으로는 CLI 가 없습니다). 워커를 실행할 수 없습니다.' 'claude is not on PATH (the desktop app alone does not include the CLI). Workers cannot start.') (T '허락하면 설치합니다 (-Install claude)' 'installed if you allow it (-Install claude)')
} elseif ($claudeFound.where -eq 'registry') {
    Add-RestartItem 'S6' 'required' 'claude CLI' $claudeApps[0].Source
} else {
    $cp = Invoke-Proc $claudeApps[0].Source @('--version') 30
    $cv = Get-VersionFrom $cp.Out
    if (-not $cv) {
        Add-Item 'S6' 'required' 'claude CLI' 'unverified' ((T 'PATH 에 있으나 버전을 읽지 못했습니다: ' 'on PATH but the version could not be read: ') + $claudeApps[0].Source)
    } elseif ($cv -lt $claudeRecommended) {
        Add-Item 'S6' 'required' 'claude CLI' 'warn' ('claude ' + $cv + ' < ' + $claudeRecommended + (T ' (권장)' ' (recommended)')) (T '허락하면 업데이트합니다 (-Update claude)' 'updated if you allow it (-Update claude)')
    } else {
        Add-Item 'S6' 'required' 'claude CLI' 'ok' ('claude ' + $cv)
    }
}

# S7 git ------------------------------------------------------------------------
$gitFound = Get-App 'git'
$gitApps = $gitFound.apps
if ($gitFound.where -eq 'none') {
    Add-Item 'S7' 'info' 'git' 'info' (T 'Git for Windows 가 없습니다. Claude Code 는 PowerShell 도구로 동작합니다.' 'Git for Windows not found. Claude Code works through its PowerShell tool.') (T '필요하면 직접 설치하세요(관리자 권한이 필요할 수 있음)' 'install it yourself if you want it (it may need administrator rights)')
} elseif ($gitFound.where -eq 'registry') {
    Add-RestartItem 'S7' 'info' 'git' $gitApps[0].Source
} else {
    $gp = Invoke-Proc $gitApps[0].Source @('--version') 15
    Add-Item 'S7' 'info' 'git' 'info' $gp.Out.Trim()
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
if (-not $venvReady) {
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
