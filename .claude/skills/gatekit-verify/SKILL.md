---
name: gatekit-verify
description: Verify the build against the completion contract with an independent evaluator — a read-only agent runs the criteria and the E2E steps, then the main session re-runs the contract and reports per-criterion verdicts. Korean triggers — "검증해줘", "다 됐는지 확인해줘", "완료 기준 통과했는지 봐줘", "E2E 돌려줘". English triggers — "verify it", "check if it is done", "run the completion contract", "did it pass the gate". NOT for fixing what the verification finds — route failures back to /gatekit-build.
argument-hint: "[optional: criterion id to focus on]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell, Agent
---

# /gatekit-verify

Input: `$ARGUMENTS` — optional criterion id to focus the report on.

**Producer ≠ evaluator.** The session that built the code does not get to grade
it. This command spawns a separate evaluator agent that may read and run but not
write, and only then reports. Do not shortcut it by running the checks yourself
and calling that verification.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the spec**.
2. Read `.claude/skills/gatekit-shared/references/verification.md`.

## Step 1 — preconditions

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract derive
```

Re-derive first: the contract must match the current `spec/05-gate.md`, or every
run comes back `unverified` with `contract_stale`. If `spec/05-gate.md` is
missing, stop and route the user to `/gatekit-gate`. The contract can also go
stale because a design input changed (`02-screens.md`, `02-design.md`, or
`tokens.json`); `contract status` names which file changed. The fix is the
same either way: `/gatekit-tasks` then `/gatekit-gate`.

## Step 2 — run the evaluator

**Read `.claude/skills/gatekit-verify/references/evaluator-brief.md` and follow it.**
It resolves who grades (`workers list --json`'s `evaluator` field), launches
that backend or a read-only subagent, and holds the brief itself — run the
contract, carry out every E2E step in `spec/05-gate.md` by hand, one verdict
each from `ok / warn / fail / unverified`, plus the `-visual` judgement on
every screenshot criterion.

One thing the command must surface rather than swallow: an `evaluator_warning`
means the producer is grading itself — **report it to the user** (there is no
second backend enabled to grade instead, unless the user configures one).

## Step 3 — re-run the contract yourself

After the evaluator returns:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract run --json
```

Run it once, in the main session. Two independent runs that disagree is itself a
finding — report the disagreement rather than picking the better result.

## Step 4 — report

Report in `output_lang`, in this order:

1. The aggregate verdict (code criteria only — see the note below on why
   this cannot include `-visual` verdicts).
2. One row per criterion: id, verdict, and for anything not `ok` the reason and
   the tail of its output. Focus on `$ARGUMENTS` if one was given, but list all.
3. One row per E2E step from the evaluator.
4. **One row per `-visual` verdict, reported with the same weight as any
   other criterion, never folded silently into the aggregate or omitted
   because the aggregate already said `ok`.**
5. Any disagreement between the evaluator's run and yours.

Rules for the report:

- `unverified` stays `unverified` everywhere it appears. A criterion that timed
  out, a step nobody could run, a missing artifact that could not be checked —
  none of these are passes and none are failures.
- Never restate a worker's or the evaluator's claim of success as a verdict. The
  contract run decides.
- **The `contract run` aggregate (`ok`/`fail`/`unverified`) only ever counts
  code criteria — it has no way to see a `-visual` verdict, since that comes
  from the evaluator reading an image, not from running a command.** Never
  report "the contract passes" on the strength of the aggregate alone while
  any `-visual` verdict reads `fail`. Check both: if the aggregate is `ok`
  **and** every `-visual` verdict is `ok` or `unverified` (never `fail`),
  say the contract passes and name the commit or the working tree it passed
  against. If the aggregate is `ok` but a `-visual` verdict is `fail`, say
  so explicitly and plainly — do not let a clean aggregate imply the build
  is done when a screenshot criterion's own visual judgement says otherwise.
- If the aggregate is anything else, or any `-visual` verdict is `fail`,
  list what would have to change, and stop. Do not fix the code here; route
  failures back through `/gatekit-build`.

## Step 5 — leave the trail

Confirm `spec/PROGRESS.md` carries the evaluator's result under the
last-verification heading for `output_lang`. If the evaluator could not write
it, write it yourself from its reply and say that you did. Then run
`uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` and fix any
PROGRESS.md finding before reporting.
