# ADR-0010: A running job shows elapsed time, remaining work, and file activity

Status: **deferred** 2026-09-17 — drafted, then parked before implementation
pending a second live build. See "Why this is deferred" below.

Origin: the Tetris trial, `docs/retros/2026-09-14-tetris-trial.md` finding R13
and the owner's report from the study's first session: *"구현 시간조차도 너무
길어서 지루한데 어떤 모양인지도 모르고 말이지."*

## Why this is deferred

The evidence behind this ADR is one build, and that build was abnormal: the
gate command was wrong from the first second, so 18 of its 22 minutes were
waste that ADR-0009 has since made impossible. Nobody has yet watched a
*healthy* job run to completion.

Every ranking in the Decision section — that elapsed time is the largest gap,
that a moving filename is the signal the operator most lacks — is therefore
inference, not measurement. The repo's own rule against presenting a guess as
an observation applies to this document as much as to a spec.

The decision is to run one more real build first, watch what is actually
missing, and only then implement. If the next run shows the gaps ranked
differently, the Decision section is rewritten before any code is written
against it. The design work here is kept because it is the cheaper half; what
it lacks is evidence, not thought.

Design preview (`/gatekit:mockup`, backlog item 11) takes priority, since its
need *was* observed: a preview was produced by hand during the trial, before
any code existed, and the owner asked for it to become part of the pipeline.

## Context

A build job on the trial ran 18 minutes 22 seconds. For that whole time the
only thing the operator could see was `jobs status`, whose table prints one
line per task:

```
  core-rules               running      0/0
```

That row says a worker is alive. It does not say for how long, what it is
doing, how many tasks are left, or whether this is the first attempt or the
third. A task that has been running ninety seconds and a task that hung eight
minutes ago look identical. The operator's only recourse is to run
`jobs status` again by hand and compare two identical tables.

`/gatekit:build` step 3 forbids the obvious fix:

> **Never read `output.txt` or `stderr.txt` into context.** They hold whole
> worker transcripts and will swamp the session.

That instruction is correct and stays. But it means the main session has no
supported way to learn anything about a running worker beyond its state word.

### Why `output.txt` cannot be tailed

The first design considered was to show the tail of the live `output.txt`.
`_spawn_worker` passes the file object directly as `stdout=`, so the file does
grow while the worker runs, and a bounded tail would not swamp the session.

That does not work, for a reason in the backend contract rather than in
`jobs.py`. The default backend argv is:

```
claude -p --output-format json --permission-mode acceptEdits
```

`--output-format json` emits a **single JSON object when the worker has
finished**. Every one of the thirteen `output.txt` files the trial produced is
exactly one line, between 5 KB and 10 KB. While the worker runs the file is
empty; at the last instant it becomes 6 KB. There is no progress in it to
tail.

Switching to `--output-format stream-json` would produce line-by-line events,
but that changes the backend contract and requires its own design for
bounding what reaches the session. It is out of scope here and listed under open questions.

### What is already on disk

Everything this ADR shows is already recorded and thrown away unread:

| Recorded in `status.json` / `task.json` | Shown today |
|---|---|
| `started_at`, `elapsed_s` | no |
| `attempt` | no |
| `depends_on`, `round` | no |
| `gates_passed` / `gates_total` | after the task ends |
| `pid`, `pid_started_at` | no |
| `write_scope` (glob list) | no |

The standing constraints apply: standard library only; hooks and code are the
enforcement, not prose; `unverified` never rounds; tests first; every hook
exits 0 on internal error.

## Decision

Three additions, none of which change what a worker does, what a gate decides,
or what any verdict means. This ADR is strictly about what the operator can
see while the machine works.

### 1. `status` reports elapsed time and remaining work

`status` gains four fields per task row, all derived from what is already
written — no new collection:

| Field | Meaning |
|---|---|
| `elapsed_s` | for a task in `running` or `gating`, seconds since `started_at` computed at read time; for a terminal task, the recorded `elapsed_s` |
| `attempt` | already in `status.json`, now surfaced in the row |
| `waiting_on` | the `depends_on` ids that are not yet `passed` (empty for a runnable task) |
| `activity` | decision 3 below; absent unless the task is running |

and three at job level: `running` and `remaining` counts, and `eta_basis` —
the mean `elapsed_s` of the tasks that have already passed in this job, or
`null` while fewer than two have. `eta_basis` is a **stated mean, not a
prediction**: `status` prints it as "passed so far average 3m 12s" and never
as a countdown for the job. A projection over tasks whose content nobody has
measured would be a number the tool cannot stand behind, and the repo's rule
against presenting a guess as an observation applies to progress reporting as
much as to specs.

The table gains the elapsed column and, for a queued task, its `waiting_on`:

```
job 20260914T043841Z-0e15  backend=claude  verdict=unverified  2 running, 3 left
  core-rules               running    2m14s  0/0   attempt 1  · tetris/src/bag.js
  screens-shell            running      48s  0/0   attempt 2  · tetris/src/ui/board.js
  play-marathon            queued           0/0   waiting on core-rules (running)
  scores-persist           passed     1m03s  1/1
```

`--compact` is **unchanged**: `id state gates_passed/total`, one line per task.
`/gatekit:build` step 3 tells the main session to poll with `--compact`, and
that line is parsed by eye during a build; widening it would break the one
output this ADR's own consumer depends on. The new fields reach a program
through `--json` and a human through the default table.

