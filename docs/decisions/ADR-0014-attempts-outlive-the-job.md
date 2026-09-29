# ADR-0014: A task's attempts are counted per task, not per job

Status: accepted 2026-09-17 (owner approval in the session that found the defect); implemented the same day and released in 0.9.0.

Verified by replaying the real `gk-trial2` job history through the new counter: `jobs start` refuses before the third consecutive failure of `e2e-full-flow`, at job `dcab` — the run's actual tenth attempt never happens.

Origin: ADR-0013's first open question, and the `gk-trial2` data behind it.

## Context

`build.max_retries` (default 2) is meant to stop a task that keeps failing.
`redelegate` reads `status.json.attempt`, refuses past the budget with
`RetryBudgetExceeded` (CLI exit 3), and `build.md` adds a rule on top:

> Count consecutive failures per task. **On the third failure of the same task,
> stop redelegating** and switch to diagnosis mode.

Neither binds across jobs. `start` writes `attempt=1` into every task it
prepares, so a new `jobs start` resets the counter. The trial shows exactly
that. `e2e-full-flow`'s recorded attempts, in job order:

| Job | attempt | state |
|---|---|---|
| 5413 | 1 | failed |
| ce3a | 2 | failed |
| dcab | 3 | failed |
| 99f7 | **1** | failed |
| 7672 | 2 | failed |
| 5040 | **1** | failed |
| 15dc | 1 | passed |
| d9aa | 3 | failed |
| 4549 | **1** | failed |
| 772f | 1 | passed |

**Eight failures of one task, and the budget never once triggered.** The
counter climbed to 3 and restarted, three separate times. The prose rule did
not bind either: nothing in the runner counts across jobs, so the only counter
was the operator's memory across a four-and-a-half-hour session.

This is not a case of the operator ignoring the rule. Starting a new job was
the *supported* way to pick up an edited gate before ADR-0013 added
`jobs recheck` — a running job holds a snapshot of `04-tasks.md`, so a gate fix
reached the runner only through `redelegate` or a fresh `start`. The retry
budget was defeated by the workflow the tool prescribed.

ADR-0013 removes most reasons to start a new job. It does not make the counter
correct: a genuinely failing task still resets simply by being started again.

The standing constraints apply: hooks and code are the enforcement, not prose;
`unverified` never rounds; stdlib only; tests first.

## Decision

### 1. Attempts are recorded against the task, not the job

`.gatekit/attempts.json` holds one entry per task id:

```json
{"version": 1, "tasks": {
  "e2e-full-flow": {"failures": 8, "last_job": "20260917T142402Z-08de",
                    "last_gate": "e2e", "updated_at": "…"}}}
```

`failures` counts **consecutive** failures. Any outcome of `passed` resets the
entry to zero; `blocked` and `stopped` leave it untouched, since neither is a
judgement about the work. The file sits beside `config.json` in `.gatekit/`
and is written atomically like every other state file.

A task id is the key because that is what the operator retries. The job is
recorded only so a report can say where the last failure happened.

### 2. `redelegate` and `start` both consult it

`redelegate` refuses when the task's recorded consecutive failures have reached
`max_retries`, whichever job produced them — the same `RetryBudgetExceeded` and
exit 3 as today, with a message naming the count and the jobs it spans.

`jobs start` refuses to include a task already at the limit, listing it and
exiting **3** — the code `redelegate` already uses for "out of retries", so one
condition keeps one signal. Starting a fresh job is how the budget was escaped
on the trial, so this is the half that actually closes it.

`--force-retry <task_id>` clears one task's entry and proceeds. The budget
exists to stop a loop, not to make a task unrunnable once the cause is fixed,
and clearing is the operator saying "I changed something". It is per task and
never global.

### 3. Exhausting the budget writes the diagnosis prompt, not the diagnosis

When a task hits the limit, the refusal names the task, the failing gate, the
number of consecutive failures and the jobs they span, and points at
`spec/RECOVERY.md`. It does **not** write a diagnosis: deciding why a task
fails requires reading its gate output and the code, which is the operator's
work and is already `build.md` step 4's fourth bullet.

What changes is that the operator now reaches that step instead of restarting
around it.

### 4. `jobs status` shows the carried count

The status row for a failed task gains `(n consecutive)` when the recorded
count exceeds the attempt inside this job — the case that was invisible. A task
on its first attempt in this job but its sixth overall must not look fresh.

## Consequences

**On the trial's numbers.** `e2e-full-flow` would have been refused at its
third consecutive failure, in job `dcab`, roughly 40 minutes into the run
instead of proceeding through five more failures and two more hours. The
refusal would have pointed at `spec/RECOVERY.md`, where the diagnosis —
"an end-to-end gate cannot pass until every other task is done" — was
available the whole time and is what ADR-0013 decision 5 now warns about
before the build starts.

**What it costs.** One more state file, and one more way for a build to stop.
A task whose cause was fixed outside gatekit's view now needs
`--force-retry`; that is a deliberate speed bump on the exact action that hid
the loop.

**What it does not do.** It does not judge *why* a task fails, and it does not
distinguish a task failing for a new reason each time from one failing the same
way. Consecutive-failure count is a crude signal; it is the one `build.md`
already asked for and could not enforce.

**Interaction with ADR-0013.** `recheck` does not touch the counter: re-running
a gate against existing code is not an attempt at the work. `complete_task`
does, since that is a host-executed attempt and must count the same as a
worker's.

**Contract changes** (`docs/ARCHITECTURE.md`): §2 lists
`.gatekit/attempts.json`; §10 gains the per-task counter, the two refusal
points, `--force-retry`, and the rule that `recheck` does not count while
`complete_task` does. §13 lists the new tests: a failure incrementing the
count, a pass clearing it, `blocked`/`stopped` leaving it alone, `redelegate`
and `start` both refusing at the limit with their exit codes, `--force-retry`
clearing exactly one task, `recheck` not counting, `complete_task` counting,
a missing or corrupt file behaving as empty, and the status row showing the
carried count.

## Rejected alternatives

- **Keep the counter in `status.json` and read the previous job's.** Requires
  knowing which job was "previous" for a task, which is not recorded and is
  ambiguous once `--tasks` subsets exist.
- **Count every failure, not consecutive ones.** A task that failed twice a
  week ago and passes today is not in a loop. The signal being asked for is
  "this is not converging".
- **Refuse in `build.md` prose only.** That is what exists, and the trial
  shows it counting nothing.
- **Make the budget global rather than per task.** A build with several
  independent hard tasks would stop on the sum of unrelated failures.
- **Reset on any edit to `04-tasks.md`.** Tempting, since a gate fix often
  precedes a legitimate retry — but ADR-0013 routes a gate fix to `recheck`,
  which does not count, so the remaining resets would mostly be instruction
  edits made *because* the task keeps failing, which is the loop itself.

## Open questions

- Whether the entry should also record the failing gate's output hash, so a
  task failing the same way each time can be distinguished from one making
  progress. It would make the signal much better and needs a decision about
  how much output to keep.
- Whether `/gatekit:verify` should report a task that finished `passed` but
  carried a long failure history, as a quality signal rather than a verdict.
