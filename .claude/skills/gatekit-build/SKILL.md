---
name: gatekit-build
description: Run spec/04-tasks.md as worker jobs behind the gates — spawn workers per task, let the gates decide pass or fail, redelegate failures, and hand off to verify. Korean triggers — "이제 만들자", "만들기 시작하자", "빌드 시작해줘", "작업 실행해줘", "워커 돌려줘", "태스크 자동으로 만들어줘". English triggers — "start making it", "go ahead and build", "build it", "run the tasks", "start the workers", "execute the task list". Call it even when the spec or task file is missing — the skill names the step to do first. NOT for judging whether the result is done — that is /gatekit-verify.
argument-hint: "[optional: task ids to build, comma-separated]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell, Agent
---

# /gatekit-build

Input: `$ARGUMENTS` — optional comma-separated task ids. Empty means every task.

**Who writes the code depends on `build.execution` (ADR-0013).** Under
`host` **you do**, task by task, in this session — a worker is a cold
session of the same model, paying a fresh project discovery per task to buy
a second opinion from the model already here. Under `worker` workers do and
you never edit a task's files. Either way **the gates decide, never your own
report.** Hand a task to a worker only when the model must differ (adversarial
verification) or a round holds three or more independent tasks.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the spec**.
2. Read `.claude/skills/gatekit-shared/references/verification.md`.

## Step 1 — preconditions (both must hold)

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve check spec/05-gate.md
```

- `spec validate` must not print `fail`. If it does, show the findings and
  stop; route the user to the pipeline that owns the failing file.
- `approve check` must print `ok`. `fail` means the gate file changed after
  approval, `unverified` that it was never approved — either way **stop** and
  send the user to `/gatekit-gate`. Never approve for them, and never edit
  `spec/05-gate.md` to make a hash match. A changed design input
  (`02-screens.md`, `02-design.md`, `tokens.json`) stales it the same way; the
  fix is `/gatekit-tasks` then `/gatekit-gate`.

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
permissions. `unverified` (timed out) is no blocker; say so once and continue.

## Step 1.5 — tell the user what is about to run

**Read `.claude/skills/gatekit-build/references/build-notice.md` and follow
it**: before any job starts, say once how many tasks and rounds, who writes
the code, that it takes time and usage, and how a stopped build continues.
If an earlier job still has tasks not `passed`, continue it as that file says.

## Step 2 — start the job

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs start
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks, `--backend <name>`
when the user asked for one; do not pass `--parallel` unless the user asked.

The command prints one row per task; record the job id. It first runs every
task's gates once, before any worker (ADR-0009); `build-notice.md` explains the
rows, a `warn:` line and exit 4 — never pass `--no-preflight` to get past one.

**Under `execution: host`** nothing spawns and the `plan` is in `job.json`.
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

If every task passed, skip this step. For a `failed` or `timeout` task,
**read `.claude/skills/gatekit-build/references/build-failures.md` and follow it**: it
covers how to tell a wrong gate from wrong code, `jobs recheck` for a gate
edit (never a new job), `jobs redelegate` for code, and what to do when a task
is out of retries (exit 3: diagnose in `spec/RECOVERY.md`, stop the pipeline).

## Step 5 — update progress

When every task is terminal, update `spec/PROGRESS.md` in `output_lang`.
If the file does not exist, copy
`.claude/skills/gatekit-build/assets/PROGRESS.md` first,
filling its YAML frontmatter block (`title`/`date`/`status`) along with the
rest of the placeholders. **Keep the template's headings exactly** — `spec
validate` rejects a heading from the other language. Under them record: the
job id, its execution mode and backend, and whether the build is done; one
line per task (id, final state, gates passed of total); every redelegated task
with the gate that failed and what changed; tasks left blocked with the failing
gate named; the timestamp.

Then run `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` and fix
any PROGRESS.md finding before reporting. Report the same table in chat, with
verdicts as they are: a `timeout` is not a pass, and a task whose gates never
ran is `unverified`, not done.

## Step 6 — hand off

Read `.claude/skills/gatekit-shared/references/handoff.md` and follow it.
Form: plain chat. Next: `/gatekit-verify`, only when every task is `passed` —
a passing build is not a passing completion contract; only verify reports that,
against the criteria the user approved. If any task is blocked or did
not pass, say so plainly and do not hand off.
