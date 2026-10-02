---
name: gatekit-build
description: Build the tasks in spec/04-tasks.md behind the gates — hand each task to a subagent with a written brief and its gates (a single task is done here), let the gates decide pass or fail, and hand off to verify. Korean triggers — "이제 만들자", "만들기 시작하자", "빌드 시작해줘", "작업 실행해줘", "워커 돌려줘", "태스크 자동으로 만들어줘". English triggers — "start making it", "go ahead and build", "build it", "run the tasks", "start the workers", "execute the task list". Call it even when the spec or task file is missing — the skill names the step to do first. NOT for judging whether the result is done — that is /gatekit-verify.
argument-hint: "[optional: task ids to build, comma-separated]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell, Agent
---

# /gatekit-build

Input: `$ARGUMENTS` — optional comma-separated task ids. Empty means every task.

**Subagents do the building; a task that is alone in its round you build
yourself.** You set the standard and the brief in files before anything is
built: each task's gates and the approved completion criteria are the
standard, and `jobs start` writes one brief per task (`prompt.md`). Whoever
builds a task reads that file, does the work and checks it against the
standard by running the task's gates. **The gates decide, never a report**,
yours or a subagent's.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the spec**.
2. Read `.claude/skills/gatekit-shared/references/verification.md`.

## Step 1 — check the standard (both must hold)

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

## Step 2 — tell the user what is about to run

**Read `.claude/skills/gatekit-build/references/build-notice.md` and follow
it**: before any job starts, say once how many tasks and rounds, who builds
them, that it takes time and usage, and how a stopped build continues.
The notice is not a question: say it and go on to Step 3 in the same turn.
If an earlier job still has tasks not `passed`, continue it as that file says.

## Step 3 — start the job

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs start
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks.

The command starts nothing. It runs every task's gates once (ADR-0009),
writes each task's brief, and prints one row per task; record the job id.
`build-notice.md` explains the rows, a `warn:` line and exit 4 — never pass
`--no-preflight` to get past one.

After the table it prints one block for **every task that is to be handed
out**, and none for a task that is alone in its round:

````
hand off <task id> (round <n>):
Read .gatekit/jobs/<job id>/tasks/<task id>/prompt.md and do that task. Reply with one line.

```gatekit-scope
{"write_scope": ["<the task's write scope>"], "stop_when": "jobs complete <task id> prints passed", "tools": "inherit"}
```
````

The text under the `hand off` line is the prompt for that task's subagent.
The round order is also in the `plan` list of `job.json`: a row with
`parallel_candidate` true is handed out.

## Step 4 — build, round by round

Work the rounds in order. Do not begin a round while a task of an earlier
round is not `passed`. Who builds a task is this one rule, not a choice:

- **One task in the round — you build it.** Read its `prompt.md` and follow
  it as written (what to read first, the write scope, the tools), then
  record the verdict:

  ```
  uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs complete <task_id>
  ```

- **Two or more tasks in the round — hand every one out.** One `Agent` call
  per task, all of them in a single message so they run together. The prompt
  of each call is the printed text for that task, **passed on exactly as
  printed**: do not rewrite it, shorten it or add the brief's content to it.
  Name the call with the task id. The fence in the text is what the spawn
  gate reads; if the gate denies a call, its message says why and what to do.
  **Wait for the round inside this turn**: do not send the calls to the
  background (where the `Agent` tool has a `run_in_background` option, set
  it to false). A turn that ends while subagents still work makes the Stop
  gate judge a half-built project.

The brief is the hand-over. If you know a file the subagent should read and
the brief does not list it, add the path under `## Read first` in that
task's `prompt.md` **before** you hand the task out. Say nothing extra in
the prompt.

A subagent runs `jobs complete` for its own task and answers with one line.
When every subagent of the round has answered, go to Step 5 before the next
round. Never mark a task done yourself.

## Step 5 — read the record, not the answers

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs results --compact
```

It prints `id state gates_passed/total`, one line per task. This is the
result of the round. A subagent's line saying `passed` is not: only a task
the record shows `passed` is passed. Do not read a subagent's transcript or
its files into this conversation. Read a task's `gates.json` only when you
need the failing gate's name and output.

A handed-out task that is still `queued` after its subagent answered was
never judged: run `jobs complete <task_id>` for it yourself, which runs its
gates on what was written. For the full table, `jobs status`. To end a job
early, `jobs stop`: every task that is not finished becomes `stopped` and
the job is closed.

## Step 6 — route failures

If every task passed, skip this step. For a `failed` task, or one a
subagent returned as `blocked`,
**read `.claude/skills/gatekit-build/references/build-failures.md` and follow it**: it
covers how to tell a wrong gate from wrong code, `jobs recheck` for a gate
edit (never a new job, never a second hand-over), fixing a returned task
yourself, and what to do when a task is out of retries (exit 3: diagnose in
`spec/RECOVERY.md`, stop the pipeline).

**Never edit these by hand: `.gatekit/approvals.json`,
`.gatekit/contract.json`, the gate code and scripts under `.claude/`, and
the `hooks` in `.claude/settings.json`.** They hold what the user approved;
changing one passes nothing, it removes the check. The Stop gate reads the
approval and `spec/05-gate.md` itself, so a build whose criteria or contract
were edited after approval is refused when it tries to end. When a criterion
does not pass there are two ways forward: fix the code, or, if the criterion
is wrong, return to `/gatekit-gate` and have the user approve it again.

## Step 7 — update progress

When no task is `queued` any more, update `spec/PROGRESS.md` in `output_lang`.
If the file does not exist, copy
`.claude/skills/gatekit-build/assets/PROGRESS.md` first,
filling its YAML frontmatter block (`title`/`date`/`status`) along with the
rest of the placeholders. **Keep the template's headings exactly** — `spec
validate` rejects a heading from the other language. Under them record: the
job id and whether the build is done; one line per task (id, final state,
gates passed of total); every task that failed before it passed, with the
gate that failed and what changed; tasks that did not pass, with the failing
gate named; the timestamp.

Then run `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` and fix
any PROGRESS.md finding before reporting. Report the same table in chat, with
verdicts as they are: a `stopped` task is not a pass, and a task whose gates
never ran is `unverified`, not done.

## Step 8 — hand off

Read `.claude/skills/gatekit-shared/references/handoff.md` and follow it.
Form: plain chat. Next: `/gatekit-verify`, only when every task is `passed` —
a passing build is not a passing completion contract; only verify reports that,
against the criteria the user approved. If any task did not pass, say so
plainly and do not hand off.
