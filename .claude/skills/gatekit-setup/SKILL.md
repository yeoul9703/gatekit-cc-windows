---
name: gatekit-setup
description: Prepare gatekit on Windows — check uv, build the .venv from uv.lock, initialize .gatekit/config.json, check the Claude worker backend and run doctor. Installs a program only after the user says yes. Korean triggers — "셋업 해줘", "초기 설정", "설치해줘", "워커 확인해줘", "백엔드 설정". English triggers — "set up gatekit", "install gatekit", "check my workers", "configure the backend". NOT for diagnosing a project that is already set up — that is /gatekit-doctor — and NOT for enabling a bypass or unsandboxed backend, which gatekit refuses.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit-setup

Input: `$ARGUMENTS` — unused; reserved for future backend configuration.

gatekit needs three programs: Claude Code, **uv** and **PowerShell 7**. uv
downloads the Python it needs by itself; nothing else has to be installed.
The work is done by one script, `.claude/gatekit/scripts/setup.ps1`; this
skill runs it, shows the result, and installs something **only after the user
says yes in the chat**. The user may not know the terminal: use plain words,
no jargon.

## Safety rules

These hold in every step and in every reference file this skill reads.

- **Install only after a yes in the chat.** A permission window from Claude
  Code allows a check to run; it is not consent to install. Run an install
  command only after the user has agreed in the chat, and pass exactly the
  names they allowed.
- **A reinstall and a retry are separate permissions.** An earlier yes does
  not cover `-Reinstall` or `-RetryFailed`; ask again each time. Never offer a
  reinstall on your own.
- **No bypass.** Never enable a bypass flag or an unsandboxed backend to make
  a worker run, and never look for a way around a company policy or a blocked
  network. A missing `claude` CLI is fixed by installing it, nothing else.

## Reference files

| File | Read it when |
|---|---|
| `.claude/skills/gatekit-setup/references/install-programs.md` | Step 3, before writing the install question |
| `.claude/skills/gatekit-setup/references/settings.md` | the `S12-settings` item is `fail` |
| `.claude/skills/gatekit-setup/references/rare-paths.md` | the user asks for a reinstall, the `P-failures` item is `warn`, a winget error code appears, or the gatekit CLI cannot start |

## Step 0 — load policy and language

Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it,
detecting `output_lang` **from the spec**. On a first run there is no spec and
maybe no uv yet; the preamble's fallback (the language of the user's own
message) covers that.

## Step 1 — say what the permission windows mean, then check

Before the first tool call, tell the user in one sentence (in `output_lang`):
"A permission window from Claude only asks whether a check may run; installing
anything is a separate question I will ask here in the chat." (Korean: "권한 창은
실행을 허락하는 창이고, 프로그램 설치를 허락하는 질문은 채팅에서 따로 드립니다.")

Then run the check. It changes nothing except the project's own
`.gatekit/config.json` and, when `.venv` is missing, one
`uv sync --frozen --no-dev --no-python-downloads` (no download, nothing
deleted). It never installs or updates a program and never downloads Python.
Run it with the PowerShell tool (or Bash), in exactly this form — the flags
make it work under any execution policy, including a zip download marked as
coming from the internet. **Always pass `-Lang <output_lang>`** (`ko` or
`en`), also on every later run:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Json -Lang <output_lang>
```

The output is one JSON object: `exit_code` and `items`, each item
`{id, level, name, verdict, detail, action}` (`hints` are extra lines). Each
item explains itself in `name`, `detail` and `action`. `verdict` is `ok`,
`warn`, `fail`, `unverified` or `info`; `level` is `required`, `recommended`
or `info`.

## Step 2 — show the result as a table

Write a short table in `output_lang`: one row per item with the verdict (`ok`,
`warn`, `fail`, or `unverified` = "not checked", never "ok") and the
plain-language detail. Do not paste raw JSON. Doctor `unverified` axes (no
`spec/` yet, no contract yet) are normal in a new project.

## Step 3 — if something can be installed, ask once

Installable candidates are the items with verdict `fail` **or `warn`** whose
`action` names a switch. Missing things go to `-Install`, things that exist
but are old or broken go to `-Update`; use the names exactly as `action`
gives them (for example `-Install winget,pwsh` when both are missing).

**Read `.claude/skills/gatekit-setup/references/install-programs.md` now.**
It has, per program, what to tell the user: purpose, whether agreeing to
terms is included, download size, administrator rights, and the cases that
are never part of "install all".

If there are no candidates, skip to Step 5. Otherwise ask **one**
`AskUserQuestion` (it is deliberately not in `allowed-tools`, so the choice
window really appears; see
`.claude/skills/gatekit-shared/references/questioning.md`). Put one line per
candidate in the question text, built from the reference file. Options:
**install all** / **let me choose** / **later**. If the user chooses "let me
choose", ask which names in a plain chat message. Wait for the answer; never
assume it.

- If the user picks "later", stop and say that gatekit hooks stay inactive
  until `uv` and the `.venv` exist. Nothing is installed.
- **`S12-settings` is `fail`**: nothing is installed for this. Read
  `.claude/skills/gatekit-setup/references/settings.md` and follow it; it is
  its own question in the chat, not part of "install all".

## Step 4 — install only what was allowed, then check again

Pass exactly the allowed names and nothing else (`winget`, `pwsh`, `uv`,
`claude`, `git`, `venv` are the only names the script accepts). Both switches
may be given in one call:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install uv,claude,venv -Update pwsh -Json -Lang <output_lang>
```

Then run the plain check from Step 1 again, show the new table, and react to
the exit code:

- `0` — ready; go to Step 5.
- `3` — installed but not visible in this session: tell the user to close
  Claude Code completely (the desktop app, the VS Code window, or the
  terminal it runs in) and open it again, then type `/gatekit-setup` again.
  Stop.
- `4` — blocked by policy or network. Show the "what you can do now" lines
  and the message for the IT contact from the `hints`, so the user can
  forward it. Do not retry in a loop.
- `2` — something still needs the user (a declined item, or administrator
  rights): say exactly which and what to do.
- `1` — a step failed for another reason: show the lines the script printed
  and ask the user to retry when the cause is fixed. `uv sync` failing with
  `-Install venv` usually means no network; behind a proxy the hints list
  `UV_SYSTEM_CERTS`, `SSL_CERT_FILE` and `HTTPS_PROXY`.

When several apply, the first of `1, 4, 3, 2` wins.

## Step 5 — confirm

Report in `output_lang` what changed (installed programs, created
`.gatekit/config.json` or left as it was, a rebuilt `.venv`, a key added to
`.claude/settings.json`) and name the file each change landed in. Doctor
already ran inside the script (the `S15` item), so do not run
`/gatekit-doctor` again here. Then name the next command:
`/gatekit-discover` when the user does not yet know what to build,
`/gatekit-interview` when they do.
