---
name: gate
description: Derive executable completion criteria into spec/05-gate.md, show them for approval, and on approval pin the hash so the build gate opens.
argument-hint: "[optional: extra criteria to include]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit:gate

Input: `$ARGUMENTS` — optional additional criteria the user wants enforced.

## Step 0 — load policy and language

1. Read `.claude/gatekit/policy/language.md` and
   `.claude/gatekit/policy/verification.md`.
2. Detect the language:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py lang --file spec/01-prd.md --lines 40
```

Call it `output_lang`.

3. Read `.claude/gatekit/spec-kit/heading-map.json` and
   `.claude/gatekit/spec-kit/templates/<output_lang>/05-gate.md`.

## Step 1 — read the inputs

Read the acceptance criteria in `spec/01-prd.md` and every task in
`spec/04-tasks.md`. Both files must exist; if `04-tasks.md` is missing, stop and
send the user to `/gatekit:tasks`.

## Step 2 — derive criteria

When writing `spec/05-gate.md`, fill its YAML frontmatter block (`title`/
`date`/`status`) at the top along with the rest of the template.

One criterion per acceptance criterion in 01, plus one per task in 04 whose
completion is not already covered. Each is a ` ```gatekit-criterion ` fence:

```json
{"id": "task-one-works", "argv": ["python3", "-m", "unittest", "discover", "-k", "task_one"],
 "expect": {"exit": 0}, "timeout_s": 30, "artifacts": []}
```

Requirements:

- `id` unique, and containing the task id it verifies so traceability holds
- `argv` a non-empty list of strings, run without a shell — no `&&`, no pipes,
  no redirection. Chain steps by adding more criteria instead.
- `timeout_s` realistic. The run-wide budget defaults to 45 seconds; if the
  criteria together need more, add one `gatekit-budget` fence declaring
  `total_budget_s` (ceiling 600). Measure first, then declare — never raise a
  budget to hide a slow test you have not looked at
- `artifacts` only for files the command genuinely produces. A declared
  artifact that does not appear is a `fail`, so do not declare aspirational ones.
- `expect` beyond `exit` when the exit code alone can lie. A test runner that
  reports skips still exits 0, so pin it: `"expect": {"exit": 0,
  "stdout_not_contains": ["skipped", "SKIP"]}`. `stdout_contains`,
  `stdout_regex` and the `stderr_*` forms exist too; every unknown key is a
  derive error, so spell them exactly.

**The screenshot criterion (ADR-0017 decision 9).** For every task in 04
whose `write_scope` touched a UI surface, add one more criterion whose
`argv` runs the project's E2E runner (`npx playwright test` unless
`spec/03-architecture.md` names a different one already in use) against a
spec that navigates to the task's screen and saves
`spec/design/build-<task-id>.png`, and whose `artifacts` names that same
path:

```json
{"id": "task-one-screenshot", "argv": ["npx", "playwright", "test", "e2e/screenshot-task-one.spec.ts"],
 "expect": {"exit": 0}, "timeout_s": 30, "artifacts": ["spec/design/build-task-one.png"]}
```

Write the actual Playwright spec file this `argv` runs — like every other
criterion it must be runnable here right now, not a guess. If the project
has no E2E runner at all, that setup is the task's own responsibility; do
not derive a criterion whose `argv` cannot run yet. **Never substitute an
MCP browser tool call for the `argv`** — `contract.py` runs criteria with
`subprocess.run`, and `mcp__*` tools exist only inside an agent session. On
a host with no browser the `argv` fails to launch and `contract.py` reports
`unverified`, never a fabricated pass; that is the correct outcome.

Every criterion must be **runnable in this repository right now**. Run each
one before writing it in — an unexecuted criterion is a guess, and the Stop
hook will run it for real. Read the output, not only the exit code:
`node --test <directory>` and `gates/tokens.py <directory>` both "run" and
both are wrong (the first loads the directory as a module, the second scans
zero files and exits 3). Use glob patterns (`tests/rules/*.test.js`).

## Step 3 — write the "not counted as done" section

This section is the point of the file. Write the conditions that make a
plausible-looking pass invalid, at minimum:

- tests passing because they were skipped, disabled, or narrowed — and where
  the runner prints skips, make that a criterion with `stdout_not_contains`
  rather than only a sentence here
- a criterion that timed out, which is `unverified` and never a pass
- a command exiting 0 with its declared artifact absent
- a UI task's screenshot criterion coming back `unverified` (no browser, no
  E2E runner) being reported as if the screen were confirmed working — it
  means nobody, human or evaluator, has actually looked at it yet
- **a feature whose own tests pass while nothing on a real screen reaches
  it.** A real trial shipped three features this way: each had passing
  tests and none was wired into the page. So for a UI-bearing project,
  cover the wiring itself with at least one criterion that drives the app
  end to end — open the screen, act on it, assert the result — rather than
  trusting per-feature tests to imply it
- TODOs, stubs, or empty implementations left behind
- editing this file to remove a failing criterion
- reporting success without having run anything

Add project-specific ones from the constraints in `spec/03-architecture.md`.

## Step 4 — validate and derive the contract

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate --json
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract derive
```

`spec validate` must not be `fail` before you continue. `contract derive` writes `.gatekit/contract.json` with the source hash of `05-gate.md`.

## Step 5 — show the criteria

Present every criterion to the user in `output_lang`, as a table: id, what it
proves, the exact command. Then state plainly what approval changes:

> Approving pins the hash of this file. From that point the write gate stops
> blocking edits outside `spec/`, so source files can be written. The Stop hook
> will run these commands and block completion while any of them fails or comes
> back unverified. Editing this file afterwards expires the approval.

## Step 6 — approve

One `AskUserQuestion` in `output_lang`, with options: approve as written,
revise a named criterion, or add a criterion. On revise or add, apply the
change, re-run Step 4, and ask again.

On approve:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve spec/05-gate.md
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve check spec/05-gate.md
```

The check must print `ok`. Never edit the file to make a hash match.

## Step 7 — report

In `output_lang`: (1) the file path and the number of criteria; (2) the
`spec validate` and `approve check` results, quoted from the runs; (3) that
the write gate now allows source edits outside `spec/`; (4) that any later
edit to `05-gate.md` expires the approval and requires re-approval plus
`contract derive`; (5) the next command, `/gatekit:build`.

If the user did not approve, say so explicitly and state that the write gate
remains closed. Do not approve on their behalf.
