# ADR-0013: Spawn a worker only when a different model is the point

Status: accepted 2026-09-17 (owner approval in the session that measured the
run); all six decisions implemented the same day and released in 0.8.0.
**Decision 1's default finally applied 2026-09-27**: the original
implementation left `config.DEFAULTS["build"]["execution"] = "worker"` as a
compatibility hedge, so `jobs.execution_mode`'s "unset means host" fallback
never fired for any project with a config file — which is every project
`/gatekit:setup` has ever touched. The code comment claimed `/gatekit:setup`
wrote `host` into new projects; no such code was ever written. So for ten
days this ADR was accepted, documented, and inert: every build still spawned
a worker per task. The default is now `host`, as decision 1 says. A project
that genuinely wants a worker per task sets `"execution": "worker"`
explicitly. Found while reconciling the user manual against the code.

Two corrections were made while implementing, both found by running the new
code against the real `gk-trial2` spec rather than only against fixtures:

- Decision 5 first counted a task's **direct** dependencies. `e2e-full-flow`
  declares one and waits on seven, so the check missed the case it was written
  for; it now measures transitive reach.
- Decision 4's evidence match was unbounded, so a one-letter task id matched
  inside ordinary prose and a shared ancestor directory (`src`) matched every
  task in the project. It now matches on identifier boundaries and only counts
  a leaf the dependency actually owns.

Origin: the `gk-trial2` run — a Next.js + Prisma + Playwright project built
through the full pipeline on 2026-09-17. It took **4.5 hours** of wall clock
for **26 minutes** of successful worker output. The owner, while it was still
running: *"이렇게 되면 이걸 누가 쓰겠어."* Then: *"워커가 뭐야 그냥 클로드
한테 맡기면 안되는 거야?"* And the answer they arrived at:

> 적대적 검증 할 때만 codex를 워커, codex로 코딩할 땐 워커로 claude를
> 띄우게 하고 나머지는 그냥 네이티브 CLI 도구로 코딩을 시키는 게 맞는 것 같아.

## Context

| Measured on `gk-trial2` | Value |
|---|---|
| Wall clock, first job to last | **4.5 h** |
| Sum of successful worker time (9 coding tasks) | **26 min** |
| Jobs started | **25** |
| Worker spawns | **35** |
| Of those, spawns that actually failed | **7** |
| Completion contract, run once everything existed | **13.7 s, 11/11 ok** |

Nine tasks whose successful work totals 26 minutes took four and a half hours,
and the contract that judges the whole result runs in fourteen seconds.

### Where the time went, precisely

**Not failures.** Only 7 of 35 spawns failed. The other 28 re-ran code that
was already correct.

**Gate edits.** Following one task across the run:

| Job | Gate argv at that moment | Outcome |
|---|---|---|
| `b01c` | `npm test` | passed at preflight, no worker |
| `afc7` | `npx vitest run tests/kind` | worker ran, passed |
| `51d0` | `npx vitest run tests/kind` | passed at preflight, no worker |
| `cf09` | `npx vitest run tests/kind` + `grep -rl QuestionKindBadge …` | worker ran, passed |

The gate changed four times. `no-answer-marker`'s code was right from the
second attempt; every later spawn existed because the *gate* moved, not the
code. `practice-commit` shows the same shape across six attempts.

This is not a defect in the operator's judgement. A gate names test files and
commands that do not exist until a worker has written them; `npm test` was too
broad, `vitest run tests/kind` was right, and nobody could know that before
the tests existed. **Gate refinement during a build is normal.** What is not
normal is that refining a gate costs a worker spawn.

ADR-0009 already anticipated half of this: `jobs start` runs gates at
preflight and skips the worker when they pass. That worked — four spawns were
avoided that way. But reaching preflight requires **starting a new job**, and
a running job holds a snapshot of `04-tasks.md`, so a gate edit is only picked
up by `jobs redelegate` (ADR-0009 decision 2) or a fresh `jobs start`. Twenty-
five jobs is the cost of that round trip, paid twenty-five times.

**Seven serial rounds.** `/gatekit:tasks` put nine tasks in seven rounds, only
one of which held more than one task. Checking every pair at the same
dependency depth: **zero write-scope collisions**. The rounds were forced by
`depends_on` declarations, and six of the ten declared dependencies have no
evidence — the depending task's instruction never refers to anything the
dependency writes. They encode the order a person reads the feature list in.
Keeping only the evidenced four: **seven rounds become three.**

**A verification task.** `e2e-full-flow` was task 9, round 7, gated on
`npx playwright test`. An end-to-end test passes only when every other task is
finished, so it failed on five consecutive attempts and passed on the seventh,
once everything else existed. The same command is *also* criterion
`e2e-full-flow-four-stages` in `05-gate.md`. It was being run in both places.

### The thing underneath all of it

A worker is `claude -p --output-format json --permission-mode acceptEdits` —
a fresh Claude session, spawned per task, fed the task brief on stdin. The
main session is also Claude.

