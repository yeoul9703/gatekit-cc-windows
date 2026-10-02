# What to tell the user before a build, and how a stopped build continues

Read this at Step 2 of `/gatekit-build`, before `jobs start`, and again
when a session opens on a build that was interrupted. The user may be new to
this: a build is the first step that runs for a long time without asking
anything, so say once what is about to happen.

## The notice — one short message, in `output_lang`

Collect the facts first. Every number comes from these two sources; give no
estimate of minutes, tokens or cost, because nothing here measures them.

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs shape
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks. It prints
`tasks N · rounds N  (serial N)` and then one line per round,
`round <i> (<count>): <task ids>`. A line about dependency links with no
evidence may follow; that is `/gatekit-tasks`' business — mention it only if
the user asks why there are so many rounds.

From `.gatekit/config.json`, under `build`: `max_retries` (2 when the file
or the key is absent).

Then tell the user, in plain words:

1. **How much**: the task count and the round count from `jobs shape`.
   Rounds run one after another; tasks inside a round do not depend on each
   other.
2. **Who builds**: a round with two or more tasks is handed out, one
   subagent per task, working at the same time; a round with a single task
   this session builds itself. Each task is built from a written brief, and
   its gates judge it either way.
3. **It can take long and it uses the plan's usage.** More tasks and more
   rounds mean more of both. Say this without a number.
4. **A failed task can be tried again, up to `max_retries` times**; after
   that the command refuses it, and the build stops on that task for a
   diagnosis instead of trying again.
5. **If it stops halfway, nothing is lost**: each task's result is saved
   under `.gatekit/jobs/`, and typing `/gatekit-build` again continues from
   the tasks that have not passed.

Do not ask a question here; the user already asked for the build. If they
answer the notice with "not now", stop — no job has been started yet.

## What `jobs start` prints

`job <id>  verdict=<ok|fail|unverified>`, then one row per
task: id, state, gates passed of total, detail, and `(N consecutive)` when
the task has failed before in earlier jobs.

Before the job starts, the command runs every task's gates once:

- Gates that already pass record the task `passed` with the detail `gates
  passed at preflight; nothing left to implement`.
- A `warn:` line after the table is a preflight warning. `warn: gate passed
  before any work existed in the write scope` means that gate can pass on an
  empty tree — tell the user. `warn: gate ... failed at preflight ... in a way
  that may be the command rather than the work; starting anyway` means the
  gate's own command looks wrong: say so, and check it before blaming the code.
- A gate whose *command* is broken ends the start with exit 4 and names the
  task and the gate. Fix it in `spec/04-tasks.md` (usually a glob instead of
  a directory) and start again; never pass `--no-preflight` to get past it.

Every waiting task reads `queued` with the detail `awaiting the host
session`, and the round order is in the `plan` list of
`.gatekit/jobs/<job id>/job.json` (`id`, `round`, `parallel_candidate`).
Each task's brief is `.gatekit/jobs/<job id>/tasks/<task id>/prompt.md`:
the instruction, what to read first, the write scope, the gates and how to
run them, the tools, and the one line to answer with.

After the table and the warnings comes one block for every task whose round
holds two or more tasks (`parallel_candidate` true): a `hand off <task id>
(round <n>):` line, then the text to give that task's subagent, which is one
line pointing at the brief and a `gatekit-scope` fence with the task's write
scope. A task that is alone in its round gets no block: this session builds
it. The text is printed by `jobs start` only and is not saved; `jobs status`
does not print it.

Exit codes: `0` nothing failed, `1` a task is `failed` or `stopped`, `2`
bad arguments or no tasks, `3` a task is out of retries, `4`
a gate command is broken.

## Continuing a build that was interrupted

A usage limit, a closed window or a crash ends the session, not the record.
There is no resume command; continue with the ones below. After Step 1's
preconditions hold again:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs status
```

It shows the newest job. Tell the user which tasks are `passed` and which
are not, then:

- **Tasks still `queued`, each alone in its round**: keep the same job.
  Build the next queued task from its `prompt.md` and record it with
  `jobs complete <task_id>`. A task that was half written when the session
  ended is simply finished and completed the same way; the gates decide.
- **Two or more tasks of one round still not `passed`** (the `round` of each
  task is in the `plan` list of `job.json`): they are handed out, and the
  text to hand them out with was printed by the `jobs start` of the session
  that ended. Close the old job with `jobs stop` and start a new one for
  what is left, as below; it prints the text again.
- **A job that will not be finished** (the task list changed, the user
  wants only some of the tasks, or tasks have to be handed out again): run
  `jobs stop` once so the old job is
  closed and no longer named as the live build, then start a new job for
  what is left:

  ```
  uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs start --tasks <ids not passed>
  ```

  The new job runs every listed task's gates first, so a task whose work
  was already finished is recorded `passed` without being done again. What
  is left is then split by the same rule: a round with one task left is
  built here, a round with more is handed out with the printed text.
- **A task that `jobs start` refuses with exit 3** has used its retries.
  Follow `.claude/skills/gatekit-build/references/build-failures.md`; do
  not reach for `--force-retry` before the diagnosis is written.

`spec/PROGRESS.md` may also hold a build-state block stamped when the
conversation was compacted (between the `gatekit:build-state` markers). It
is a narrative aid; `jobs status` is the record.
