# Writing a task's gates

Read by `/gatekit:tasks` Step 4. Every task in `spec/04-tasks.md` carries
at least one gate; this file says what makes a gate trustworthy, which
runners need glob patterns, and the two gates added by default.

## Step 4 — write gates

Every task carries at least one gate: an argv list, run without a shell, that
fails when the task is not done.

```json
"gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "tests.test_notes_create"]}]
```

The gate must be a command that exists in this repository, and you verify it
runs before writing it in. A gate that always passes is worse than no gate: it
manufactures false evidence.

### A gate must test what its own task builds

**Point every gate at something inside that task's `write_scope`** — the
test file it writes, the module it creates, the route it adds. Never give a
task the whole suite (`npm test`, `pytest`, `unittest discover` with no
target) as its gate.

This is not a style preference. It is the defect that made a real trial
(`gk-todo`) record three features as complete without a line of code being
written for them. All three tasks shared an `npm test` gate; the first
feature's tests alone made that suite pass; so `jobs start`'s preflight
found the gate already green, skipped the worker for each, and recorded
`passed`. The trial's own retro states the rule it arrived at: *"작업별
게이트를 항상 그 작업의 write_scope 안 경로로 좁힐 것 — 전체 스위트
게이트는 완료 기준(05)에서만 보조적으로 쓸 것."*

The test to apply while writing each gate: **if this task's code did not
exist, would this gate fail?** If another task's work can satisfy it, it is
not a gate for this task.

The whole suite still belongs in `spec/05-gate.md` as a completion
criterion, where it checks that everything holds together once every task
is done. That is a different question from "did this task do its job," and
a run where the suite passes but a feature was never wired up is exactly
what `/gatekit:verify`'s independent evaluator exists to catch.

Two runners need glob patterns, not directories: `node --test` loads a bare
directory as a module and fails with `Cannot find module`, so write
`tests/rules/*.test.js`; `gates/tokens.py` scans zero files for a bare
directory and exits 3, so write `src/**`. `jobs start` runs every gate once
before spawning a worker (ADR-0009) and refuses to start when a gate's
command itself errors — write the gate so that, with no code yet, it fails
the way the runner reports "tests failed" (exit 1), not a usage error.

**The token gate.** When `spec/tokens.json` exists, add this gate by default
to every task whose `write_scope` includes a stylesheet, component, or
template path — pass the task's own `write_scope` globs as the gate's
arguments so it scans only what that task writes:

```json
{"name": "tokens", "argv": [".claude/gatekit/bin/gatekit", "_gate", "tokens", "--lang", "<output_lang>", "<write_scope glob>", "..."]}
```

No `--root` is needed here: `jobs.run_gates` runs every task gate with the
project root as its `cwd`, and `tokens.py --root` defaults to `.`. Running
the same fence by hand from another directory resolves `.` to the wrong
root and reports `unverified` unless you pass `--root` explicitly.

It scans the task's own files for colour literals that are not in
`tokens.json` and exits 0 (`ok`), 1 (`fail`, a literal named), or 3
(`unverified`, `tokens.json` absent or unparsable, or nothing the gate knows
how to scan). Treat exit 3 the same as any other `unverified` result:
never round it to a pass. Do not add it to a task whose write scope has no
such path (e.g. pure backend logic, `"read-only"` tasks) — the ADR keeps the
scan narrow so a `fail` from it stays trustworthy.

**The screenshot criterion (ADR-0017 decision 9).** For any task whose
`write_scope` includes a UI surface — same test as Step 2's "the surface a
user touches" — `/gatekit:gate` (not this command) will derive a completion
criterion requiring `spec/design/build-<task-id>.png` to exist, captured by
a standalone script (`npx playwright test` or whatever E2E runner
`spec/03-architecture.md` names — never an MCP tool call, which only exists
inside an interactive session and cannot be a criterion `argv`). This
command's job is only to make that possible: name the task so `<task-id>`
is stable and unique (it already must be, per Step 3's uniqueness rule),
and do not write anything to `spec/design/` yourselves — the screenshot is
captured once the task's own gates already pass, as evidence for `/gatekit:
verify`'s evaluator to look at later, not a gate this command or the worker
clears itself.

