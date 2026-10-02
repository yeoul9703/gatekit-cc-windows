# What to tell the user before a build, and how a stopped build continues

Read this at Step 1.5 of `/gatekit-build`, before `jobs start`, and again
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

From `.gatekit/config.json`, under `build`: `execution` (`host` when unset
or unrecognised; `--backend <name>` on `jobs start` forces `worker`),
`max_retries` and `parallel`.

Then tell the user, in plain words:

1. **How much**: the task count and the round count from `jobs shape`.
   Rounds run one after another; tasks inside a round do not depend on each
   other.
2. **Who writes the code**:
   - `host` — this session writes each task itself, one at a time, and the
     gates judge each one.
   - `worker` — a separate Claude session is started for each task, up to
     `parallel` of them at once, and the gates judge each one.
3. **It can take long and it uses the plan's usage.** More tasks and more
   rounds mean more of both; under `worker` every task is a session of its
   own. Say this without a number.
4. **A failed task can be tried again, up to `max_retries` times**; after
   that the command refuses it, and the build stops on that task for a
   diagnosis instead of trying again.
5. **If it stops halfway, nothing is lost**: each task's result is saved
   under `.gatekit/jobs/`, and typing `/gatekit-build` again continues from
   the tasks that have not passed.

Do not ask a question here; the user already asked for the build. If they
answer the notice with "not now", stop — no job has been started yet.

## What `jobs start` prints

`job <id>  backend=<name>  verdict=<ok|fail|unverified>`, then one row per
task: id, state, gates passed of total, detail, and `(N consecutive)` when
the task has failed before in earlier jobs.

Before any worker runs, the command runs every task's gates once:

- Gates that already pass record the task `passed` with the detail `gates
  passed at preflight; no worker spawned`.
- A `warn:` line after the table is a preflight warning. `warn: gate passed
  before any work existed in the write scope` means that gate can pass on an
  empty tree — tell the user.
- A gate whose *command* is broken ends the start with exit 4 and names the
  task and the gate. Fix it in `spec/04-tasks.md` (usually a glob instead of
  a directory) and start again; never pass `--no-preflight` to get past it.

The table does not print the execution mode: under
`host` every waiting task reads `queued` with the detail `awaiting the host
session (build.execution=host)`, and the round order is in the `plan` list
of `.gatekit/jobs/<job id>/job.json` (`id`, `round`, `parallel_candidate`).
Each task's prompt is `.gatekit/jobs/<job id>/tasks/<task id>/prompt.md`.

Exit codes: `0` nothing failed, `1` a task is `failed`, `timeout` or
`stopped`, `2` bad arguments or no tasks, `3` a task is out of retries, `4`
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

- **`host`, tasks still `queued`**: keep the same job. Implement the next
  queued task from its `prompt.md` and record it with `jobs complete
  <task_id>`. A task that was half written when the session ended is simply
  finished and completed the same way; the gates decide.
- **`worker`, tasks left `running` or `queued` with no live session behind
  them**: run `jobs stop` once so the old job is closed and any worker it
  still owns is ended, then start a new job for what is left:

  ```
  uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs start --tasks <ids not passed>
  ```

  The new job runs every listed task's gates first, so a task whose work
  was already finished is recorded `passed` without a worker. A dependency
  that is not in the new job does not block it.
- **A task that `jobs start` refuses with exit 3** has used its retries.
  Follow `.claude/skills/gatekit-build/references/build-failures.md`; do
  not reach for `--force-retry` before the diagnosis is written.

`spec/PROGRESS.md` may also hold a build-state block stamped when the
conversation was compacted (between the `gatekit:build-state` markers). It
is a narrative aid; `jobs status` is the record.
