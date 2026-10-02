# common.ps1 - helpers shared by setup.ps1, session-check.ps1 and verify.ps1: PATH rule (Get-MergedPath, Find-App, Get-App), PowerShell 7 product rule (Get-PwshProduct), ASCII-only JSON (ConvertTo-AsciiJson), whether this project runs the claude CLI (Test-CliRequired), one argument quoted for a new process (Quote-Arg).
# Windows PowerShell 5.1 compatible. Each script loads it with:  . "$PSScriptRoot\common.ps1"
# It only defines functions: it prints nothing, never exits and leaves $ErrorActionPreference to the caller.
# Every function gets what it needs as a parameter, so none depends on a variable of the script that loaded it.
# A function of this file must not be defined again in a script (the later definition would silently win).

# ---- PATH rule -------------------------------------------------------------------------------
# A program counts as present only if it is on the PATH of THIS session. Installers write the
# registry PATH (Machine + User), not the running process, so a program that is visible only after
# merging the registry PATH is "installed but not visible in this session" (restart needed), not
# "not installed". The merged PATH is only used for that lookup; it is never assigned to the session.
# Test hooks (environment): GATEKIT_SETUP_KEEP_PATH=1 never reads the registry (merged = session);
# GATEKIT_SETUP_REGISTRY_PATH replaces the registry PATH value.

