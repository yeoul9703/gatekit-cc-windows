---
name: setup
description: Initialize .gatekit/config.json and check the Claude worker backend.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:setup

Input: `$ARGUMENTS` — unused; reserved for future backend configuration.

## Step 0 — load policy and language

1. Read `.claude/gatekit/policy/language.md`.
2. Detect the language:

```
".claude/gatekit/bin/gatekit" lang "$ARGUMENTS"
```

Call it `output_lang` and write every user-facing string in it. If `spec/01-prd.md`
exists, detect from its first 40 lines instead.

## Step 1 — initialize config

If `.gatekit/config.json` does not exist, create it with the defaults:

```
".claude/gatekit/bin/gatekit" workers set-default claude
```

`config.save` writes the full default document, so this one call both creates
the file and leaves the default backend as `claude`. Never hand-write the file
when the CLI can produce it. If it already exists, leave it alone and say so.

## Step 2 — check the default worker

```
".claude/gatekit/bin/gatekit" workers check claude
```

Read the verdict:

- `ok` — the Claude CLI is on PATH and reported its version. Say so.
- `unverified` — the binary is there but the version probe did not answer. This
  is not a failure and not a pass. Say it is unverified, and that builds will
  still run.
- `fail` — the binary is missing. Tell the user to install the Claude CLI and
  put it on PATH. Do not offer to install it for them, and do not work around it
  by enabling a bypass flag.

## Step 3 — confirm

```
".claude/gatekit/bin/gatekit" workers list
".claude/gatekit/bin/gatekit" doctor
```

Show the backend table and the doctor's worker axis. Report what changed in
`output_lang`, and name the config file the change landed in.

A project that wants an additional worker backend can add one to
`.gatekit/config.json`'s `worker.backends` by hand (see `docs/USAGE.md`), then
enable it with `workers enable <name>`.
