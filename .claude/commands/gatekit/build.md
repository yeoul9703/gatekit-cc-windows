---
name: build
description: Run spec/04-tasks.md as worker jobs behind the gates — spawn workers per task, let the gates decide pass or fail, redelegate failures, and hand off to verify.
argument-hint: "[optional: task ids to build, comma-separated]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit:build

Input: `$ARGUMENTS` — optional comma-separated task ids. Empty means every task.

**Who writes the code depends on `build.execution` (ADR-0013).** Under
`host` **you do**, task by task, in this session — a worker is a cold
session of the same model, paying a fresh project discovery per task to buy
a second opinion from the model already here. Under `worker` workers do and
you never edit a task's files. Either way **the gates decide, never your own
report.** Hand a task to a worker only when the model must differ (adversarial
verification) or a round holds three or more independent tasks.

## Step 0 — load policy and language

1. Read `.claude/gatekit/policy/language.md` and
   `.claude/gatekit/policy/verification.md`.
2. Detect the language and call it `output_lang`:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py lang --file spec/01-prd.md --lines 40
```

Every user-facing string below is written in `output_lang`.

## Step 1 — preconditions (both must hold)

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve check spec/05-gate.md
```

- `spec validate` must not print `fail`. If it does, show the findings and
  stop; route the user to the pipeline that owns the failing file.
- `approve check` must print `ok`. `fail` means the gate file changed after
  approval, `unverified` that it was never approved — either way **stop** and
  send the user to `/gatekit:gate`. Never approve for them, and never edit
  `spec/05-gate.md` to make a hash match. A changed design input
  (`02-screens.md`, `02-design.md`, `tokens.json`) stales it the same way; the
  fix is `/gatekit:tasks` then `/gatekit:gate`.

**Only under `execution: worker`**, confirm a worker can actually answer —
under `host` there is nothing to probe:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers default
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers check <name printed above> --probe
```

`--probe` sends one trivial prompt through the backend's read-only argv — the
only check that catches a CLI that exists but cannot answer here (not logged
in, or sandboxed away from its credentials). `fail`: stop and show the detail;
the fix is to log in, or under a sandboxed host to run with escalated
permissions. `unverified` (timed out) is not a blocker; say so once and
continue.

## Step 2 — start the job

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs start
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks, `--backend <name>`
when the user asked for one. Read `max_retries` and `parallel` from
`.gatekit/config.json`; do not pass `--parallel` unless the user asked.

The command prints one row per task. Record the job id. It first runs every
task's gates once, before any worker (ADR-0009): gates that already pass
record the task `passed` with no worker (a `warn: gate passed before any
work existed` detail means that gate can pass on an empty tree — tell the
user); a gate whose *command* errors ends the start with exit 4 and names the
task and gate — fix it in `spec/04-tasks.md` (usually a glob instead of a
directory) and start again, never `--no-preflight` to get past it.

**Under `execution: host`** the job's `plan` comes back and nothing spawns.
Work it in round order (within a round, any order; `parallel_candidate` marks
one wide enough to hand to workers). Read each task's `prompt.md` — write
scope, gates, design, screens — implement it, then record the verdict with
`jobs complete <task_id>`, which runs its gates and writes the same
`status.json` a worker's exit would. Never mark a task done yourself.

## Step 3 — poll

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs status
```

**Never read `output.txt` or `stderr.txt` into context.** They hold whole worker
transcripts and will swamp the session. (Under `host` they do not exist.) Use
the status table and:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs results --compact
```

which prints `id state gates_passed/total`, one line per task. Read a task's
`gates.json` only when you need the specific failing gate's name.

Terminal states are `passed`, `failed`, `timeout`, `redelegated`, `stopped`
and `blocked`. A `blocked` task never ran because an in-job dependency did not
pass: fix the dependency, then `jobs start --tasks <id>`. To end a job early,
`jobs stop` — it ends this job's own workers only; never kill them by name.

## Step 4 — route failures

For every `failed` or `timeout` task, read the failing gate's output tail in
`gates.json` and decide **whether the code or the gate is wrong**. A gate names
files and commands that do not exist until the work is done, so narrowing one
mid-build is normal, not a mistake.

**Gate wrong** — too broad, names a path the task never had to create, or fails
the same way regardless of the code: fix `spec/04-tasks.md`, then
`jobs recheck <task_id>`, which runs the new gate against existing code in
seconds with no worker and no new job. **Never redelegate or start a job for a
gate edit** — on the trial behind ADR-0013 that was 28 of 35 spawns.

**Code wrong** — under `host`, fix it yourself and `jobs complete <task_id>`
again. Under `worker`, `jobs redelegate <task_id>`: it archives the attempt
under `attempt-N/`, appends the gate output to the prompt and re-runs; exit 3
means out of retries (`build.max_retries`) and you do not retry past it.

Consecutive failures bind across jobs by code (ADR-0014): `redelegate` and
`start` both refuse a task at `max_retries`, exit 3, naming the jobs it failed
in. On refusal, diagnose: read `spec/RECOVERY.md` and the task's `gates.json`,
write the diagnosis there under a heading naming the task (what gate fails,
what the output says, likely causes), then **stop the pipeline**. Once the
cause is fixed, `jobs start --force-retry <task_id>` clears its count — never
to route around a diagnosis you have not done.

## Step 5 — update progress

When every task is terminal, update `spec/PROGRESS.md` in `output_lang`.

If the file does not exist, copy
`.claude/gatekit/spec-kit/templates/<output_lang>/PROGRESS.md` first,
filling its YAML frontmatter block (`title`/`date`/`status`) along with the
rest of the placeholders. **Keep the template's headings exactly** — `spec
validate` rejects a heading from the other language. Under them record: the
job id, its execution mode and
backend, and whether the build is done; one line per task (id, final state,
gates passed of total); every redelegated task with the gate that failed and
what changed; tasks left blocked with the failing gate named; the timestamp.

Then run `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` and fix
any PROGRESS.md finding before reporting. Report the same table in chat, with
verdicts as they are: a `timeout` is not a pass, and a task whose gates never
ran is `unverified`, not done.

## Step 6 — hand off

If every task is `passed`, tell the user to run `/gatekit:verify` and stop.
Build passing is not the same as the completion contract passing; only
`/gatekit:verify` reports that, using an evaluator that did not write the
code. If any task is blocked, say so plainly and do not hand off.