So for the whole of `gk-trial2`, **Claude spawned Claude, 35 times.** The
process was isolated; the judgement was not. Each spawn paid the cost of
starting cold — no knowledge of the repo, of what earlier tasks built, or of
why — and re-derived it from the brief, while a session that already knew all
of it sat waiting for the result.

The isolation bought three things in principle: context that does not swamp
the main session, a write scope the hook can enforce, and parallelism. On this
run it delivered the first two and almost none of the third, because seven of
nine rounds held a single task.

What it never bought is the thing that actually matters for trust: an
independent judgement. `/gatekit:verify` already knows this — ADR-0007 made
the evaluator a separate process precisely so the producer does not grade
itself, and `verify.evaluator` can name a different CLI. On this run it was
left at the default `agent`, so even the grading was Claude.

The standing constraints apply: hooks and code are the enforcement; `unverified`
never rounds; producer ≠ evaluator; stdlib only; command files ≤ 160 lines.

## Decision

**A worker exists to bring in a model that is not the one already working.**
Everything else the runner does is cheaper in the session that already has the
context.

### 1. The default execution mode for a task is the host session

`build.execution` gains two values: `"host"` (new default) and `"worker"`.

Under `"host"`, `/gatekit:build` does not spawn per-task workers. The session
running the command implements the tasks in round order, and after each task
runs that task's gates exactly as `jobs.run_gates` does today, recording the
same `status.json`. The gates, the verdicts, the `write_scope` enforcement and
the ledger are unchanged — only the thing holding the editor moves.

Under `"worker"`, behaviour is exactly as today. It stays because two cases
genuinely need it, named in decision 2.

This reverses `build.md`'s standing rule that the main session never writes
code. That rule existed to protect context, and the protection is real — but
the host already has a mechanism for a session that fills up, and gatekit is
built to survive it.

**A compaction is not a loss for this pipeline.** Everything a build must not
forget is already on disk by design: `status.json` per task, `gates.json`,
`spec/PROGRESS.md`, the job dir. Stages communicate through files, never
through conversation memory — that is why `redelegate` can resume a task a
different session started. What a compaction removes is the narrative, and the
narrative is reconstructable from those files.

So decision 1a makes it explicit rather than accidental:

**1a. Build state survives compaction by contract, not by luck.**

A `PreCompact` hook (`gates/compact.py`) writes the current build state into
`spec/PROGRESS.md` — job id, each task's state and gate tally, what failed and
why — before the summary is taken. It never blocks and exits 0 on any internal
error, like every other hook here.

After a compaction the existing `UserPromptSubmit` injection carries one extra
field while a build is live: `build=<job_id> 6/9 passed, next: socratic-ai`.
The session that comes back reads that, reads `PROGRESS.md`, and continues.

This is what makes decision 1 safe for a long build: the session may be
compacted as often as the host likes, and the only cost is re-reading a file
that was written for exactly this purpose. Context pressure stops being a
reason to spawn a cold worker per task.

### 2. A worker is spawned when, and only when, the model differs

| Situation | Who does the work |
|---|---|
| Coding, host is Claude Code | the host session |
| Coding, host is Codex CLI | the host session |
| Coding the user explicitly delegated across models | a worker of the named backend |
| **Adversarial verification** | **a worker of a backend that is not the host** |
| A round with 3+ independent tasks | workers, for real parallelism |

The verification row is the one that must not be negotiable. `verify.evaluator`
defaults to `"agent"` today, which on a Claude host means Claude grading
Claude. The default becomes **the first enabled backend whose name differs
from the host**, falling back to `"agent"` with a printed warning when there
is none. `/gatekit:setup` offers to enable Codex for this purpose.

The parallelism row is a threshold, not a preference: a round holding one or
two tasks is faster in-session than the spawn cost, and on this run five of
seven rounds held exactly one.

### 3. A gate edit re-checks; it does not rebuild

`gatekit gates recheck [--task ID]` re-reads `spec/04-tasks.md`, runs the named
task's gates (or every task's) against the working tree, and updates
`status.json`. No job, no worker, no preflight round trip.

This is the direct fix for the 28 unnecessary spawns. When a gate moves and the
code is already right, the correct action is to run the new gate — which takes
seconds — not to re-derive the code. `/gatekit:build` step 4 routes a failure
whose cause is the gate here instead of to `redelegate`.

### 4. `depends_on` requires evidence, and rounds are shown before they are written

A task may declare `depends_on: [X]` only when its own instruction refers to
something X writes. "X comes earlier in the feature list" is not a dependency.

Before writing `spec/04-tasks.md`, `/gatekit:tasks` prints the shape and asks
once:

```
작업 9개 · 라운드 3개  (직렬 26분 → 임계경로 20분)
  round 1 (1개)  scaffold-and-schema
  round 2 (5개)  think-first-lock, no-answer-marker, why-prompt-submit, …
  round 3 (2개)  socratic-ai, practice-commit
```

Rounds are shown as prominently as the count, because rounds are what cost
time. The owner asked for the count; on this run the count (9) was reasonable
and the round total (7) was not, so the count alone would have shown nothing.

No round ceiling is imposed — a genuinely serial project exists, and a cap
would push the author to fake independence, which is the fault this decision
fixes pointed the other way.

