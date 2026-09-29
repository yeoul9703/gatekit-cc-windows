---
name: setup
description: Prepare gatekit on Windows — check uv, build the .venv from uv.lock, initialize .gatekit/config.json, check the Claude worker backend and run doctor.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit:setup

Input: `$ARGUMENTS` — unused; reserved for future backend configuration.

gatekit needs exactly two programs: Claude Code and **uv**. uv downloads the
Python it needs by itself; nothing else has to be installed. The work is done by
one script, `.claude/gatekit/scripts/setup.ps1`; this command runs it and
explains the result.

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

## Step 1 — run setup.ps1

Run it with the PowerShell tool (or Bash), exactly in this form — the flags make
it work under any execution policy, including a zip download marked as coming
from the internet:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1
```

The script prints one line per step, each tagged `[ok]`, `[warn]`, `[fail]` or
`[info]`:

1. uv is installed
2. `uv sync --frozen` builds `.claude/gatekit/.venv` from `uv.lock`
3. `.gatekit/config.json` is created if missing (default worker `claude`); an
   existing file is left alone
4. the `claude` CLI is on PATH
5. if the project root has a `package.json`, Node and npm are shown for
   information only — gatekit itself does not need Node; npm is for the user's
   own project gates
6. doctor runs

Exit code `0` means ready, `1` means a step failed, `2` means uv is missing.

## Step 2 — if uv is missing (exit code 2)

The script only prints the install commands; it installs nothing:

```
winget install --id=astral-sh.uv -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Show both to the user, say what each one does (installs the uv program for the
current user), and **ask for permission first. Run an install command only after
the user has agreed**, then tell the user to open a new terminal (so PATH picks
uv up) and run Step 1 again. If the user declines, stop here and say that gatekit
hooks stay inactive without uv.

## Step 3 — read the result

- `[fail]` on `uv sync` — usually no network on the first run (uv fetches Python).
  Show the lines the script printed and ask the user to retry when online.
- `[warn]` on the claude CLI — workers cannot start. Tell the user to install the
  Claude Code CLI and put it on PATH. Do not offer to install it for them, and do
  not work around it by enabling a bypass flag.
- Doctor: `unverified` axes (no `spec/` yet, no contract yet) are normal in a new
  project. Say "not checked", never "ok". Follow `verification.md`.

To look at the worker backends in more detail:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers check claude
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers list
```

`workers check` verdicts: `ok` — the CLI answered its version probe;
`unverified` — the binary is there but the probe did not answer (not a failure,
not a pass; builds will still run); `fail` — the binary is missing.

## Step 4 — confirm

Report in `output_lang` what changed (for example "created `.gatekit/config.json`"
or "left it as it was") and name the config file the change landed in.

A project that wants an additional worker backend can add one to
`.gatekit/config.json`'s `worker.backends` by hand (see `docs/USAGE.md`), then
enable it with `workers enable <name>`.
