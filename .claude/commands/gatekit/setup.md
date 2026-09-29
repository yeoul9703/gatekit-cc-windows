---
name: setup
description: Prepare gatekit on Windows — check uv, build the .venv from uv.lock, initialize .gatekit/config.json, check the Claude worker backend and run doctor.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit:setup

Input: `$ARGUMENTS` — unused; reserved for future backend configuration.

gatekit needs exactly two programs: Claude Code and **uv**. uv downloads the
Python it needs by itself; nothing else has to be installed. The work is done by
one script, `.claude/gatekit/scripts/setup.ps1`; this command runs it, shows the
result, and installs something **only after the user says yes in the chat**.
The user may not know the terminal: use plain words, no jargon.

## Step 0 — load policy and language

1. Read `.claude/gatekit/policy/language.md`.
2. Detect the language. `$ARGUMENTS` carries no signal here. If `spec/01-prd.md`
   exists, run:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py lang --file spec/01-prd.md --lines 40
```

   Otherwise use the language of the user's own message (`ko` if Korean, else
   `en`). If uv or the `.venv` is not there yet the command above cannot run —
   then just use the language of the user's message.

Call it `output_lang` and write every user-facing string in it.

## Step 1 — say what the permission windows mean, then check

Before the first tool call, tell the user in one sentence (in `output_lang`):
"A permission window from Claude only asks whether a check may run; installing
anything is a separate question I will ask here in the chat." (Korean: "권한 창은
실행을 허락하는 창이고, 프로그램 설치를 허락하는 질문은 채팅에서 따로 드립니다.")

Then run the check. It changes nothing except the project's own `.gatekit/config.json`
and, when `.venv` is missing, one `uv sync --frozen --no-dev --no-python-downloads`
(no download, nothing deleted). It never installs or updates a program and never
downloads Python. Run it with the PowerShell tool (or Bash), in exactly this form —
the flags make it work under any execution policy, including a zip download marked
as coming from the internet. **Always pass `-Lang <output_lang>`** (`ko` or `en`),
also on every later run:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Json -Lang <output_lang>
```

Use `ko` or `en` for `<output_lang>`. The output is one JSON object:
`exit_code` and `items`, each item `{id, level, name, verdict, detail, action}`
(`hints` are extra lines). `verdict` is `ok`, `warn`, `fail`, `unverified` or
`info`; `level` is `required`, `recommended` or `info`. What the items cover:

| id | what |
|---|---|
| S1, S17, S8 | Windows version, folder path (OneDrive or very long), script mark |
| S3 | winget present, its version, whether its source terms were accepted |
| S2 | PowerShell 7 (stable 7.6 recommended; a preview build only warns) |
| S4 | uv (required, at least 0.4.27) and how it was installed |
| S5 | `.claude/gatekit/.venv` (default check: `uv sync --frozen --no-dev --no-python-downloads` only; a missing Python or a damaged `.venv` is a `warn`/`fail` that asks for `-Install venv`) |
| S12 | `.gatekit/config.json` and the hooks in `.claude/settings.json` |
| S6 | the `claude` CLI on PATH (required; the desktop app alone has no CLI) |
| S7, S18, S23 | Git, Node/npm (only with a `package.json`), Python stub note — information |
| S15 | doctor |

Exit codes: `0` ready · `1` failed · `2` the user must allow or do something ·
`3` a program is installed but not visible in this session (PATH), restart needed ·
`4` blocked by policy or network. When several apply, the first of `1, 4, 3, 2` wins.
The check judges by the PATH of the current session only; a program that shows up
only after re-reading the registry PATH is a `warn` with exit `3`.

## Step 2 — show the result as a table

Write a short table in `output_lang`: one row per item with the verdict (`ok`,
`warn`, `fail`, or `unverified` = "not checked", never "ok") and the plain-language
detail. Do not paste raw JSON. Doctor `unverified` axes (no `spec/` yet, no
contract yet) are normal in a new project; follow `verification.md`.

## Step 3 — if something can be installed, ask once

Installable candidates are the items with verdict `fail` **or `warn`** that a
switch can fix: missing, too old, a preview build, or a broken receipt:

