---
name: gatekit-verify
description: Verify the build against the completion contract — run the approved criteria once, hand only what a command cannot decide (how a screen looks, a check written in words) to a read-only reviewer, and report a verdict per criterion. Korean triggers — "검증해줘", "다 됐는지 확인해줘", "완료 기준 통과했는지 봐줘", "E2E 돌려줘". English triggers — "verify it", "check if it is done", "run the completion contract", "did it pass the gate". NOT for fixing what the verification finds — route failures back to /gatekit-build.
argument-hint: "[optional: criterion id to focus on]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell, Agent
---

# /gatekit-verify

Input: `$ARGUMENTS` — optional criterion id to focus the report on.

**You own this verification.** What counts as done was settled before the code
existed: the user approved `spec/05-gate.md` in `/gatekit-gate` and its hash is
pinned. So nothing here is judged by opinion. Commands decide everything a
command can decide; only what a command cannot decide — how a screen looks, a
check the gate file describes in words — goes to a read-only reviewer, and you
hand it exactly those items, not the whole job. The reviewer is a subagent
that did not see this session, which is what keeps the judgement apart from
the work (ADR-0023).

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

## Step 2 — run the contract

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract run --json
```

Run it once. Its result is the verdict for every criterion that is a command;
neither you nor the reviewer overrides it, and nobody re-runs it to get a
second opinion.

## Step 3 — hand out only what a command cannot decide

List the items that still need eyes:

- every screenshot criterion that came back `ok` (its `artifacts` entry is a
  `spec/design/build-<task-id>.png`): the image exists, whether it looks
  right is a separate fact;
- every check `spec/05-gate.md` describes in words and no criterion runs.

No such item: skip this step and say so in the report. Otherwise **read
`.claude/skills/gatekit-verify/references/evaluator-brief.md` and follow it**:
it spawns one read-only reviewer with exactly that list and holds the brief,
including the `-visual` verdict.

## Step 4 — report

Report in `output_lang`, in this order:

1. The aggregate verdict (code criteria only — see the note below on why
   this cannot include `-visual` verdicts).
2. One row per criterion: id, verdict, and for anything not `ok` the reason and
   the tail of its output. Focus on `$ARGUMENTS` if one was given, but list all.
3. One row per item the reviewer checked, or one line saying nothing needed a
   reviewer.
4. **One row per `-visual` verdict, reported with the same weight as any
   other criterion, never folded silently into the aggregate or omitted
   because the aggregate already said `ok`.**

Rules for the report:

- `unverified` stays `unverified` everywhere it appears. A criterion that timed
  out, a step nobody could run, a missing artifact that could not be checked —
  none of these are passes and none are failures.
- Never restate a worker's or the reviewer's claim of success as a verdict
  for a command criterion. The contract run decides.
- **The `contract run` aggregate (`ok`/`fail`/`unverified`) only ever counts
  code criteria — it has no way to see a `-visual` verdict, since that comes
  from the reviewer reading an image, not from running a command.** Never
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

Write the result under the **last-verification heading that already exists**
in `spec/PROGRESS.md` (`## 마지막 검증` in Korean, `## Last verification` in
English): the timestamp, the aggregate verdict, one line per criterion and one
per reviewed item. Do not add a heading in another language — `spec validate`
fails on it. If the file or the heading is missing, copy
`.claude/skills/gatekit-build/assets/<output_lang>/PROGRESS.md` first and fill
its placeholders, the YAML frontmatter included. Then run
`uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` and fix any
PROGRESS.md finding before reporting.

## Step 6 — hand off

Read `.claude/skills/gatekit-shared/references/handoff.md` and follow it.
Form: plain chat. The contract passes: there is no next skill — say the
pipeline is finished. Anything else: offer `/gatekit-build` (or stop); there
is no "more work here", because this skill never fixes what it finds.
