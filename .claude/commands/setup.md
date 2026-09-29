---
name: setup
description: Initialize .gatekit/config.json and check worker backends — verify the Claude CLI, and on request explain and enable the optional sandboxed Codex backend after the user confirms.
argument-hint: "[optional: codex]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:setup

Input: `$ARGUMENTS` — `codex` to set up the optional Codex backend. Empty means
the default setup.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md`. Step 5 asks the user a
   question, so read `${CLAUDE_PLUGIN_ROOT}/policy/questioning.md` too.
2. Detect the language:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

Call it `output_lang` and write every user-facing string in it. If `spec/01-prd.md`
exists, detect from its first 40 lines instead.

## Step 1 — initialize config

If `.gatekit/config.json` does not exist, create it with the defaults:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-default claude
```

`config.save` writes the full default document, so this one call both creates
the file and leaves the default backend as `claude`. Never hand-write the file
when the CLI can produce it. If it already exists, leave it alone and say so.

## Step 2 — check the default worker

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check claude
```

Read the verdict:

- `ok` — the Claude CLI is on PATH and reported its version. Say so.
- `unverified` — the binary is there but the version probe did not answer. This
  is not a failure and not a pass. Say it is unverified, and that builds will
  still run.
- `fail` — the binary is missing. Tell the user to install the Claude CLI and
  put it on PATH. Do not offer to install it for them, and do not work around it
  by enabling a bypass flag.

## Step 3 — the default setup ends here

Show the backend table and stop:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list
```

Continue to Step 4 only when `$ARGUMENTS` is `codex`.

## Step 4 — Codex: check first

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check codex
```

If this is `fail`, the Codex CLI is not installed. Say so and stop; there is
nothing to enable.

## Step 5 — Codex: explain, then ask

Codex is disabled by default and stays that way until the user says otherwise.
Before asking, tell them plainly, in `output_lang`, what enabling it does:

- gatekit will run `codex exec --sandbox workspace-write` as a worker backend.
- `workspace-write` lets it edit files in the project workspace and nothing
  outside it. The sandbox stays on.
- gatekit will not pass a bypass flag. A backend whose argv contains a bypass,
  dangerous or yolo switch is refused unless its config entry sets
  `"unsafe": true`, and gatekit never sets that for the user.
- Enabling only makes the backend available. It does not become the default
  unless they also ask for that.
- It is reversible: set `enabled` back to `false` in `.gatekit/config.json`.

Then ask for confirmation with `AskUserQuestion`, in `output_lang`, one question
with two options: enable Codex, or leave it disabled. **Do not enable anything
before the answer comes back.** If they decline, say nothing changed and stop.

## Step 6 — Codex: enable

Only after an explicit yes:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers enable codex
```

Then ask, again with `AskUserQuestion`, whether Codex should also become the
default backend for new jobs. Only on yes:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-default codex
```

## Step 7 — confirm

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor
```

Show the backend table and the doctor's worker axis. Report what changed in
`output_lang`, and name the config file the change landed in.