| name | switch | purpose | terms | download | admin |
|---|---|---|---|---|---|
| `uv` (S4 fail) | `-Install uv` | runs gatekit and fetches Python | none with the official script; winget adds source terms | small | no |
| `uv` (S4 warn: broken receipt, or too old) | `-Update uv` | repairs `uv self update` | none | small | no |
| `claude` (S6 fail) | `-Install claude` | the Claude Code CLI that workers use | none | tens of MB | no |
| `claude` (S6 warn: older than recommended) | `-Update claude` | newer CLI | none | tens of MB | no |
| `pwsh` (S2 warn: missing) | `-Install pwsh` | PowerShell 7, optional | includes winget source and package terms | tens of MB | no |
| `pwsh` (S2 warn: preview or older) | `-Update pwsh` | stable PowerShell 7.6; an older MSI install may show a Windows administrator prompt (UAC) | includes winget terms | tens of MB | maybe (MSI) |
| `venv` (S5 warn: no Python; S5 fail: damaged) | `-Install venv` | Python and packages for the hooks; **a damaged `.claude/gatekit/.venv` is deleted and rebuilt** | none | Python plus packages, tens of MB | no |
| `git` | `-Install git` (prints a command only) | Git for Windows, optional | — | — | may need it |

If there are no candidates, skip to Step 5. Otherwise ask **one**
`AskUserQuestion` (it is deliberately not in `allowed-tools`, so the choice window
really appears; see `policy/questioning.md`). Put one line per candidate in the
question text: name, purpose, whether agreeing to terms is included, how much is
downloaded, whether administrator rights are needed. For `venv` say plainly that
Python and packages are downloaded (tens of MB, network needed) and, if S5 was a
`fail`, that the damaged `.claude/gatekit/.venv` folder is deleted and rebuilt (it is
a folder inside this project and can be rebuilt). Options: **install all** / **let me choose** /
**later**. If the user chooses "let me choose", ask which names in a plain chat
message and wait for the answer. Wait for the answer; never assume it.

- `git` may need administrator rights and the script never installs it: show the
  command it prints and let the user do it. Offer it only as a separate, optional
  note, never inside "install all".
- If the user picks "later", stop and say that gatekit hooks stay inactive until
  `uv` and the `.venv` exist. Nothing is installed.

For manual reference, the commands the script would run for uv are (do not run them
yourself unless the user asks you to, and run an install command only after
the user has agreed):

```
winget install --id=astral-sh.uv -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Step 4 — install only what was allowed, then check again

Pass exactly the allowed names (`pwsh`, `uv`, `claude`, `git`, `venv` are the only
names the script accepts) and nothing else. Missing things go to `-Install`, the
`warn` candidates that already exist go to `-Update` (`venv` only ever with `-Install`).
Both switches may be given in one call:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install uv,claude,venv -Update pwsh -Json -Lang <output_lang>
```

`-Update git` never runs anything: Git is left as it is. Only the names in `-Install` / `-Update` receive
winget's `--accept-source-agreements --accept-package-agreements`, which is why the
question in Step 3 said terms are included. Then run the plain check from Step 1
again and show the new table. React to the exit code:

- `0` — ready; go to Step 5.
- `3` — installed but not visible: tell the user to close the Claude app (the VS
  Code window) completely, open it again, and type `/gatekit:setup` again. Stop.
- `4` — blocked by policy or network. Show the "what you can do now" lines and the
  message for the IT contact from the `hints`, so the user can forward it. Do not
  retry in a loop and do not look for a way around the policy.
- `2` — something still needs the user (a declined item, or administrator rights):
  say exactly which and what to do.
- `1` — a step failed for another reason: show the lines the script printed and
  ask the user to retry when the cause is fixed. `uv sync` failing with `-Install
  venv` usually means no network (uv fetches Python); behind a proxy the hints list
  `UV_SYSTEM_CERTS`, `SSL_CERT_FILE` and `HTTPS_PROXY`.

Never enable a bypass flag to make a worker run; a missing `claude` CLI is fixed by
installing it (Step 3), nothing else.

## Step 5 — confirm

Report in `output_lang` what changed (installed programs, created
`.gatekit/config.json` or left as it was, a rebuilt `.venv`) and name the file each
change landed in. Doctor already ran inside the script (item S15, in `output_lang`).

To look at the worker backends in more detail:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers check claude
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers list
```

`workers check` verdicts: `ok` — the CLI answered its version probe;
`unverified` — the binary is there but the probe did not answer (not a failure,
not a pass; builds will still run); `fail` — the binary is missing.

A project that wants an additional worker backend can add one to
`.gatekit/config.json`'s `worker.backends` by hand (see `docs/USAGE.md`), then
enable it with `workers enable <name>`.
