# gatekit setup (Windows PowerShell 5.1 compatible).
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 [switches]
#
# Switches
#   (none)            check only: nothing is installed or updated.
#   -Install <list>   install the listed programs. Allowed names: pwsh, uv, claude, git.
#   -Update <list>    update the listed programs (same names).
#   -Json             print ONE JSON object {exit_code, items:[{id,level,name,verdict,detail,action,hints}]}.
#   -Lang ko|en       print one language only (default: both, "English / Korean").
# Any other name in -Install / -Update is refused with exit code 1.
# -Install / -Update are the user's permission: the chat asked first. Only calls
# made for a listed name pass --accept-source-agreements / --accept-package-agreements.
# Only user-scope installs run automatically. Anything that needs administrator
# rights (git) is never run here; the script prints what to do instead.
#
# Every line: [ok|warn|fail|unverified|info] name: result - next action
# Nothing here asks a question (no Read-Host); winget always gets --disable-interactivity.
#
# Exit codes (when several problems mix, the FIRST matching row wins):
#   1  something failed that a permission cannot fix (bad switch, .venv or config
#      could not be built, doctor failed, an install failed for an unknown reason)
#   4  blocked by policy or network (winget policy block, no network, TLS)
#   3  a program was installed but is still not visible after re-reading PATH:
#      close the Claude app (VS Code window) completely and open it again
#   2  the user must allow or do something (a required program is missing or too
#      old, or a listed program needs administrator rights)
#   0  ready
# Environment: GATEKIT_SETUP_KEEP_PATH=1 keeps the inherited PATH (no merge from the registry).

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
$allowed = @('pwsh', 'uv', 'claude', 'git')
$uvMinimum = [version]'0.4.27'
$claudeRecommended = [version]'2.1.277'

$script:items = New-Object System.Collections.ArrayList
$script:flags = @{ fail = $false; blocked = $false; restart = $false; needs = $false }
$script:done = New-Object System.Collections.ArrayList
$script:failedActions = New-Object System.Collections.ArrayList
$script:langMode = 'both'
$script:lastScriptFail = $null
$script:showSummary = $true

# ---- output helpers -----------------------------------------------------------
function T([string]$ko, [string]$en) {
    if ($script:langMode -eq 'ko') { return $ko }
    if ($script:langMode -eq 'en') { return $en }
    return ($en + ' / ' + $ko)
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

function Set-Flag([string]$name) { $script:flags[$name] = $true }

function Get-ExitCode {
    if ($script:flags.fail) { return 1 }
    if ($script:flags.blocked) { return 4 }
    if ($script:flags.restart) { return 3 }
    if ($script:flags.needs) { return 2 }
    return 0
}

function Complete-Run {
    $code = Get-ExitCode
    if ($script:showSummary -and ($code -ne 0 -or $script:done.Count -gt 0 -or $script:failedActions.Count -gt 0)) {
        $remaining = @()
        foreach ($i in $script:items) {
            if ($i.level -eq 'required' -and $i.verdict -eq 'fail') { $remaining += $i.id }
        }
        $d = $script:done -join ', '
        $f = $script:failedActions -join ', '
        $r = $remaining -join ', '
        $detail = T ('성공: ' + $d + '; 실패: ' + $f + '; 남은 것: ' + $r) ('done: ' + $d + '; failed: ' + $f + '; remaining: ' + $r)
        $verdict = 'ok'
        if ($code -ne 0) { $verdict = 'warn' }
        Add-Item 'S11' 'required' 'summary' $verdict $detail
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
        Write-Output (ConvertTo-Json -InputObject $obj -Depth 6)
    } else {
        Write-Host ('[info] exit code ' + $code + ': ' + $meaning[$code])
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
        Add-Item 'args' 'required' '-Lang' 'fail' ('unknown language ' + $Lang) 'use -Lang ko or -Lang en'
    }
}
$installList = Split-List $Install
$updateList = Split-List $Update
foreach ($n in (@($installList) + @($updateList))) {
    if ($allowed -notcontains $n) {
        $argsBad = $true
        Add-Item 'args' 'required' 'switch' 'fail' ('refused: "' + $n + '" is not in the allowed list') ('allowed: ' + ($allowed -join ', '))
    }
}
if ($argsBad) { $script:showSummary = $false; Set-Flag 'fail'; Complete-Run }

# ---- process and PATH helpers ------------------------------------------------
function Quote-Arg([string]$a) {
    if ($a -eq '') { return '""' }
    if ($a -match '[\s"]') { return '"' + ($a -replace '"', '\"') + '"' }
    return $a
}

# Runs a program without a shell: stdin closed (nothing can prompt), stdout+stderr
# captured, killed after $timeoutSec. Returns Started / TimedOut / Code / Out.
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
            try { $p.Kill() } catch { }
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

function Find-App([string]$name) {
    return @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)
}

