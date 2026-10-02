---
name: gatekit-tasks
description: Derive vertical-slice tasks from the spec into spec/04-tasks.md as gatekit-task fences, with non-overlapping write scopes and at least one gate each. Korean triggers — "작업 나눠줘", "태스크로 쪼개줘", "할 일 목록 만들어줘", "작업 분해해줘". English triggers — "break this into tasks", "split the work", "make a task list from the spec", "decompose into work items". NOT for executing the tasks — that is /gatekit-build — and NOT for writing the spec itself.
argument-hint: "[optional: constraints, e.g. 'round 1 only' or 'backend first']"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit-tasks

Input: `$ARGUMENTS` — optional constraints on scope or ordering.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the spec**.
2. Read `.claude/skills/gatekit-shared/references/verification.md`.
3. Read `.claude/skills/gatekit-shared/assets/heading-map.json` and
   `.claude/skills/gatekit-tasks/assets/04-tasks.md`.

## Step 1 — read the inputs

Read `spec/01-prd.md` (features `F<n>`, acceptance criteria, assumption
ledger), `spec/02-screens.md` if it exists (screens `S<n>`, states,
components), `spec/02-design.md` if it exists (patterns `P<n>`, components,
design tokens), and `spec/03-architecture.md` (stack, data model, naming
rules, constraints). A task instruction may cite a `P<n>` for emphasis when
its write scope touches something that pattern governs.

Then look at the actual repository: which directories exist, what the test
command is, how files are currently named. Task write scopes must point at real
paths, and gates must be commands that actually run here.

If `spec/01-prd.md` is missing, stop and tell the user to run
`/gatekit-interview` first. Do not invent requirements.

**ADR-0017 decisions 3 and 4 — two more hard stops, same shape as the one
above.** Run `spec validate --json` now (not just at Step 6) and check for
these findings before doing any planning work:

- `screens_required` — `01-prd.md` implies a UI-bearing project (no
  `[non-ui]` marker in Non-goals) and `spec/02-screens.md` does not exist.
  **Stop** and tell the user to run `/gatekit-mockup` first. Do not guess a
  screen layout here — that is mockup's job, not this command's.
- `prototype_required` — `spec/02-screens.md` exists but carries no
  `Prototype confirmed <date>` line. **Stop** and tell the user to finish
  `/gatekit-mockup`'s live-prototype revision loop (Step 7b there) and
  confirm it before tasks can be cut. A task list built against an
  unconfirmed prototype risks exactly the "기다림 끝에 엉망" outcome this
  ADR exists to prevent — the prototype is cheap to revise; a built task
  list against the wrong shape is not.

Neither stop applies to a project whose PRD carries the `[non-ui]` marker.

## Step 2 — cut vertical slices

Each task must deliver something demonstrable end to end: data, logic, and the
surface a user touches, together.

- Correct: "user can submit the form and see the saved value" — touches route,
  handler, storage, and screen.
- Wrong: "create all the database models", "set up the component library".
  Horizontal layers finish without proving anything works.

Sizing: one task is a single focused work session. A task whose instruction
needs more than a paragraph to state is two tasks.

Cover every feature `F<n>` from 01. A feature with no task is a gap; say so
rather than silently dropping it.

## Step 3 — assign write scopes and rounds

`write_scope` is a list of globs, or the string `"read-only"` for tasks that
only investigate.

Rules that `spec validate` enforces:

- ids unique across the file
- `write_scope` non-empty, or exactly `"read-only"`
- every `depends_on` id exists in this file
- **no two tasks in the same round have intersecting write scopes**
- every task has at least one gate

Assign rounds by dependency: a task goes in the first round where all its
dependencies are already done and no sibling in that round shares its files.
When two tasks want the same file, sequence them into different rounds or
re-cut them so their boundaries differ — never widen a scope to make a
collision disappear.

**Declare a `depends_on` only when this task's instruction refers to something
that task writes.** "It comes earlier in the feature list" is not a dependency.
Rounds, not the task count, are what cost time — nine tasks in one round take
the slowest, in nine rounds they take the sum — and on the ADR-0013 trial six
of ten links were unevidenced, turning three rounds into seven.

## Step 4 — write gates

**Read `.claude/skills/gatekit-tasks/references/task-gates.md` and follow it.** Every
task carries at least one gate — an argv list, run without a shell, that
fails when the task is not done — and that file covers what makes one
trustworthy (verify it runs before writing it in; a gate that always passes
manufactures false evidence), which runners need glob patterns rather than
directories, and the one gate added by default: the **token gate** when
`spec/tokens.json` exists. The **screenshot criterion** for a task that
renders a screen is not a gate written here: `/gatekit-gate` derives it, and
`task-gates.md` says what this step does to make it possible (a stable,
unique task id).

## Step 5 — show the shape, then write spec/04-tasks.md

Write the fences to a scratch copy, run `jobs shape`, and present its counts,
rounds, and unevidenced links with the round total dropping them would save. One
`AskUserQuestion` — write as shown, merge tasks, or loosen dependencies — skipped
after a stop signal.

Then fill the template, including its YAML frontmatter block (`title`/`date`/
`status`) at the top, headings verbatim from the heading map. Each task is one
` ```gatekit-task ` fence holding a single JSON object, and the instruction must
be self-contained — a worker reads only that string and its scope. Fill the
execution-order table so a human can see the rounds at a glance.

## Step 6 — validate

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate --json
```

On `fail`, fix the specific finding. Scope collisions are re-cut, never
widened. Malformed JSON is rewritten. Re-run until `ok` or `warn`.

A traceability warning about tasks missing from 05 is expected here; the next
command resolves it.

## Step 7 — report

In `output_lang`:

1. The file path written, with task count and round count on their own line.
2. The `spec validate` verdict, quoted from the run.
3. Any feature from 01 with no covering task.

Do not run any task. This command only plans them.

## Step 8 — hand off

**ADR-0017 decision 6.** Read
`.claude/skills/gatekit-shared/references/handoff.md` and follow it.

- Form: one closing `AskUserQuestion`.
- Next: `/gatekit-gate`.
- More work here: revise the task list (merge tasks, loosen dependencies,
  or add a task for an uncovered feature), then re-run Step 6.