# Registry Machine + User PATH merged with $sessionPath, in that order. Entries are trimmed,
# %VARIABLES% are expanded, empty ones are dropped and duplicates (case and a trailing "\" ignored) removed.
function Get-MergedPath([string]$sessionPath = $env:Path) {
    if ($env:GATEKIT_SETUP_KEEP_PATH -eq '1') { return $sessionPath }
    $machine = ''
    $user = ''
    if ($env:GATEKIT_SETUP_REGISTRY_PATH) {
        $machine = $env:GATEKIT_SETUP_REGISTRY_PATH
    } else {
        try {
            $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $user = [Environment]::GetEnvironmentVariable('Path', 'User')
        } catch { }
    }
    $seen = @{}
    $merged = @()
    foreach ($src in @($machine, $user, $sessionPath)) {
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

# Looks a program up on $pathValue (default: the current process PATH); the session PATH is put back afterwards.
function Find-App([string]$name, [string]$pathValue = '') {
    $saved = $env:Path
    if ($pathValue) { $env:Path = $pathValue }
    try { return @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue) }
    finally { $env:Path = $saved }
}

# where = session (found on the session PATH) / registry (found only after merging the registry PATH: restart needed) / none.
function Get-App([string]$name, [string]$sessionPath = $env:Path) {
    $s = Find-App $name $sessionPath
    if ($s.Count -gt 0) { return @{ apps = $s; where = 'session' } }
    $m = Find-App $name (Get-MergedPath $sessionPath)
    if ($m.Count -gt 0) { return @{ apps = $m; where = 'registry' } }
    return @{ apps = @(); where = 'none' }
}

# ---- PowerShell 7: which product is installed --------------------------------------------------
# The stable product and the preview build are two products: the Windows package names differ
# (appx_name / appx_preview_name in packages.json; the caller passes them in) and the MSI folders
# differ (<Program Files>\PowerShell\7 and 7-preview). Nothing here starts a process, so
# session-check.ps1 can use it; setup.ps1 adds the version text of the pwsh on PATH on top.
function ConvertTo-Version3([string]$text) {
    if ($text -match '(\d+)\.(\d+)\.(\d+)') { return ($Matches[1] + '.' + $Matches[2] + '.' + $Matches[3]) }
    return ''
}

# Package versions as text ('' = not installed). An empty name is not looked up.
# Test hook: GATEKIT_SETUP_PWSH_PACKAGES replaces the Get-AppxPackage lookup: "none", or
# "<package name>=<version>" pairs separated by ";" (an empty value counts as not set).
function Get-PwshPackages([string]$stableName, [string]$previewName) {
    $res = @{ stable = ''; preview = '' }
    if ($env:GATEKIT_SETUP_PWSH_PACKAGES) {
        foreach ($pair in ($env:GATEKIT_SETUP_PWSH_PACKAGES -split ';')) {
            $kv = @($pair -split '=', 2)
            if ($kv.Count -ne 2) { continue }
            $pkgName = $kv[0].Trim()
            if ($stableName -and $pkgName -eq $stableName) { $res.stable = $kv[1].Trim() }
            elseif ($previewName -and $pkgName -eq $previewName) { $res.preview = $kv[1].Trim() }
        }
        return $res
    }
    foreach ($slot in @(@('stable', $stableName), @('preview', $previewName))) {
        if (-not $slot[1]) { continue }
        try {
            $found = @(Get-AppxPackage -Name $slot[1] -ErrorAction Stop | Sort-Object { [version]$_.Version } -Descending)
            if ($found.Count -gt 0) { $res[$slot[0]] = "$($found[0].Version)" }
        } catch { }
    }
    return $res
}

# The MSI install: stable = its version text ('' = not there, '?' = there but unreadable).
# The folder is looked up under the ProgramW6432 / ProgramFiles environment variable.
function Get-PwshMsi {
    $res = @{ stable = ''; stablePath = ''; preview = $false }
    $pf = $env:ProgramW6432
    if (-not $pf) { $pf = $env:ProgramFiles }
    if (-not $pf) { return $res }
    $root = Join-Path $pf 'PowerShell'
    $exe = Join-Path $root '7\pwsh.exe'
    if (Test-Path -LiteralPath $exe) {
        $res.stablePath = $exe
        $vt = ''
        try { $vt = ConvertTo-Version3 "$((Get-Item -LiteralPath $exe).VersionInfo.ProductVersion)" } catch { }
        if (-not $vt) { $vt = '?' }
        $res.stable = $vt
    }
    if (Test-Path -LiteralPath (Join-Path $root '7-preview\pwsh.exe')) { $res.preview = $true }
    return $res
}

# The one rule both scripts share. stable: a stable product is installed (package first, then the
# MSI folder). source: package / msi / ''. version: three numbers ('?' if unreadable). path: the MSI
# pwsh.exe ('' for a package). preview: a preview product was seen.
function Get-PwshProduct([string]$stableName, [string]$previewName) {
    $st = @{ stable = $false; version = ''; source = ''; path = ''; preview = $false }
    $pk = Get-PwshPackages $stableName $previewName
    $msi = Get-PwshMsi
    if ($pk.preview -or $msi.preview) { $st.preview = $true }
    if ($pk.stable) {
        $st.stable = $true; $st.source = 'package'; $st.version = ConvertTo-Version3 $pk.stable
        if (-not $st.version) { $st.version = '?' }
    } elseif ($msi.stable) {
        $st.stable = $true; $st.source = 'msi'; $st.version = $msi.stable; $st.path = $msi.stablePath
    }
    return $st
}

# stable / preview / unknown for one pwsh.exe WITHOUT running it: the folder name (7-preview, or
# the preview package folder) and the product version text inside the file ("7.7.0-preview.5").
# A Windows app alias (a 0 byte pwsh.exe under WindowsApps) carries no version: unknown.
function Get-PwshFileKind([string]$path, [string]$previewName = '') {
    if ($path -match '(?i)\\7-preview\\') { return 'preview' }
    if ($previewName -and $path -match ('(?i)\\' + [regex]::Escape($previewName) + '_')) { return 'preview' }
    $pv = ''
    try { $pv = "$((Get-Item -LiteralPath $path).VersionInfo.ProductVersion)" } catch { }
    if ($pv -match '^\s*(\d+)\.(\d+)\.(\d+)(-[A-Za-z]\S*)?') {
        if ($Matches[4]) { return 'preview' }
        return 'stable'
    }
    return 'unknown'
}

# ---- Does this project run the claude CLI? -------------------------------------------------------
# With the default settings nothing starts the `claude` command: build.execution is "host" (the
# session does the work itself) and the reviewer of /gatekit-verify is a subagent of the session.
# The CLI is started only when .gatekit/config.json says build.execution = "worker", or names a
# backend in verify.evaluator (any value other than "agent"). Only then is a missing CLI a problem.
# This is the one PowerShell copy of the rule (setup.ps1 S6 and session-check.ps1 both call it);
# the Python copy is cli_required in gatekit/doctor.py. The file is only read, and read as JSON
# here, so the answer does not need the .venv. No file, or one that cannot be read: $false.
function Test-CliRequired([string]$projectRoot) {
    try {
        $file = Join-Path $projectRoot '.gatekit\config.json'
        if (-not (Test-Path -LiteralPath $file)) { return $false }
        $cfg = (Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json)
        if (-not $cfg) { return $false }
        if ("$($cfg.build.execution)".Trim() -ceq 'worker') { return $true }
        $evaluator = $cfg.verify.evaluator
        if ($evaluator -is [string]) {
            $evaluator = $evaluator.Trim()
            if ($evaluator -and $evaluator -cne 'agent') { return $true }
        }
    } catch { }
    return $false
}

# ---- One argument of a command line --------------------------------------------------------------
# setup.ps1 and verify.ps1 start a program without a shell, so the arguments travel as one text
# (ProcessStartInfo.Arguments) that the program splits again. This quotes one argument so that it
# comes back unchanged: quoted only when it is empty or holds white space or a quote; inside the
# quotes every quote becomes \" and the backslashes right before a quote are doubled, and so are
# the ones at the very end, which would otherwise escape the closing quote and take the next
# argument with them ("C:\dir with space\" has to be "C:\dir with space\\").
function Quote-Arg([string]$a) {
    if ($a -eq '') { return '""' }
    if ($a -notmatch '[\s"]') { return $a }
    $s = $a -replace '(\\*)"', '$1$1\"'
    $s = $s -replace '(\\+)\z', '$1$1'
    return '"' + $s + '"'
}

# ---- JSON that is pure ASCII ---------------------------------------------------------------------
# Every char above 0x7E of a JSON text becomes \uXXXX, so the output does not depend on the console
# code page. Give it the result of ConvertTo-Json (it already escapes quotes, backslashes, newlines).
function ConvertTo-AsciiJson([string]$json) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $json.ToCharArray()) {
        $code = [int]$ch
        if ($code -gt 126) { [void]$sb.AppendFormat('\u{0:x4}', $code) } else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}
