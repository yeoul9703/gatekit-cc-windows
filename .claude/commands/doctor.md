---
name: doctor
description: Diagnose the gatekit install across eight axes — plugin files, hook registration, project state, spec set, contract freshness, workers, python and the Codex host layer — then show the table and offer the printed fixes.
argument-hint: "[optional: --json]"
allowed-tools: Read, Glob, Grep, Bash
---

# /gatekit:doctor

Input: `$ARGUMENTS` — pass `--json` through if the user asked for machine output.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md` — the latter is what keeps
   `unverified` from being reported as a pass in Step 2.
2. Detect the language:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

Call it `output_lang`. If `spec/01-prd.md` exists, detect from its first 40 lines
instead. Axis names and verdict tokens stay in English; your prose does not.

## Step 1 — run the diagnosis

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor
```

Exit code 1 means at least one axis is `fail`. Exit code 0 does **not** mean
everything is fine — it means nothing failed, which is not the same thing when
axes came back `unverified`.

## Step 2 — show the table

Render one row per axis, in order, in `output_lang`:

| # | axis | verdict | what it means |
|---|------|---------|---------------|

The seven axes are: plugin files, hooks registered, project state, spec set,
contract freshness, workers, python.

Reading the verdicts:

- `ok` — checked, and it holds.
- `warn` — checked, works, worth knowing.
- `fail` — checked, and it is broken. This is what exit 1 reports.
- `unverified` — **not checked.** No install manifest to read, no `spec/` yet, a
  worker whose version probe went unanswered. Say "not checked" and why. Never
  round it up to `ok` or down to `fail`, and never summarize a report containing
  `unverified` axes as "all good".

State the aggregate verdict once, at the top. It is `fail` if any axis failed,
otherwise `unverified` if any axis is unverified, otherwise `warn`, otherwise
`ok`.

## Step 3 — offer the fixes

Each axis carries a `fix` string: a copy-pasteable command, or empty. For every
axis that is not `ok` and has a non-empty fix, list the command and say in one
sentence what it will change.

Common cases:

- **plugin files** fail — a gate script is missing or empty, so that gate is not
  firing at all. Reinstall the plugin.
- **hooks registered** fail — gatekit is not in the running install, so no hook
  fires regardless of what is on disk. This is the one that makes the harness
  look installed while enforcing nothing.
- **hooks registered** unverified — usually a source checkout with no install
  manifest. Expected; not a problem to fix.
- **project state** fail — `.gatekit/config.json` or `approvals.json` does not
  parse. Show the parse error; the file has to be fixed or removed by hand.
- **spec set** — route to the pipeline owning the failing file.
- **contract freshness** fail — `spec/05-gate.md` changed after the contract was
  derived, or a design input did (`02-screens.md`, `02-design.md`, or
  `tokens.json`); the detail names which file changed. Fix either case with
  `/gatekit:tasks` then `/gatekit:gate`.
- **workers** fail — the default backend's binary is not on PATH. Route to
  `/gatekit:setup`.
- **python** fail — the interpreter is below 3.9.

Ask before running any fix. **Never** run a fix that rewrites `spec/05-gate.md`,
records an approval, or enables an unsafe backend; those are the user's calls,
taken through their own commands.

## Step 4 — machine output

If `$ARGUMENTS` contains `--json`, run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor --json` and
show the JSON as-is. Do not reformat it or drop axes from it.