### 5. A verification-shaped task belongs in the gate file

A check that can only pass once several other tasks are done is a completion
criterion, not a task. `spec validate` warns when a task's `write_scope`
contains no path outside a test directory while its `depends_on` names two or
more tasks — the `e2e-full-flow` signature — and names `05-gate.md` as where it
belongs. A warn, not a fail: a legitimate test-only task exists.

## Consequences

**On this run's numbers.** Decision 1 removes the spawn and cold-start cost
from 35 executions. Decision 3 turns the 28 gate-driven re-runs into gate
executions measured in seconds — the full contract, all eleven criteria, runs
in 13.7 s. Decision 4 turns seven rounds into three. Decision 5 removes the
task that failed five times. What remains is 26 minutes of actual
implementation plus one Codex verification pass.

**What is given up.** Per-task context isolation during coding, and with it
`build.parallel` on narrow rounds. The context half of that cost is largely
answered by decision 1a: the host compacts, `PROGRESS.md` holds the state, and
the session resumes — which is what the file was always for. What genuinely
remains is that one session now carries a long build's worth of history, so a
very wide project is slower to navigate than nine cold sessions would be.
That is the trade the owner named, and it is the right way round: the
isolation was costing hours and buying a second opinion from the same model.

**What is strengthened.** Verification becomes genuinely adversarial by
default instead of by configuration nobody set. On `gk-trial2` the evaluator
was `agent`, so the producer graded itself — the failure ADR-0007 exists to
prevent, reached by leaving a default alone.

**Honest limit.** Nothing here makes a worker's output more faithful, and
nothing measures whether the host session implements a task better than a
worker would. The claim is narrower and is about cost: for the same judgement,
one model, the session that already has the context is cheaper than a cold
one. When the judgement should differ, spawn.

**Contract changes** (`docs/ARCHITECTURE.md`): §10 gains `build.execution`,
the host-execution path recording the same `status.json`, `gates recheck`, and
the spawn rule; §9 gains `build.execution` and the new `verify.evaluator`
default; §6 gains the `depends_on` evidence rule and the verification-task
warn; §1's `/gatekit:tasks` row notes the shape approval. §13 lists the new
tests: host execution recording the same statuses and verdicts as worker
execution; `gates recheck` updating status without a job or spawn; the
evaluator default resolving to a non-host backend and warning when it cannot;
a round of three or more spawning workers while a round of one does not; the
test-only-scope-plus-two-dependencies warn and its negatives; the `PreCompact`
hook writing every task's state into `PROGRESS.md`, doing nothing when no job
is live, and exiting 0 when the file is unwritable; the build field appearing
in the prompt injection only while a job is unfinished and staying inside the
600-char budget; exit 0 on internal error for every new path.

## Rejected alternatives

- **Keep workers everywhere and make them faster.** The cost is not the
  binary's startup; it is a cold session re-deriving the project from a brief
  35 times. There is nothing to tune.
- **Remove workers entirely.** Then adversarial verification has nothing to
  run, and `/gatekit:verify`'s producer ≠ evaluator rule becomes prose.
- **Keep `verify.evaluator: "agent"` as the default and document the risk.**
  It is documented today, and this run still graded itself. A default nobody
  changes is the behaviour.
- **Cap the task count.** Nine tasks for eight features is reasonable; the
  rounds were the fault.
- **Auto-move a verification task into `05-gate.md`.** `/gatekit:tasks` does
  not own the gate file, and moving work between spec files silently hides it
  from the person approving the gate.
- **Check `depends_on` evidence mechanically and fail on it.** Deciding
  whether an instruction refers to a dependency's output needs to understand
  both; a checker strict enough to catch this run's six would block legitimate
  chains.

## Open questions

- Whether `max_retries` should persist across jobs for the same task. It
  resets on every `jobs start`, so `build.md`'s "stop after three consecutive
  failures" never bound across twenty-five jobs. Smaller once decision 3
  removes the reason to start most of them, but still open.
- What `"host"` execution does when a round is wide and the session is
  already long. Decision 2's threshold is a task count, not a measure of
  remaining context, and decision 1a makes a compaction cheap rather than
  unnecessary. Remaining context **is** observable — Claude Code passes
  `context_window` (`context_window_size`, `current_usage`, sometimes
  `used_percentage`) to the statusline command on every assistant message, as
  the owner's own HUD at `~/.claude/hud/usage-hud.mjs` reads today. But it
  arrives only there: no hook event carries it, so reaching it means writing
  the figure to the ledger from a statusline wrapper and reading it back in
  `UserPromptSubmit`. That is a separate decision — it touches the user's own
  `~/.claude/settings.json`, must chain rather than replace an existing
  statusline, and needs a Codex equivalent — so the count stands here and the
  context-aware threshold gets its own ADR.
- Whether Codex CLI fires a `PreCompact`-equivalent hook. Claude Code does;
  `hosts.py` would need the mapping, and until it exists a Codex host keeps
  build state only at the points `PROGRESS.md` is written anyway.
- Whether `gates recheck` should also refresh `preflight.json`, or whether
  that file should stay a record of what was true when the job started.
