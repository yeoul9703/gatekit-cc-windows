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
| `claude` | `-Install claude` / `-Update claude` | recommended | the Claude Code CLI; gatekit never starts it, and setup only reads the Claude Code version from it (`S6`). The desktop app or the VS Code extension alone is enough | none | tens of MB | no |
| `venv` | `-Install venv` only | required | Python and packages for the hooks; **a damaged `.claude/gatekit/.venv` is deleted and rebuilt** | none | tens of MB | no |
| `git` | `-Install git` only | recommended | Git for Windows; gatekit runs without it, but a project that came as a zip file has nothing to restore a changed file from and keeps no history | includes winget source and package terms | tens of MB | not for the first attempt (user scope); a Windows administrator prompt (UAC) may appear if that attempt does not work |
| `node` | `-Install node` only | optional (`info`) | Node.js, for what the user builds; gatekit itself never starts it | includes winget source and package terms | tens of MB | not for the first attempt (user scope); a Windows administrator prompt (UAC) may appear if that attempt does not work |

Only the names passed to `-Install` or `-Update` receive winget's
`--accept-source-agreements --accept-package-agreements`. That is why the
question must say, per candidate, whether agreeing to terms is included.

## What each line of the question says

One line per candidate: name, purpose, whether agreeing to terms is included,
how much is downloaded, whether administrator rights are needed.

- **`venv`**: say plainly that Python and packages are downloaded (network
  needed). If its verdict was `fail`, also say that the damaged
  `.claude/gatekit/.venv` folder is deleted and rebuilt.
- **`claude`**: not a candidate and never inside "install all". The `S6`
  item only shows the Claude Code version. `unverified` there (no `claude`
  command in this session) is normal with only the desktop app or the VS
  Code extension: tell the user to keep the app up to date, and do not offer
  an install just to read a version. `warn` (older than the recommended
  version) is a separate, optional note. Pass `-Update claude` or
  `-Install claude` only if the user asks for it.
- **`git`**: a candidate like the others when `S7` is `warn` with
  `-Install git` in its `action` (`-Install winget,git` when winget is missing
  too). Its line says three things: gatekit runs without Git, it is
  recommended so that a changed file can be restored and the work keeps a
  history, and a Windows administrator prompt (UAC) may appear. See the next
  section for what to say before the install runs.
- **`node`**: not a candidate here and never inside "install all". What the
  user builds may need a program of its own, and that is asked about only
  after the interview has fixed the stack, not in `/gatekit-setup`. The
  `S18` item is `info` for a missing or an old Node.js, so do not describe
  it as something missing. `/gatekit-gate` asks when a completion criterion
  needs it and passes `-Install node` after a yes
  (`.claude/skills/gatekit-gate/references/gate-criteria.md`); the script
  then installs it the way it installs Git, user scope first.

## Git (`S7`): user scope first, then the administrator prompt

Git is `recommended`. None of the three states below changes the exit code.

| State | Verdict | `action` |
|---|---|---|
| on this session's PATH | `ok` | — |
| not installed | `warn` | `-Install git`, or `-Install winget,git` when winget is missing too |
| installed, but not on this session's PATH | `warn` | reopen Claude Code |

What `-Install git` does, in order:

1. `winget install --id Git.Git -e --source winget --scope user` — the
   user-scope installer, which needs no administrator rights.
2. Only if that attempt ends with an error the script has no row for (for
   example, no user-scope installer applies): the same command without
   `--scope user`. winget and the Git installer may then show the Windows
   administrator prompt (UAC) themselves. The script prints the `S10-git`
   line before this attempt.
3. If that fails too: the `S16-git` item, with the address to download the
   installer from.

A policy block, a network problem, terms that are not accepted and a timeout
are not retried; they end with their own exit code (4 or 2).

**Say this in the chat before you run `-Install git`**, in `output_lang`: a
Windows administrator prompt may appear during the Git install; it can open
behind other windows, so if nothing seems to happen, look for a flashing icon
on the taskbar and allow it. (Korean: "Git 설치 중에 Windows 관리자 확인 창이
뜰 수 있습니다. 다른 창 뒤에 숨을 수 있으니, 멈춘 것 같으면 작업 표시줄에서
깜박이는 아이콘을 눌러 허용해 주세요.") The script runs with `-Json`, so its
own `S10-git` line reaches the user only after the install has ended; the
notice has to come from you, beforehand. The attempt is stopped after 15
minutes without an answer (exit code 4).

Do not try to get administrator rights yourself: no elevation tool (gsudo,
`Start-Process -Verb RunAs`), no "run as administrator" instruction for the
script. An elevation tool shows the same prompt, and an account without
administrator rights cannot pass it either way. When `S16-git` says the
install failed, show its hints (the download address, the message for the IT
contact) and move on: gatekit works without Git.

After a successful install `S7` may read `warn` "installed but not visible
in this session": the exit code stays as it is, and Git works once Claude
Code has been closed completely and opened again (the desktop app: quit it
from the Claude icon in the notification area). Tell the user so; it does
not block the next step.

`-Update git` only reports that Git is there, and `-Reinstall git` is
refused: an existing Git is never updated or reinstalled by the script.

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
