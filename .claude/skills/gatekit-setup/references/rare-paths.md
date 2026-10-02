# Setup: rare paths

Read this in `/gatekit-setup` when the user asks for a reinstall, when the
`P-failures` item is `warn`, when a winget error code appears in the output,
when the gatekit CLI cannot start, when the exit code is 4, or when one of
`S8`, `S17`, `S20` is not `ok`. Each action below that changes the PC
needs its own yes in the chat; an earlier permission does not carry over.

Every script call uses the same form as Step 1, with `-Lang <output_lang>`:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 <switches> -Json -Lang <output_lang>
```

## Switches

| Purpose | Switch | Accepted names | Permission |
|---|---|---|---|
| check only | (none) | — | none |
| program table and failure record only | `-Status` | — | none; nothing changes |
| install | `-Install` | `winget`, `pwsh`, `uv`, `claude`, `git`, `venv` | yes in the chat |
| update | `-Update` | `pwsh`, `uv`, `claude`, `git` | yes in the chat |
| reinstall | `-Reinstall` | `uv`, `pwsh`, `claude` | a separate yes |
| retry recorded failures | `-RetryFailed` | — | a separate yes |

A name outside the list is refused with exit code 1. `-Status` cannot be
combined with the switches that change something.

## Reinstall (`-Reinstall`)

Use it when the user asks for a reinstall, or when `-Update uv` did not
repair a broken `uv self update`. Never offer it on your own.

Ask again before running it, in the same way as an install: name, what it
does, whether terms are included, download size, administrator rights. What
the script does per name:

- `uv` — winget `--force` or the official script, matching how uv was
  installed. A uv installed by another tool (scoop, pip) is not reinstalled;
  the script prints that tool's command instead.
- `pwsh` — winget MSIX with `--force`.
- `claude` — the official script.

It reads the version again afterwards and shows it.

## Retry recorded failures (`-RetryFailed`)

A failed install, update or reinstall is recorded in
`.gatekit/runs/setup-last.json` (time, item, action, exit code, category,
message). The record of an item is removed when that item later succeeds.

When `P-failures` is `warn`, say which items failed and why, and ask
**again** before `-RetryFailed`. It retries only the recorded items, each
with the same action as before. With no record it prints one line and does
nothing.

## Looking without changing (`-Status`)

`-Status` shows the program table and the failure record and skips the
`.venv`, the config and doctor. It needs no permission.

## winget error codes

| Code | Meaning | What the script does | What to tell the user |
|---|---|---|---|
| `0x8A15002B` | nothing to update | treated as success | nothing |
| `0x8A150061` | already installed | treated as success | nothing |
| `0x8A15003A`, `0x8A15010F`, `0x8A15001B`, `0x8A15001C` | blocked by policy | exit code 4 (a new uv or claude install falls back to the official script) | forward the IT message from the `hints` |
| `0x8A150109` | installed, restart needed | exit code 3 | restart the PC, then run setup again |
| `0x8A150107` | cannot reach the install server | exit code 4 | check the internet, VPN or proxy, then retry |
| `0x80072EFD` | secure connection failed | exit code 4 | retry on another network |
| `0x8A150046`, `0x8A150041` | winget source terms not accepted yet | exit code 2 | allow the install again (terms are then included for that item) |

Any other code is an unknown failure (exit code 1): show the last lines the
script printed.

## The CLI cannot start

The gatekit CLI needs uv and the `.venv`. When uv is broken or the `.venv` is
missing, run the script directly, as above; it needs only the Windows
PowerShell 5.1 that Windows ships with. Tell the user in plain words that the
script is being run directly. The same permissions apply to `-Install`,
`-Update` and `-Reinstall`.

If the script file itself is missing, do not rebuild it by hand: tell the
user the files under `.claude/gatekit/scripts` have to be restored. With Git
installed that is `git checkout .claude/gatekit/scripts`; without Git (the
project came as a zip file) the user downloads the repository again and
overwrites that folder.

## A kit file is missing or damaged

The script's `action` already says which way applies: when Git is on this
session's PATH it prints `git checkout <file>`; when it is not, it says to
download the repository again and overwrite that file. Pass that on as it
is. Do not suggest installing Git just for this, and do not recreate the
file by hand. Only when `common.ps1` itself cannot be read does the script
print both ways, because it cannot look for Git at that point.

## Environment items

These items look and never change anything. None of them is an install
candidate; do not put them into the "install all" question.

| Item | What it checks | Verdicts | What to tell the user |
|---|---|---|---|
| `S17` | project folder length plus the longest file path inside it (79 characters) against Windows' 259 character limit | `warn` when the sum is over 259, i.e. the folder path is longer than 179 characters; `ok` when the registry value `LongPathsEnabled` is 1 | move the project to a shorter folder such as `C:\dev` |
| `S20` | the execution policy pinned by group policy (`MachinePolicy`, then `UserPolicy`) | `fail` and exit code 4 for `AllSigned` or `Restricted`; otherwise `ok` | forward the IT message from the `hints` |
| `S8` | the "downloaded from the internet" mark on every `.ps1` file in the scripts folder | `ok` without a mark; `info` naming the marked files; `warn` and exit code 2 when group policy says `RemoteSigned` | show the one command from the `hints` |

**`S20` is `fail`.** The hooks and the scripts start with
`-ExecutionPolicy Bypass`, and a group policy beats that flag, so the
unsigned gatekit scripts do not run. Nothing the user allows fixes it. Show
the IT message. Do not run or suggest `Set-ExecutionPolicy`, do not sign or
rewrite the scripts, and do not look for another way to start them. On such
a PC the setup script usually cannot start at all: when the check itself
ends with "cannot be loaded because running scripts is disabled on this
system", tell the user the same thing and ask them to send the output of
`Get-ExecutionPolicy -List` to their IT contact.

**`S8` names marked files.** The script never removes the mark. With `info`
everything still works, so only mention it. With `warn` the marked files do
not run until the mark is gone: show the command from the `hints`
(`Get-ChildItem .claude\gatekit\scripts\*.ps1 | Unblock-File`) and let the
user run it in the project folder. Run it yourself only after the user has
agreed in the chat; it is its own question, not part of an install.

**`S4` or `S5` says a policy blocks the program from running** (Windows
error 1260 or 4551: `uv.exe` or the `.venv` `python.exe` exists but Windows
refuses to start it). This is exit code 4. A reinstall or `-Install venv`
puts the same file back and it is refused again, so offer neither; the
script does not delete the `.venv` in this case. Show the IT message from
the `hints` and say that the gatekit hooks stay off until the program is
allowed. Any other start failure still reads "could not run it to read the
version" and keeps the reinstall offer, because the script cannot tell
whether a policy is behind it.

## `-Install winget,pwsh` and winget failed

When the winget install of the same run fails, the `S16-pwsh` item says "the
winget install failed, so PowerShell 7 could not be installed". The cause is
the `S16-winget` item: handle that one (the Microsoft Store link, or the IT
contact for exit code 4) and do not ask for `-Install winget` again.

## Worker backends in more detail

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers check claude
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers list
```

`workers check` verdicts: `ok` — the CLI answered its version probe;
`unverified` — the binary is there but the probe did not answer (not a
failure, not a pass; builds will still run); `fail` — the binary is missing.
An additional backend is added by hand in `.gatekit/config.json` under
`worker.backends` and enabled only by the user. If they ask how, tell them
the usage guide in the project's docs folder describes it.
