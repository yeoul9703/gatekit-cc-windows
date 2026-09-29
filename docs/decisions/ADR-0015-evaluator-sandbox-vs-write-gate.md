# ADR-0015: The evaluator needs a writable sandbox, and gatekit cannot make Codex trust its own hooks

Status: accepted 2026-09-18 (owner approval in the session that found the sandbox defect); implemented the same day.

Origin: the `gk-trial2` retrial's Codex evaluator run
(`.gatekit/jobs/20260918T133500Z-2b06`). 111 seconds, exit 0, and 12 of 18
criteria came back `unverified` for one repeated reason.

## Context

`jobs.evaluate` resolves the evaluator backend with `read_only=True`, which for
Codex means `codex exec --sandbox read-only`. The docstring states the
intended design:

> The worker gets `GATEKIT_TASK_ID=evaluate` with a read-only `task.json` so
> the write gate refuses writes inside its session, **on top of** the
> backend's `read_only_argv` sandbox.

Two layers were intended. Only one exists in practice, and it is the wrong
one for this job.

### What `--sandbox read-only` actually blocks

The evaluator's job is to run `npx vitest`, `npx playwright test` and similar
commands and read what happens — not to edit source. But a test runner is not
read-only software: Vitest writes a config cache, Playwright writes
`test-results/.last-run.json` and screenshots. `--sandbox read-only` blocks
those too, because it does not distinguish "the evaluator edited a source
file" from "the test runner it invoked wrote its own scratch output". The
retrial's evaluator output names the same failure twelve times:

> Vitest 설정 로딩 중 `EPERM`; 테스트 미실행.
> Playwright가 `test-results/.last-run.json` 삭제·쓰기 권한 오류로 종료.

`unverified` is the correct verdict for what happened — the evaluator did not
round a blocked test to a pass — but what happened is that the sandbox
prevented the criteria from running at all. A verification pass that cannot
execute twelve of eighteen checks is not doing its job, regardless of how
honestly it reports the failure.

### Why the write gate — the intended second layer — did not fire

The write gate is a project hook, registered in `.codex/hooks.json`. Reading
`gatekit.hosts`'s own docstring:

> Codex loads project hooks only once the project's `.codex/` layer is
> trusted; that trust cannot be read from here, so `status` never claims the
> hooks fire.

This session verified what that means concretely. `gk-trial2` had no
`.codex/` directory at all — `evaluate()` had never installed one, and nothing
in its code path does. Installing it (`gatekit install --host codex`) and
running `codex exec --sandbox workspace-write` in the same project showed:

- `~/.codex/config.toml` already had `[projects."<path>"] trust_level =
  "trusted"` for this project — from an earlier, unrelated interactive
  session — but **zero** `[hooks.state."<path>/.codex/hooks.json:*"]` entries.
  Project trust and hook trust are recorded separately, and only the second
  gates a hook actually running.
- Running `codex exec` under this condition produced no `write.py` hook
  activity in Codex's own log lines, while a **different**, already-trusted
  Codex plugin's hooks (`oh-my-claudecode`, global, unrelated to this project)
  fired normally in the same run.

So the failure mode is silent, not loud: an untrusted project hook is skipped,
not refused. Switching `evaluate`'s sandbox to `workspace-write` today, with no
other change, would make the evaluator a real code-writing session with no
gate watching it — the exact risk `read_only_argv` exists to prevent.

Codex does expose `--dangerously-bypass-hook-trust`. Its own help text —
"DANGEROUS. Intended only for automation that already vets hook sources" — is
the reason this ADR does not reach for it: it removes the one signal (a human
approved this exact hook content) that hook trust exists to provide, for the
sake of automation that has not actually vetted anything.

Hook trust cannot be granted non-interactively. It is recorded per hook, keyed
by a content hash, and nothing in Codex's CLI surface sets it outside the
interactive approval flow.

The standing constraints apply: hooks and code are the enforcement, not prose;
`unverified` never rounds; producer ≠ evaluator (ADR-0007); stdlib only.

## Decision

### 1. `evaluate` requires trusted hooks before it runs Codex `workspace-write`

Before switching a Codex evaluator to `workspace-write`, `jobs.evaluate` checks
`~/.codex/config.toml` for a `hooks.state` entry matching this project's
`.codex/hooks.json` and the write gate's own event key. `codex_hooks_trusted(root)`
does the check: parse the TOML (stdlib `tomllib` on 3.11+, a narrow hand-rolled
fallback reader for the one table shape this needs on 3.9–3.10 — the file is
simple `[section]` / `key = "value"` pairs, not general TOML), and confirm at
least one `hooks.state."<hooks.json path>:pre_tool_use:*"` key exists.

- **Trusted**: proceed with `--sandbox workspace-write`. The write gate is the
  layer that was always meant to do the real work; the sandbox becomes the
  second layer, catching whatever the gate's own heuristics miss.