### 2. `jobs status --watch [--interval N]` redraws until the job is terminal

A blocking loop that re-renders the table every `N` seconds (default 3,
minimum 1) and returns when `status()["done"]` is true, the job is stopped, or
the user interrupts. On a TTY it repaints in place; when stdout is not a TTY
it prints one block per interval so the output stays greppable in a log. Exit
code is the same as a plain `status` call on the final state, so `--watch` can
end a script.

`--watch` is for a **human at a terminal**. `/gatekit:build` must keep polling
with discrete `jobs status` / `results --compact` calls: a blocking command
inside an agent session holds the turn open and produces one enormous tool
result. The command file says so in the sentence that documents the flag.

### 3. `activity`: the most recently modified file inside the task's `write_scope`

For a task in `running`, `jobs.task_activity(root, task)` returns the path and
mtime of the most recently modified file matching the task's own
`write_scope` globs, or `None`.

This is a filesystem `stat`, not a read. The file's *contents* never enter the
session, so the `/gatekit:build` prohibition is respected exactly: the
operator learns "the worker touched `tetris/src/bag.js` eleven seconds ago",
which is the signal they actually lack, and learns nothing about what it
wrote.

Rules that keep it honest:

- **Scope is the task's own `write_scope`**, read from the job's `task.json`
  snapshot, never a walk of the repository. A task whose `write_scope` is
  `"read-only"` or empty always reports `None`.
- **Only files modified after the task's `started_at`** count. A file the
  previous job wrote is not this worker's activity.
- **Bounded cost.** The scan is `glob` over the declared patterns with a cap
  of `ACTIVITY_MAX_FILES` (2000) stat calls per task per refresh; past the cap
  it returns what it found and sets `"truncated": true`. A `**` over a large
  tree must not make `status` slow enough that the operator stops running it.
- **Absent is not idle.** `None` renders as nothing at all, never as "idle" or
  "stuck". A worker that is thinking, reading, or running a test has no file
  activity and is working normally. Rendering silence as a problem would be
  exactly the kind of inference the repo forbids.
- **Never a verdict.** `activity` appears in no aggregate, gates nothing, and
  changes no state. A task with recent file activity and a failing gate is
  `failed`.

### 4. Command text

`plugin/commands/build.md` gains: the elapsed and `waiting_on` columns in
step 3, `--watch` described as the operator's view with the reason the agent
must not use it, and one sentence that `activity` is a filename and mtime and
that its absence means nothing. `docs/manual/08-cli.md` documents the flags.

`build.md` is at its 160-line limit, so this lands by replacing prose in
step 3, not by appending.

## Consequences

**What the operator gets.** On the trial's own numbers: during the 18-minute
job, a per-task elapsed clock next to a moving filename, the count of tasks
left, and which queued task was waiting on which failing dependency. The
`play-marathon` task that started the same second `core-rules` failed would
have shown `waiting on core-rules (failed)` instead of `running` — the bug
ADR-0009 fixed would have been *visible* as well as prevented.

**What it does not give.** No insight into the worker's reasoning, no progress
percentage within a task, and no completion estimate. A task that hangs still
looks like a task that is thinking, except that its `activity` mtime stops
advancing — a hint, deliberately not a verdict, because a long silent stretch
is normal.

**Costs.** `status` does filesystem work it did not do before: one `glob` plus
stats per running task, capped. `--watch` adds a blocking code path that must
be tested without a real job. Three new fields appear in `status()`'s return
value, which `/gatekit:build`, `/gatekit:verify` and `spec/PROGRESS.md`
consumers all read — hence the rule that `--compact` does not change.

**Contract changes** (`docs/ARCHITECTURE.md`): §10 gains the new `status`
fields, `--watch`, and the `activity` rules; §14 gains `task_activity` and the
`watch` signature. §13 lists the new tests: elapsed for running vs terminal
tasks, `waiting_on` derivation, `eta_basis` null below two samples, activity
inside and outside `write_scope`, activity older than `started_at` ignored,
the file cap, `read-only` scope, `--watch` terminating on `done`, `--compact`
unchanged, and exit-0-on-internal-error for every new path.

## Rejected alternatives

- **Tail `output.txt`.** The default backend writes one JSON object at exit;
  there is no progress in the file to tail. See Context.
- **Switch the backend to `--output-format stream-json`.** Changes the backend
  contract and needs its own design for bounding what reaches the session. Deferred, not rejected on merit.
- **Let `--compact` carry the new columns.** `/gatekit:build` polls with it
  during a build; changing that line breaks the consumer this ADR exists to
  serve.
- **Show a percentage or ETA per job.** Requires per-task duration estimates
  nobody has measured. `eta_basis` states the mean of what already finished
  and refuses to extrapolate.
- **Have the worker report its own progress.** Self-reported progress is the
  same class of evidence as a worker's claim of success, which §10 already
  refuses to let decide a verdict.
- **A daemon or log file that tails workers.** More moving parts than the
  problem justifies; everything needed is already in `status.json` and the
  filesystem.

## Open questions

- Whether `stream-json` should become the `claude` backend's argv. It would make real in-task progress possible and
  would supersede decision 3's mtime heuristic for that backend.
- Whether `activity` should show a count of files touched since
  `started_at` rather than only the most recent one. One filename is the
  smallest thing that answers "is it moving"; a count may read better for a
  task with a wide `write_scope`.
- Whether `--watch` belongs on `results` too, or whether one watch surface is
  enough.