function Get-VersionFrom([string]$text) {
    if ($text -match '(\d+)\.(\d+)\.(\d+)') { return [version]($Matches[1] + '.' + $Matches[2] + '.' + $Matches[3]) }
    return $null
}

# Re-read Machine + User PATH and merge into this process (installers write the
# registry, not the running process).
function Update-SessionPath {
    if ($env:GATEKIT_SETUP_KEEP_PATH -eq '1') { return }
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $seen = @{}
    $merged = @()
    foreach ($src in @($machine, $user, $env:Path)) {
        foreach ($e in ("$src" -split ';')) {
            $t = [Environment]::ExpandEnvironmentVariables($e.Trim())
            if ($t) {
                $key = $t.ToLower().TrimEnd('\')
                if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; $merged += $t }
            }
        }
    }
    $env:Path = ($merged -join ';')
}

$winPs = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$tlsPrefix = '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; '

# ---- winget failure table (S16) ----------------------------------------------
# key = exit code as 8 hex digits. class: ok / policy / network / agreement / unknown
function Get-WingetFailure([int]$code) {
    $hex = '{0:X8}' -f $code
    switch ($hex) {
        '8A15002B' { return @{ cls = 'ok'; hex = $hex; ko = '업데이트할 것이 없습니다(이미 최신).'; en = 'nothing to update (already current).'; can = ''; it = $false } }
        '8A150061' { return @{ cls = 'ok'; hex = $hex; ko = '이미 설치되어 있습니다.'; en = 'already installed.'; can = ''; it = $false } }
        '8A15003A' { return @{ cls = 'policy'; hex = $hex
            ko = '회사·학교 정책이 winget 사용을 막고 있습니다.'; en = 'a company or school policy blocks winget.'
            can = (T 'uv·claude는 winget 없이 공식 설치 스크립트로 설치할 수 있습니다(다시 허락해 주세요). PowerShell 7·Git은 IT 담당자가 필요합니다.' 'uv and claude can be installed without winget through their official installer script (ask again). PowerShell 7 and Git need your IT contact.'); it = $true } }
        '8A150107' { return @{ cls = 'network'; hex = $hex
            ko = '설치 서버에 연결하지 못했습니다(네트워크).'; en = 'could not reach the install source (network).'
            can = (T '인터넷·VPN·프록시 연결을 확인하고 잠시 뒤 다시 시도하세요.' 'check the internet, VPN and proxy, then try again in a moment.'); it = $true } }
        '80072EFD' { return @{ cls = 'network'; hex = $hex
            ko = '보안 연결(TLS)이나 서버 연결에 실패했습니다.'; en = 'the secure connection (TLS) or the server connection failed.'
            can = (T '회사 프록시·방화벽·보안 프로그램이 막고 있을 수 있습니다. 집 네트워크/핫스팟에서 다시 시도해 보세요.' 'a company proxy, firewall or security tool may be blocking it. Try again from a home network or a hotspot.'); it = $true } }
        '8A150046' { return @{ cls = 'agreement'; hex = $hex
            ko = 'winget 원본 약관에 아직 동의하지 않았습니다.'; en = 'the winget source agreements have not been accepted yet.'
            can = (T '터미널에서 winget search git 을 한 번 실행해 약관에 직접 동의하거나, 설치를 다시 허락해 주세요.' 'run winget search git once in a terminal and accept the agreements yourself, or allow the install again.'); it = $false } }
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

function Test-NetworkText([string]$text) {
    return ($text -match '(?i)error sending request|dns error|timed out|timeout|could not resolve|unable to connect|certificate|tls|ssl|proxy|connection (refused|reset)|no such host|name or service')
}

# ---- actions (only for names the user allowed) -------------------------------
function Invoke-WingetAction([string]$verb, [string]$id, [string]$name, [string]$what) {
    $winget = Find-App 'winget'
    if ($winget.Count -eq 0) {
        [void]$script:failedActions.Add($name)
        Set-Flag 'needs'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T 'winget 이 없어 자동 설치를 할 수 없습니다.' 'winget is missing, so it cannot install automatically.') `
            (T 'Microsoft Store에서 "앱 설치 관리자(App Installer)"를 설치·업데이트한 뒤 다시 실행하세요.' 'install or update "App Installer" from the Microsoft Store, then run again.')
        return $false
    }
    Out-Human ('[info] ' + $name + ': winget ' + $verb + ' ' + $id + ' ...')
    $wargs = @($verb, '--id', $id, '-e', '--source', 'winget', '--disable-interactivity',
               '--accept-source-agreements', '--accept-package-agreements')
    $r = Invoke-Proc $winget[0].Source $wargs 900
    if ($r.TimedOut) {
        [void]$script:failedActions.Add($name)
        Set-Flag 'blocked'
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '설치' 'install')) 'fail' (T 'winget 이 제한 시간 안에 끝나지 않았습니다.' 'winget did not finish in time.') `
            (T '네트워크를 확인하고 다시 시도하세요. 계속되면 IT 담당자에게 문의하세요.' 'check the network and try again. If it keeps happening, ask your IT contact.')
        return $false
    }
    if ($r.Code -eq 0) { return $true }
    $f = Get-WingetFailure $r.Code
    if ($f.cls -eq 'ok') { Out-Human ('[info] ' + $name + ': ' + (T $f.ko $f.en)); return $true }
    Report-InstallFailure $name $what $f $r.Out
    return $false
}

# Runs an official install.ps1. On failure returns $false and leaves the failure
# description in $script:lastScriptFail; the CALLER reports it (Report-InstallFailure)
# so a fallback (winget) can be tried first.
function Invoke-OfficialScript([string]$url, [string]$name) {
    Out-Human ('[info] ' + $name + ': ' + (T '공식 설치 스크립트 실행 ' 'running the official installer ') + $url)
    $cmd = $tlsPrefix + 'irm ' + $url + ' | iex'
    $r = Invoke-Proc $winPs @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $cmd) 600
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

function Invoke-Action([string]$name, [string]$mode) {
    $apps = Find-App $name
    $present = ($apps.Count -gt 0)
    if ($mode -eq 'install' -and $present) {
        Out-Human ('[ok] ' + $name + ': ' + (T '이미 설치되어 있어 건너뜁니다.' 'already installed, skipped.'))
        return
    }
    if ($mode -eq 'update' -and -not $present) {
        Add-Item ('S16-' + $name) 'required' ($name + ' ' + (T '업데이트' 'update')) 'warn' (T '설치되어 있지 않아 업데이트할 수 없습니다.' 'not installed, so nothing to update.') (T '-Install 로 먼저 설치하세요.' 'install it first (-Install).')
        Set-Flag 'needs'
        return
    }
    $ok = $false
    switch ($name) {
        'pwsh' { $ok = Invoke-WingetAction $(if ($mode -eq 'install') { 'install' } else { 'upgrade' }) 'Microsoft.PowerShell' 'pwsh' 'PowerShell 7 (winget Microsoft.PowerShell)' }
        'uv' {
            if ($mode -eq 'install') {
                if ((Find-App 'winget').Count -gt 0) { $ok = Invoke-WingetAction 'install' 'astral-sh.uv' 'uv' 'uv (winget astral-sh.uv)' }
                else {
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
                    Out-Human '[info] uv: uv self update ...'
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
                    Add-Item 'S16-uv' 'required' 'uv update' 'warn' (T '이 설치 방법은 자동 업데이트하지 않습니다.' 'this install method is not updated automatically.') (Get-UvUpdateAdvice $m.method)
                    return
                }
            }
        }
        'claude' {
            if ($mode -eq 'install') {
                $ok = Invoke-OfficialScript 'https://claude.ai/install.ps1' 'claude'
                if (-not $ok) {
                    if ((Find-App 'winget').Count -gt 0) {
                        $ok = Invoke-WingetAction 'install' 'Anthropic.ClaudeCode' 'claude' 'Claude Code (winget Anthropic.ClaudeCode)'
                    } else { Report-ScriptFailure 'claude' }
                }
            } else {
                Out-Human '[info] claude: claude update ...'
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
        Update-SessionPath
        if ((Find-App $name).Count -gt 0) {
            [void]$script:done.Add($name + ' ' + $mode)
            Out-Human ('[ok] ' + $name + ': ' + (T '완료' 'done') + ' (' + $mode + ')')
        } else {
            Set-Flag 'restart'
            [void]$script:failedActions.Add($name)
            Add-Item ('S9-' + $name) 'required' $name 'warn' (T '설치했지만 PATH 를 다시 읽어도 보이지 않습니다.' 'installed, but still not visible after re-reading PATH.') `
                (T 'Claude 앱(VS Code 창)을 완전히 닫고 다시 연 뒤 /gatekit:setup 을 다시 실행하세요.' 'close the Claude app (VS Code window) completely, open it again, then run /gatekit:setup again.')
        }
    }
}

# ---- start ---------------------------------------------------------------------
Update-SessionPath
Out-Human ('[info] project: ' + $projectRoot)

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
    Add-Item 'S17' 'info' 'path' 'warn' (T 'OneDrive 폴더 안입니다(동기화가 .venv 를 방해할 수 있음)' 'the project is inside OneDrive (sync can disturb .venv)') (T 'OneDrive 밖(예: C:\dev)으로 옮기는 것을 권장합니다' 'moving it outside OneDrive (for example C:\dev) is recommended')
} elseif ($projectRoot.Length -gt 200) {
    Add-Item 'S17' 'info' 'path' 'warn' (T ('경로가 200자를 넘습니다(' + $projectRoot.Length + ')') ('the path is longer than 200 characters (' + $projectRoot.Length + ')')) (T '더 짧은 폴더로 옮기세요' 'move it to a shorter folder')
} else {
    Add-Item 'S17' 'info' 'path' 'ok' (T '경로 문제 없음' 'no path problem')
}

# S8 script mark ----------------------------------------------------------------
$mark = $null
try { $mark = Get-Item -LiteralPath $PSCommandPath -Stream Zone.Identifier -ErrorAction SilentlyContinue } catch { }
if ($mark) {
    Add-Item 'S8' 'required' 'scripts' 'info' (T '이 파일에 "인터넷에서 받음" 표시가 있습니다. 자동으로 해제하지 않습니다.' 'this file carries a "downloaded from the internet" mark. It is not unblocked automatically.') (T '항상 powershell -NoProfile -ExecutionPolicy Bypass -File 로 실행하세요' 'always run it with powershell -NoProfile -ExecutionPolicy Bypass -File')
}

# S3 winget ---------------------------------------------------------------------
$wingetApp = Find-App 'winget'
if ($wingetApp.Count -eq 0) {
    Add-Item 'S3' 'recommended' 'winget' 'warn' (T '없음' 'not found') (T 'Microsoft Store 의 "앱 설치 관리자(App Installer)"를 설치·업데이트하세요(자동 설치 안 함). uv·claude 는 winget 없이도 설치할 수 있습니다' 'install or update "App Installer" from the Microsoft Store (not done automatically). uv and claude can be installed without winget')
} else {
    $wv = Invoke-Proc $wingetApp[0].Source @('--version') 15
    $wvText = ($wv.Out.Trim() -split "`r?`n")[0]
    if ($wv.Code -eq 0 -and (Get-VersionFrom $wvText)) {
        Add-Item 'S3' 'recommended' 'winget' 'ok' ('present, ' + $wvText)
    } else {
        Add-Item 'S3' 'recommended' 'winget' 'unverified' (T 'winget 은 있지만 버전을 읽지 못했습니다' 'winget is there but its version could not be read')
    }
    $ag = Invoke-Proc $wingetApp[0].Source @('search', '--id', 'astral-sh.uv', '-e', '--source', 'winget', '--disable-interactivity') 30
    if ($ag.TimedOut -or -not $ag.Started) {
        Add-Item 'S3-agreement' 'recommended' 'winget source agreements' 'unverified' (T '제한 시간 안에 확인하지 못했습니다' 'could not be checked in time')
    } elseif ($ag.Code -eq 0) {
        Add-Item 'S3-agreement' 'recommended' 'winget source agreements' 'ok' (T '원본 조회 성공(약관 동의됨)' 'source lookup worked (agreements accepted)')
    } else {
        $agFail = Get-WingetFailure $ag.Code
        if ($agFail.cls -eq 'agreement') {
            Add-Item 'S3-agreement' 'recommended' 'winget source agreements' 'warn' (T $agFail.ko $agFail.en) (T '설치를 허락하면 그 항목에 한해 동의를 포함해 실행합니다' 'if you allow an install, agreement is included for that item only')
        } else {
            Add-Item 'S3-agreement' 'recommended' 'winget source agreements' 'unverified' ((T '확인하지 못했습니다' 'could not be checked') + ' (0x' + $agFail.hex + ')')
        }
    }
}

# S2 pwsh -----------------------------------------------------------------------
$pwshApps = Find-App 'pwsh'
if ($pwshApps.Count -eq 0) {
    Add-Item 'S2' 'recommended' 'pwsh' 'warn' (T 'PowerShell 7 이 없습니다(없어도 동작합니다)' 'PowerShell 7 not found (gatekit works without it)') (T '허락하면 설치합니다 (-Install pwsh)' 'installed if you allow it (-Install pwsh)')
} else {
    $found = @()
    $primaryStable = $false
    $primaryText = ''
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
        if ($index -eq 0) { $primaryStable = $stable; $primaryText = $vt }
        $found += ($a.Source + ' = ' + $vt)
        $index++
    }
    $where = $found -join '; '
    if ($primaryText -eq '?') {
        Add-Item 'S2' 'recommended' 'pwsh' 'unverified' ((T '버전을 읽지 못했습니다: ' 'could not read the version: ') + $where)
    } elseif ($primaryStable) {
        Add-Item 'S2' 'recommended' 'pwsh' 'ok' ((T '안정판 ' 'stable ') + $primaryText + ' (' + $where + ')')
    } elseif ($primaryText -match '-') {
        $act = T '안정판 7.6 권장 (-Install pwsh)' 'stable 7.6 recommended (-Install pwsh)'
        if ($anyStable) { $act = T '안정판 7.6 이 다른 경로에 있습니다. PATH 순서를 확인하세요' 'a stable 7.6 exists at another path. Check the PATH order' }
        Add-Item 'S2' 'recommended' 'pwsh' 'warn' ((T '미리보기(preview) 버전이 먼저 잡힙니다: ' 'a preview build is found first: ') + $where) $act
    } else {
        Add-Item 'S2' 'recommended' 'pwsh' 'warn' ((T '7.6 안정판보다 낮습니다: ' 'older than stable 7.6: ') + $where) (T '허락하면 업데이트합니다 (-Update pwsh)' 'updated if you allow it (-Update pwsh)')
    }
    if ($found.Count -gt 1) {
        Add-Item 'S2-paths' 'info' 'pwsh paths' 'info' ((T 'PATH 에 pwsh 가 여러 개: ' 'several pwsh on PATH: ') + $where)
    }
}

# S4 uv -------------------------------------------------------------------------
$uvApps = Find-App 'uv'
$uvOk = $false
if ($uvApps.Count -eq 0) {
    Set-Flag 'needs'
    Add-Item 'S4' 'required' 'uv' 'fail' (T 'uv 를 찾을 수 없습니다. gatekit 은 uv 가 필요합니다(Python 은 uv 가 알아서 받습니다).' 'uv not found. gatekit needs uv (it fetches Python by itself).') `
        (T '허락하면 설치합니다 (-Install uv). 직접 하려면 아래 중 하나를 실행하세요' 'installed if you allow it (-Install uv). To do it yourself run ONE of these') `
        @('winget install --id=astral-sh.uv -e', 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"', (T '설치 후 새 터미널(또는 Claude 창 재시작)에서 다시 실행하세요' 'after installing, run this again from a new terminal (or restart the Claude window)'))
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
$venvReady = $false
if (-not $uvOk) {
    Add-Item 'S5' 'required' '.venv' 'unverified' (T 'uv 가 준비되지 않아 확인하지 못했습니다' 'not checked because uv is not ready')
} else {
    $cfgFile = Join-Path $venvDir 'pyvenv.cfg'
    $rebuilt = $false
    if (Test-Path -LiteralPath $cfgFile) {
        $home_ = $null
        foreach ($cl in (Get-Content -LiteralPath $cfgFile -ErrorAction SilentlyContinue)) {
            if ($cl -match '^\s*home\s*=\s*(.+?)\s*$') { $home_ = $Matches[1] }
        }
        if ($home_ -and -not (Test-Path -LiteralPath $home_)) {
            Out-Human ('[warn] .venv: ' + (T ('pyvenv.cfg 의 Python 경로가 없습니다(' + $home_ + '). 깨진 .venv 를 삭제하고 다시 만듭니다: ') ('the Python path in pyvenv.cfg is gone (' + $home_ + '). Deleting the broken .venv and recreating it: ')) + $venvDir)
            if ((Split-Path -Leaf $venvDir) -eq '.venv') { Remove-Item -LiteralPath $venvDir -Recurse -Force -ErrorAction SilentlyContinue }
            $rebuilt = $true
        }
    }
    if ($rebuilt -or -not (Test-Path -LiteralPath $venvPy)) {
        Out-Human ('[info] .venv: ' + (T 'uv sync --frozen 실행. 처음이면 Python 과 패키지를 내려받으므로 네트워크가 필요하고 몇 분 걸릴 수 있습니다.' 'running uv sync --frozen. On a first run it downloads Python and packages, so it needs the network and can take a few minutes.'))
    }
    $syncOut = @(& uv sync --project $kit --frozen 2>&1 | ForEach-Object { "$_" })
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $venvPy)) {
        $pv = Invoke-Proc $venvPy @('-c', "import sys;print('%d.%d.%d' % sys.version_info[:3])") 20
        Add-Item 'S5' 'required' '.venv' 'ok' ('uv sync --frozen: python ' + $pv.Out.Trim() + (T ' 준비됨' ' ready'))
        $venvReady = $true
    } else {
        $text = ($syncOut -join "`n")
        $hints = @($syncOut | Select-Object -Last 6 | ForEach-Object { '  ' + $_ })
        if (Test-NetworkText $text) {
            Set-Flag 'blocked'
            $hints += (T '프록시/회사 인증서 환경이면 UV_SYSTEM_CERTS=1, SSL_CERT_FILE, HTTPS_PROXY, UV_PYTHON_INSTALL_MIRROR 를 확인하세요. 계속되면 IT 담당자에게 문의하세요.' 'behind a proxy or a company certificate, check UV_SYSTEM_CERTS=1, SSL_CERT_FILE, HTTPS_PROXY and UV_PYTHON_INSTALL_MIRROR. If it keeps failing, ask your IT contact.')
            Add-Item 'S5' 'required' '.venv' 'fail' (T 'uv sync --frozen 실패: 네트워크로 보입니다' 'uv sync --frozen failed: looks like a network problem') (T '온라인에서 다시 시도하세요' 'try again when online') $hints
        } else {
            Set-Flag 'fail'
            Add-Item 'S5' 'required' '.venv' 'fail' (T 'uv sync --frozen 실패' 'uv sync --frozen failed') '' $hints
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
    $out = @(& $venvPy $launcher workers set-default claude --root $projectRoot 2>&1 | ForEach-Object { "$_" })
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $cfg)) {
        Add-Item 'S12-config' 'required' '.gatekit/config.json' 'ok' (T '생성함(기본 워커: claude)' 'created (default worker: claude)')
    } else {
        Set-Flag 'fail'
        Add-Item 'S12-config' 'required' '.gatekit/config.json' 'fail' (T '생성 실패' 'could not be created') '' @($out | Select-Object -Last 5 | ForEach-Object { '  ' + $_ })
    }
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
        if ($hasStart -and $hasGate) {
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'ok' (T '훅 등록 확인(SessionStart, 게이트)' 'hooks registered (SessionStart, gates)')
        } else {
            Set-Flag 'fail'
            Add-Item 'S12-settings' 'required' '.claude/settings.json' 'fail' (T 'gatekit 훅 등록이 빠져 있습니다' 'gatekit hook registrations are missing') (T '저장소에서 복원하세요' 'restore it from the repository')
        }
    }
}

# S6 claude ---------------------------------------------------------------------
$claudeApps = Find-App 'claude'
if ($claudeApps.Count -eq 0) {
    Set-Flag 'needs'
    Add-Item 'S6' 'required' 'claude CLI' 'fail' (T 'PATH 에 claude 가 없습니다(데스크톱 앱만으로는 CLI 가 없습니다). 워커를 실행할 수 없습니다.' 'claude is not on PATH (the desktop app alone does not include the CLI). Workers cannot start.') (T '허락하면 설치합니다 (-Install claude)' 'installed if you allow it (-Install claude)')
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
$gitApps = Find-App 'git'
if ($gitApps.Count -eq 0) {
    Add-Item 'S7' 'info' 'git' 'info' (T 'Git for Windows 가 없습니다. Claude Code 는 PowerShell 도구로 동작합니다.' 'Git for Windows not found. Claude Code works through its PowerShell tool.') (T '필요하면 직접 설치하세요(관리자 권한이 필요할 수 있음)' 'install it yourself if you want it (it may need administrator rights)')
} else {
    $gp = Invoke-Proc $gitApps[0].Source @('--version') 15
    Add-Item 'S7' 'info' 'git' 'info' ($gp.Out.Trim())
}

# S18 node (only with a package.json) ---------------------------------------------
if (Test-Path -LiteralPath (Join-Path $projectRoot 'package.json')) {
    $nodeText = T '없음' 'missing'
    $npmText = T '없음' 'missing'
    $nodeApp = Find-App 'node'
    $npmApp = Find-App 'npm'
    if ($nodeApp.Count -gt 0) { $nodeText = (Invoke-Proc $nodeApp[0].Source @('--version') 15).Out.Trim() }
    if ($npmApp.Count -gt 0) { $npmText = (Invoke-Proc $npmApp[0].Source @('--version') 20).Out.Trim() }
    Add-Item 'S18' 'info' 'node/npm' 'info' ('node ' + $nodeText + ', npm ' + $npmText + ' (' + (T 'gatekit 자체는 Node 가 필요 없고, 사용자 프로젝트 게이트용입니다' 'gatekit itself does not need Node; it is for your project gates') + ')')
}

# S23 python stub ---------------------------------------------------------------
$pyApp = Find-App 'python'
if ($pyApp.Count -gt 0 -and $pyApp[0].Source -match '(?i)\\WindowsApps\\') {
    Add-Item 'S23' 'info' 'python' 'info' (T 'WindowsApps 의 python 은 스토어 안내용 스텁일 수 있어 사용하지 않습니다. gatekit 은 uv 가 관리하는 .venv 의 Python 만 씁니다.' 'the python in WindowsApps may be a Store stub and is not used. gatekit only uses the uv-managed .venv Python.')
}

# S15 doctor --------------------------------------------------------------------
if (-not $venvReady) {
    Add-Item 'S15' 'required' 'doctor' 'unverified' (T '.venv 가 없어 실행하지 못했습니다' 'not run because .venv is not ready')
} else {
    $doctorOut = @(& $venvPy $launcher doctor --root $projectRoot 2>&1 | ForEach-Object { "$_" })
    $doctorCode = $LASTEXITCODE
    if ($doctorCode -eq 0) {
        Add-Item 'S15' 'required' 'doctor' 'ok' (T '실패한 축 없음' 'no failing axis') '' @($doctorOut)
    } else {
        Set-Flag 'fail'
        Add-Item 'S15' 'required' 'doctor' 'fail' (T '실패한 축이 있습니다(아래 해결 줄 참고)' 'at least one axis failed (see the fix lines below)') '' @($doctorOut)
    }
}

Complete-Run
