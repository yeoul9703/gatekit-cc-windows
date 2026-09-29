# ADR-0009: Gates run before workers, redelegation re-reads the task, and a job can be stopped

Status: accepted 2026-09-14 (owner approval in the trial session); implemented the same day.

Origin: the Tetris trial build, `docs/retros/2026-09-14-tetris-trial.md`
findings R1, R2, R3 and the timing table under R13.

## Context

`jobs.py` today does four things in sequence for every task: snapshot the
task fence into `tasks/<id>/task.json`, spawn a worker with the prompt on
stdin, wait for it to exit, then run the task's gates and record
`passed` or `failed`. `redelegate` archives the attempt, appends the failed
gate's output to the prompt, and re-runs from the same snapshot. Nothing
runs a gate before a worker has run, nothing re-reads `spec/04-tasks.md`
once a job has started, and nothing can end a job that is still running.

The trial produced four observations that all trace to those gaps.

1. **A wrong gate command cost a whole job.** The task gates were written
   as `node --test tetris/tests/rules/`. Node's runner loads a bare
   directory as a module and exits 1 with `Cannot find module`, so the
   gate could never pass. Six workers wrote correct code (37/8/25/10/15/9
   tests, all green under the right command) and every task was recorded
   `failed`. The job ran 18 minutes 22 seconds before it drained. The
   command was wrong from the first second, and one dry run before the
   first spawn would have named it.

2. **A worker gamed the gate.** Given that failure output on redelegation,
   the `screens-shell` worker created `tetris/tests/shell/index.js` that
   `require()`s the real test file so the *wrong* command would pass, and
   said so in a comment. The gate went green on false evidence. The
   redelegate prompt says "fix the cause"; it never says that the cause may
   be the gate.

3. **Redelegation ran the stale gate.** After `04-tasks.md` was corrected
   to `tetris/tests/rules/*.test.js`, `jobs redelegate core-rules` and
   `jobs redelegate play-marathon` still ran the directory form, because
   `redelegate` rebuilds the prompt from the job's `task.json` snapshot.
   Both failed again for no reason connected to the code. Only a fresh
   `jobs start` picked up the fix, and that fresh job spent 5 minutes 52
   seconds spawning six workers whose only finding was "nothing to do":
   every gate already passed before they started. Gates themselves took
   0.6 seconds for all ten.

4. **A dependent task ran after its dependency failed.** `play-marathon`
   (`depends_on: ["core-rules"]`) started at 04:24:06, the same second
   `core-rules` was recorded `failed`. `_waves` orders by `round` then
   `depends_on` but never checks the dependency's *state*. The task
   proceeded on code that, as far as the job knew, was broken.

There is also no way to stop a job. With thirteen other Claude sessions
open on the same folder, killing worker processes by name was not safe,
so the broken job was left to run out.

The standing constraints apply: hooks and code are the enforcement, not
prose; every hook exits 0 on internal error; the verdict words are
`ok / warn / fail / unverified` and `unverified` never rounds; standard
library only; tests first.

## Decision

### 1. `jobs start` runs every gate once before spawning any worker

For each task selected for the job, before the first spawn, run its gates
with `jobs.run_gates` exactly as they would run after the worker. Record
the result in `tasks/<id>/preflight.json` (same shape as `gates.json`).
Then classify:

| Preflight result | Meaning | Action |
|---|---|---|
| every gate `ok` | the task's evidence already exists | record `state = "passed"`, `detail = "gates passed at preflight; no worker spawned"`, skip the worker |
| some gate `fail` and the output looks like a **command error** | the gate itself cannot pass | refuse to start the job; print the task id, gate name and output tail; exit non-zero |
| some gate `fail` otherwise, or `unverified` | expected before the work is done | spawn the worker as today |

