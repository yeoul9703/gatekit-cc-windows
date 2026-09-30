# common.ps1 - helpers shared by setup.ps1 and session-check.ps1: PATH rule (Get-MergedPath, Find-App, Get-App), ASCII-only JSON (ConvertTo-AsciiJson).
# Windows PowerShell 5.1 compatible. Both scripts load it with:  . "$PSScriptRoot\common.ps1"
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