- **Not trusted**: `evaluate` refuses before spawning anything, naming the
  exact fix:

  > Codex hooks are not trusted for this project yet, so `workspace-write`
  > would run with no write gate watching it. Run `codex exec --sandbox
  > workspace-write "echo trust-check"` once by hand in this project and
  > approve the hook trust prompt, then re-run `/gatekit:verify`.

  This is a refusal, not a silent fallback to `read-only` — falling back
  quietly would reproduce exactly the `unverified`-everything result this ADR
  exists to fix, with no signal about why.

`--force-read-only-evaluator` overrides the refusal for a project that
deliberately wants the stricter, more limited sandbox — accepting that most
criteria will read `unverified` in exchange for zero risk of a stray write.

### 2. `evaluate` installs the Codex host layer if it is missing

`gk-trial2` had no `.codex/` directory at all; the trust check in decision 1
would refuse forever with nothing to trust. Before the check, `evaluate`
calls `hosts.install(root, "codex")` when `.codex/hooks.json` does not exist
(idempotent, as `hosts.py` already documents). This does not grant trust —
only a human can — but it removes the otherwise-permanent blocker of there
being nothing to approve.

### 3. Claude Code's own evaluator sandbox is checked, not assumed safe

The original docstring's "two layers" claim was wrong for Codex; it is worth
confirming for Claude directly rather than assuming symmetry. `read_only_argv`
for the `claude` backend is `--permission-mode plan`, which Claude Code
enforces itself — there is no separate "did the user trust this hook" step,
because the plugin's hooks are loaded by the act of installing the plugin.
`--permission-mode plan` blocks all edits at the tool-call level, before a
test runner underneath it could write anything either. No code change follows
from this: it is recorded here because the asymmetry between the two backends
is otherwise invisible, and a future backend added under `read_only_argv`
must be checked the same way rather than assumed to behave like either
existing one.

## Consequences

**What this fixes.** A Codex evaluator that has had its hooks trusted once
(a one-time, per-machine step) can now actually run the test suites it is
meant to grade, instead of reporting `unverified` on every check that needs to
write a scratch file.

**What remains manual.** Hook trust itself. This ADR makes the requirement
visible and actionable — a named command to run — rather than removing it,
because removing it means bypassing the approval Codex's own design puts there
on purpose.

**Cost of decision 1's check.** One TOML read per `evaluate` call under Codex;
negligible. The narrow parser is scoped to exactly the shape gatekit needs
(flat `[section]` tables, string values) and is not a general TOML
implementation — it must fail closed (treat unparseable as "not trusted")
rather than guess.

**What `--force-read-only-evaluator` costs.** A user who reaches for it gets
back today's behaviour: an honest but mostly `unverified` report. That is a
regression from this ADR's fix, chosen deliberately by the user, not a default.

**Contract changes** (`docs/ARCHITECTURE.md`): §10's `evaluate` paragraph
gains the trust check, the install-if-missing step, `--force-read-only-evaluator`,
and the corrected claim about what protects a Claude Code evaluator. §13 lists
the new tests: `codex_hooks_trusted` true/false/malformed-TOML/missing-file;
`evaluate` refusing with the exact remediation message when untrusted; installing
the host layer when absent and not reinstalling when present; proceeding with
`workspace-write` when trusted; `--force-read-only-evaluator` bypassing the
refusal and keeping `read-only`; the check never running for the `claude`
backend.

## Rejected alternatives

- **Use `--dangerously-bypass-hook-trust`.** Its own text says why not: it
  removes the human-approval signal hook trust exists to provide, for
  automation the flag's authors explicitly say has not earned that trust.
- **Grant a narrower sandbox** (test-cache directories writable, everything
  else read-only) via Codex sandbox policy config instead of the write gate.
  Rejected for now, not permanently: it would need per-project maintenance of
  a path allowlist as test tooling changes, where the write gate already
  reuses the same `write_scope` mechanism every other task in the build
  uses. Left as an open question below.
- **Silently fall back to `read-only` when hooks are untrusted.** Reproduces
  today's failure with no signal about the cause. A refusal that names the
  fix is more useful than a report that quietly can't check twelve criteria.
- **Skip decision 2 and require the user to run `install --host codex`
  themselves first.** Adds a manual step for something gatekit can safely do
  on its own — installing files is idempotent and reversible; granting trust
  is not, which is exactly why only decision 1's check, not an install, stays
  manual.

## Open questions

- Whether a narrower sandbox (decision 1's rejected alternative) is worth
  building once more than one test framework's scratch-path needs are known —
  it would remove the dependency on hook trust entirely for evaluation, at
  the cost of a path allowlist to maintain.
- Whether `jobs start`'s own Codex workers (not just `evaluate`) hit the same
  trust gap. They already run `workspace-write` by default and were not
  measured in this session; if hook trust is equally silent there, a worker's
  write gate could be unenforced today with no test having caught it yet.
- Whether `doctor` should report Codex hook-trust status as its own axis, so
  the gap is visible before a build or verify run hits it rather than after.
