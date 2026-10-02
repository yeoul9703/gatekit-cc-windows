# Programs setup can install

Read this at `/gatekit-setup` Step 3, before writing the install question. It
says what to tell the user about each candidate and which cases stay out of
"install all". Nothing here is a permission: the user's yes in the chat is.

## The programs

| name | switch | level | purpose | terms | download | admin |
|---|---|---|---|---|---|---|
| `winget` | `-Install winget` only | recommended | Windows' package manager; `pwsh` installs through it | none for the first attempt (registers the App Installer already on the PC); the fallback installs a PowerShell Gallery module | nothing for the first attempt; a few MB for the fallback | not expected; if the fallback cannot finish, the script points to the Microsoft Store |
| `pwsh` | `-Install pwsh` / `-Update pwsh` | required | PowerShell 7 stable; Claude Code runs its PowerShell tool and the input-box `!` commands with it | includes winget source and package terms | tens of MB | maybe, for an older MSI install |
| `uv` | `-Install uv` / `-Update uv` | required | runs gatekit and fetches Python | none with the official script; winget adds source terms | small | no |
| `claude` | `-Install claude` / `-Update claude` | required | the Claude Code CLI that workers use (the desktop app or the VS Code extension alone does not provide it) | none | tens of MB | no |
| `venv` | `-Install venv` only | required | Python and packages for the hooks; **a damaged `.claude/gatekit/.venv` is deleted and rebuilt** | none | tens of MB | no |
| `git` | prints a command only | optional | Git for Windows | — | — | may need it |

Only the names passed to `-Install` or `-Update` receive winget's
`--accept-source-agreements --accept-package-agreements`. That is why the
question must say, per candidate, whether agreeing to terms is included.

## What each line of the question says

One line per candidate: name, purpose, whether agreeing to terms is included,
how much is downloaded, whether administrator rights are needed.

- **`venv`**: say plainly that Python and packages are downloaded (network
  needed). If its verdict was `fail`, also say that the damaged
  `.claude/gatekit/.venv` folder is deleted and rebuilt.
- **`git`**: the script never installs it, because it may need administrator
  rights. Show the command the script prints and let the user run it. Offer
  it as a separate, optional note, never inside "install all".

## PowerShell 7 (`S2`): the stable product is what counts

The check asks whether the **stable** PowerShell 7 product is installed, not
which `pwsh` comes first on PATH. A preview build does not count.

| State | Verdict | `action` |
|---|---|---|
| stable installed, 7.6.0 or newer | `ok` (if a preview build comes first on PATH, the detail only mentions it) | — |
| stable installed, older than 7.6.0 | `fail` | `-Update pwsh` |
| only a preview build | `fail` | `-Install pwsh` |
| nothing installed | `fail` | `-Install pwsh`, or `-Install winget,pwsh` when winget is missing too |
| installed, but not on this session's PATH | `warn`, exit code 3 | reopen Claude Code |

`pwsh` installs through winget only. Do not look for another download.

## winget (`S3`)

winget is `recommended`: when it is missing the item is `warn` with action
`-Install winget`. uv and claude install without it; `pwsh` does not. The
script never installs winget before `pwsh` on its own: when both are missing
the `S2` action names both (`-Install winget,pwsh`), and the user allows both
or neither.

`-Install winget` tries, in order: register the App Installer that Windows
already carries (no download); then the `Microsoft.WinGet.Client` module's
repair; then it stops with exit code 2 and the Microsoft Store link for the
user to open. A policy or network block is exit code 4. `winget` is not
accepted by `-Update` or `-Reinstall`.

If `-Install winget,pwsh` was allowed and the winget part fails, the `pwsh`
line (`S16-pwsh`) names the failed winget install as its cause. Resolve the
`S16-winget` line first; `pwsh` cannot be installed before that.

The session-start check applies the same stable-product rule without
starting `pwsh`: a PC with only a preview build gets the message "only a
preview build is installed", which leads here to `-Install pwsh`.

## uv by hand

For reference, these are the commands the script runs for uv. Do not run them
yourself unless the user asks you to, and then only after the user has agreed
in the chat:

```
winget install --id=astral-sh.uv -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