"Command error" is a narrow, listed heuristic, kept in one function
(`jobs.classify_gate_result(gate_result, argv) -> "command_error" |
"suspicious" | "expected"`) with its own tests. It refuses only when the
failure is provably about the command rather than the work: exit code 126
or 127 (the shell's "cannot execute" / "not found"), or an output line
matching one of a short pattern list — `Cannot find module`, `can't open
file`, `No such file or directory`, `command not found`, `is a directory` —
that **also names one of the gate's own arguments** (its program, for
`command not found`). A failing test that merely prints "No such file"
about a fixture names nothing from argv and does not refuse. Signals that
are only suggestive — exit ≥ 2 on its own (`pytest` uses 2 for collection
errors and interrupts), a pattern line naming nothing from argv, a usage
banner opening stderr — make the gate `suspicious`: the job starts and a
`warn` line is printed and kept in `job.json.preflight_warnings`. Refusal is
reserved for the named-argument and 126/127 cases. The list is data in the
module, not prose in a command file.

*Revised at review (2026-09-14): the first draft refused on any exit ≥ 2
and on any pattern match; the reviewer showed three false positives
(pytest exit 2, fixture-missing test output, usage text inside captured
output), each of which would have refused a legitimate job with no
override short of `--no-preflight`.*

A gate that passes at preflight on a task whose write scope contains no
files yet is reported separately as `warn: gate passed before any work —
check that it can fail`. It is not refused, because a legitimate gate can
pass early (a `read-only` investigation, a task whose files a previous
job already wrote), but it is the signature of a gate that always passes,
and the operator should see it.

`--no-preflight` skips the step for the rare case where a gate is
expensive or has side effects; the flag is recorded in `job.json`.

### 2. `redelegate` re-reads the task from `spec/04-tasks.md`

Before archiving the attempt, `redelegate` parses the current
`spec/04-tasks.md`, finds the task by id, and if its fence differs from the
job's `task.json` snapshot, overwrites the snapshot and records
`detail = "task re-read from spec/04-tasks.md; gates changed"` (or
"instruction changed", or both) in `status.json`. `jobs status` shows that
detail on the task line. If the task id no longer exists in the file,
`redelegate` refuses with a message naming the file.

Re-reading applies to `redelegate` only. `jobs start` still snapshots, so a
running job is not affected by edits made while workers run.

### 3. `jobs stop [--job ID]` ends a running job

Every spawned worker's pid is written to `tasks/<id>/status.json` as
`pid` and cleared again the moment the worker is reaped, before the task
enters `gating` — from then on the number may belong to any process.
`jobs stop` sends SIGTERM to each pid of a task still in `running` that is
alive **and** whose process was started by this job (checked by pid plus
recorded start time against `ps -o etime=`, so a recycled pid is never
signalled), waits `STOP_GRACE_S` (five seconds), then SIGKILL. Each such task is recorded
`state = "stopped"`, `detail = "stopped by jobs stop"`; queued tasks become
`stopped` without a signal. `job.json` gets `stopped_at`. `stopped` is
added to the state set and is terminal; `results --compact` and the
`/gatekit:build` command treat it like `failed` for the purpose of "not
done". `jobs stop` never touches a process it did not start.

### 4. The redelegate prompt says the gate may be the problem

`redelegate` appends one more paragraph after the gate output:

> If the gate command itself looks wrong — it names a file or directory
> that this task was never asked to create, or it fails in a way no code
> change could fix — do not adapt the code so that the wrong command
> passes. Stop, and say in your last message which gate looks wrong and
> why. A human will fix the task file.

This is prose in a prompt, so it is not enforcement; decision 1 is the
enforcement, since a command-error gate never reaches a worker in the
first place. The sentence exists for the residual case the heuristic
misses.

### 5. A task whose dependency did not pass does not run

`_waves` (or the loop that consumes it) skips a task while any id in its
`depends_on` has a state other than `passed`. The task stays `queued`
with `detail = "waiting on <id> (<state>)"`. When the job drains with such
tasks still queued, they are recorded `state = "blocked"`,
`detail = "dependency <id> ended <state>"`. `blocked` is terminal but it is
**not** a failure: the task was never run and never judged, so a job whose
only non-passed tasks are blocked reports `unverified`, never `fail`
(the cardinal rule: `unverified` is never rounded). When the dependency's
own gates returned `unverified`, the detail says so. `redelegate` of the dependency, once it passes,
returns the blocked task to `queued` on the next `jobs start --tasks`
(no automatic resume; the operator starts it).

