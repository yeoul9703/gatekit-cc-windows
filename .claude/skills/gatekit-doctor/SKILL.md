---
name: gatekit-doctor
description: Diagnose the gatekit install across eight axes — gatekit files, hook registration, project state, spec set, contract freshness, workers, python, uv — then show the table and offer the printed fixes. Read-only, for when something looks wrong in a project that is already set up. Korean triggers — "닥터 돌려줘", "설치 점검해줘", "훅이 안 먹는 것 같아", "게이트킷 상태 확인". English triggers — "run doctor", "diagnose gatekit", "why are my hooks not firing", "check the install". NOT the built-in /doctor, which checks Claude Code itself and knows nothing about gatekit. NOT for installing a missing program — that is /gatekit-setup — and NOT for fixing the spec or approving a gate file.
argument-hint: "[optional: --json]"
allowed-tools: Read, Glob, Grep, Bash, PowerShell
---

# /gatekit-doctor

Input: `$ARGUMENTS` — pass `--json` through if the user asked for machine output.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the spec** (`$ARGUMENTS` is empty or `--json`, so it
   carries no language signal). Axis names and verdict tokens stay in
   English; your prose does not.
2. Read `.claude/skills/gatekit-shared/references/verification.md` — it is what keeps
   `unverified` from being reported as a pass in Step 2.

## Step 1 — run the diagnosis

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py doctor
```

Exit code 1 means at least one axis is `fail`. Exit code 0 does **not** mean
everything is fine — it means nothing failed, which is not the same thing when
axes came back `unverified`.

## Step 2 — show the table

Render one row per axis, in order, in `output_lang`:

| # | axis | verdict | what it means |
|---|------|---------|---------------|

The eight axes are: gatekit files, hooks registered, project state, spec set,
contract freshness, workers, python, uv.

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

- **gatekit files** fail — a gate script, the launcher, a `scripts/*.ps1`,
  `pyproject.toml` or `uv.lock` is missing or empty, so that part is not working
  at all. Restore it from git.
- **hooks registered** fail — `.claude/settings.json` lacks an event, or a hook is
  not in exec form (`command` + `args`, no shell string), so a hook does not fire.
  This is the one that makes the harness look installed while enforcing nothing.
- **hooks registered** unverified — `.claude/settings.json` could not be read.
- **project state** fail — `.gatekit/config.json` or `approvals.json` does not
  parse. Show the parse error; the file has to be fixed or removed by hand.
- **spec set** — route to the pipeline owning the failing file.
- **contract freshness** fail — `spec/05-gate.md` changed after the contract was
  derived, or a design input did (`02-screens.md`, `02-design.md`, or
  `tokens.json`); the detail names which file changed. Fix either case with
  `/gatekit-tasks` then `/gatekit-gate`.
- **workers** fail — the default backend's binary is not on PATH. Route to
  `/gatekit-setup`.
- **python** fail — `.claude/gatekit/.venv` is missing (hooks are silently
  inactive) or its interpreter is below 3.14. Route to `/gatekit-setup`.
- **uv** fail — `uv` is not on PATH. Route to `/gatekit-setup`, which shows the
  install command; install it only after the user agrees.

Ask before running any fix. **Never** run a fix that rewrites `spec/05-gate.md`,
records an approval, or enables an unsafe backend; those are the user's calls,
taken through their own commands.

## Step 4 — machine output

If `$ARGUMENTS` contains `--json`, run `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py doctor --json` and
show the JSON as-is. Do not reformat it or drop axes from it.

## Step 5 — hand off

Skip this after `--json`. Otherwise read
`.claude/skills/gatekit-shared/references/handoff.md` and follow it, in plain
chat. Next: the skill Step 3 routed the first axis that is not `ok` to; with
every axis `ok` there is nothing to hand off. There is no "more work here".
