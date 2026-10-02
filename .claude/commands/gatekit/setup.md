---
name: setup
description: Prepare gatekit on Windows — check uv, build the .venv from uv.lock, initialize .gatekit/config.json, check the Claude worker backend and run doctor. Installs a program only after the user says yes. Korean triggers — "셋업 해줘", "초기 설정", "설치해줘", "워커 확인해줘", "백엔드 설정". English triggers — "set up gatekit", "install gatekit", "check my workers", "configure the backend". NOT for diagnosing a project that is already set up — that is /gatekit:doctor — and NOT for enabling a bypass or unsandboxed backend, which gatekit refuses.
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

Read `.claude/gatekit/policy/preamble.md` and follow it, detecting
`output_lang` **from the spec**. On a first run there is no spec and maybe no
uv yet; the preamble's fallback (the language of the user's own message)
covers that.

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

The output is one JSON object: `exit_code` and `items`, each item
`{id, level, name, verdict, detail, action}` (`hints` are extra lines). Each
item explains itself in `name`, `detail` and `action`. `verdict` is `ok`,
`warn`, `fail`, `unverified` or `info`; `level` is `required`, `recommended`
or `info`. The check judges by the PATH of the current session only.

## Step 2 — show the result as a table

Write a short table in `output_lang`: one row per item with the verdict (`ok`,
`warn`, `fail`, or `unverified` = "not checked", never "ok") and the plain-language
detail. Do not paste raw JSON. Doctor `unverified` axes (no `spec/` yet, no
contract yet) are normal in a new project.

## Step 3 — if something can be installed, ask once

Installable candidates are the items with verdict `fail` **or `warn`** whose
`action` names a switch. Missing things go to `-Install`, things that exist
but are old or broken go to `-Update`:

| name | switch | purpose | terms | download | admin |
|---|---|---|---|---|---|
| `uv` | `-Install uv` / `-Update uv` | runs gatekit and fetches Python | none with the official script; winget adds source terms | small | no |
| `claude` | `-Install claude` / `-Update claude` | the Claude Code CLI that workers use (the desktop app or the VS Code extension alone does not provide it) | none | tens of MB | no |
| `pwsh` | `-Install pwsh` / `-Update pwsh` | PowerShell 7, optional | includes winget source and package terms | tens of MB | maybe, for an older MSI install |
| `venv` | `-Install venv` only | Python and packages for the hooks; **a damaged `.claude/gatekit/.venv` is deleted and rebuilt** | none | tens of MB | no |
| `git` | prints a command only | Git for Windows, optional | — | — | may need it |

If there are no candidates, skip to Step 5. Otherwise ask **one**
`AskUserQuestion` (it is deliberately not in `allowed-tools`, so the choice window
really appears; see `policy/questioning.md`). Put one line per candidate in the
question text: name, purpose, whether agreeing to terms is included, how much is
downloaded, whether administrator rights are needed. For `venv` say plainly that
Python and packages are downloaded (network needed) and, if its verdict was
`fail`, that the damaged `.claude/gatekit/.venv` folder is deleted and rebuilt.
Options: **install all** / **let me choose** / **later**. If the user chooses
"let me choose", ask which names in a plain chat message. Wait for the answer;
never assume it.

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

Pass exactly the allowed names and nothing else (`pwsh`, `uv`, `claude`, `git`,
`venv` are the only names the script accepts). Both switches may be given in
one call:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install uv,claude,venv -Update pwsh -Json -Lang <output_lang>
```

Only the names passed here receive winget's `--accept-source-agreements
--accept-package-agreements`, which is why the question in Step 3 said terms
are included. Then run the plain check from Step 1 again, show the new table,
and react to the exit code:

- `0` — ready; go to Step 5.
- `3` — installed but not visible in this session: tell the user to close
  Claude Code completely (the desktop app, the VS Code window, or the terminal
  it runs in), open it again, and type `/gatekit:setup` again. Stop.
- `4` — blocked by policy or network. Show the "what you can do now" lines and the
  message for the IT contact from the `hints`, so the user can forward it. Do not
  retry in a loop and do not look for a way around the policy.
- `2` — something still needs the user (a declined item, or administrator rights):
  say exactly which and what to do.
- `1` — a step failed for another reason: show the lines the script printed and
  ask the user to retry when the cause is fixed. `uv sync` failing with `-Install
  venv` usually means no network; behind a proxy the hints list `UV_SYSTEM_CERTS`,
  `SSL_CERT_FILE` and `HTTPS_PROXY`.

When several apply, the first of `1, 4, 3, 2` wins.

Never enable a bypass flag to make a worker run; a missing `claude` CLI is fixed by
installing it (Step 3), nothing else.

## Step 5 — confirm

Report in `output_lang` what changed (installed programs, created
`.gatekit/config.json` or left as it was, a rebuilt `.venv`) and name the file each
change landed in. Doctor already ran inside the script (the `S15` item), so do
not run `/gatekit:doctor` again here. Then name the next command:
`/gatekit:discover` when the user does not yet know what to build,
`/gatekit:interview` when they do.

## Reference — rare paths, read before acting

`docs/SETUP-REFERENCE.md` holds what this command needs only occasionally.
Read the named section when one of these comes up:

- **The user asks for a reinstall**, or `-Update uv` did not repair a broken
  `uv self update` — section 2-3-1. `-Reinstall` takes only `uv`, `pwsh`,
  `claude`, and it is a **separate permission**: ask again in the same way
  (name, what it does, terms, download size, administrator rights) before
  running it. Never offer it on your own.
- **The `P-failures` item is `warn`** (recorded failed installs) — section 7.
  Say which items failed and why, and ask **again** before `-RetryFailed`; the
  earlier permission does not carry over.
- **A winget error code** appears in the output — section 6.
- **uv or the `.venv` is broken so `gatekit.py` cannot start** — section 9:
  run `scripts/setup.ps1` directly with the same switches, and tell the user
  so in plain words.
- **Looking at the package table without the `.venv` and doctor steps** — the
  `-Status` switch in section 3 (no permission needed, nothing changes).
- **Worker backends in more detail** — run the two commands below.
  `workers check` verdicts: `ok` — the CLI answered its version probe;
  `unverified` — the binary is there but the probe did not answer (not a
  failure, not a pass; builds will still run); `fail` — the binary is
  missing. An additional backend is added by hand (see `docs/USAGE.md`) and
  enabled only by the user.

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers check claude
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers list
```