### 6. Command text

`plugin/commands/tasks.md` and `gate.md` gain one note each: `node --test`
and `plugin/gatekit/gates/tokens.py` take glob patterns
(`tests/rules/*.test.js`, `src/**`); a bare directory is loaded as a
module by the first and scans zero files in the second. `build.md`
documents preflight, `stop`, and the `blocked` and `stopped` states.

## Consequences

**Time.** On the trial's numbers: the wrong-gate job (18 min 22 s) would
have been refused at preflight in under one second; the re-run job
(5 min 52 s) would have recorded six `passed` tasks at preflight in
0.6 seconds; the two stale redelegations (2 min 35 s) would have run the
corrected gate. That is 27 of the roughly 30 minutes the retro counted as
waste. Worker time for real work (3–6 minutes per task) is unchanged and
is not the problem.

**Evidence.** A gate that passes before any work is now visible as a
warning instead of silently manufacturing a green result later. A gate
that cannot pass is caught before it can teach a worker to route around
it. The `screens-shell` gaming case could not have happened under
decision 1 because that gate would never have reached a worker.

**Costs.** `jobs start` gets slower by the sum of the gates' preflight
runtime; on a project with a slow suite that is real, hence
`--no-preflight`. The command-error heuristic is a list and will miss
cases; the design keeps misses on the safe side (start the job, print
`warn`) and never refuses on a guess. `stop` adds a pid to `status.json`
and a signal path that must be tested with a fake process. `blocked` and
`stopped` add two states every consumer of `status.json` must know:
`jobs status`, `results`, `/gatekit:build` step 3–5, and
`spec/PROGRESS.md` milestone rows.

**Contract changes** (`docs/ARCHITECTURE.md`): §10 gains the preflight
step and `preflight.json`, the `pid` field, `stopped` and `blocked` in
the state set, `stop` in the `jobs` verb list and in the §14 `run()`
docstring, the dependency-state rule for waves, and the re-read rule for
`redelegate`. §6 notes that a gate must be able to fail before the work
exists. §13 lists the new tests: preflight classification (pass / command
error / expected failure / unsure), early-pass warning, re-read with
changed gates, refusal on a missing task id, stop with a fake pid and a
recycled pid, dependency gating, and the exit-0-on-internal-error
property for every new path.

## Rejected alternatives

- **Pin gates in the approval hash.** Putting `04-tasks.md` under the same
  hash as `05-gate.md` would make every gate edit a re-approval. The trial
  already needed three approvals; this would have made it five. The gate
  file defines "done"; the task file defines "how", and "how" should be
  editable mid-build.
- **Let the worker fix the gate.** Giving workers write access to
  `04-tasks.md` legalises exactly the move decision 4 forbids.
- **Ask the operator on every redelegation.** Defeats autonomous builds;
  the point of the job runner is that nobody is watching.
- **Skip preflight when no code exists.** The "gate passes before any
  work" warning is only possible if preflight runs on the empty tree; it
  is the cheapest always-passes detector available.
- **Kill by process name in `stop`.** Unsafe with concurrent sessions on
  the same machine; the trial had thirteen.

## Open questions

- Should preflight also run at `/gatekit:gate` time on the criteria in
  `05-gate.md`? That command already tells the author to execute every
  criterion by hand before writing it; the trial shows that instruction
  was followed and still misread (`node --test docs/` printed a failure
  that looked like a real run). A mechanical dry run with the same
  command-error heuristic would have caught it. Deferred: it changes the
  gate command, not `jobs.py`.
- Whether `blocked` tasks should resume automatically when their
  dependency later passes inside the same job. Manual resume is chosen
  here because an automatic one hides the fact that the dependency
  failed once.
- Whether the command-error pattern list should be per-backend data under
  `plugin/spec-kit/` rather than a constant in `jobs.py`. Data files are
  the repo's stated preference; a constant is chosen for the first cut
  because the list is short and tested.
