# ADR-0007: The evaluator may be a different CLI than the builder

## Context

`/gatekit:verify` separates producer from evaluator: the session that built
the code does not grade it. Until now the evaluator was always a read-only
subagent of the host, so it was a different context but the same model as
the builder. The build worker, by contrast, can already be a different CLI
(`workers.py`, ADR-0003). A study participant on Claude Code who wants
Codex to grade, or the reverse, had no way to ask for it.

Two things make this cheap: the worker infrastructure already spawns a CLI
with a prompt on stdin and `GATEKIT_TASK_ID` in its environment, and both
CLIs have a read-only mode (`claude -p --permission-mode plan`,
`codex exec --sandbox read-only`). Both authenticate with the user's
subscription login; no API key is involved.

## Decision

1. Every backend carries two argv lists: `argv` for building and
   `read_only_argv` for grading. A backend without `read_only_argv` cannot
   be an evaluator, and its writable argv is never substituted for the
   missing one. The unsafe-flag rule applies to both lists.
2. `verify.evaluator` in `.gatekit/config.json` names who grades: `agent`
   (the host's read-only subagent, the default) or a backend name.
   `workers set-evaluator` changes it.
3. `jobs evaluate` runs the named backend once with its `read_only_argv`,
   under `.gatekit/jobs/<job>/evaluate/`, with `GATEKIT_TASK_ID=evaluate`
   and a `task.json` whose `write_scope` is `read-only`. Inside the
   evaluator's own session the write gate therefore refuses every write,
   independently of the CLI sandbox. It records `passed|failed|timeout` and
   prints the reply tail; a state other than `passed` is `unverified` for
   every criterion.
4. `/gatekit:verify` branches on the setting: a backend evaluator receives
   the same brief as the subagent, minus the `PROGRESS.md` bullet, and the
   main session writes `PROGRESS.md` from the reply.

## Consequences

- Adversarial verification across models is one config line away, on
  either host, with subscription logins only. The user needs both
  subscriptions to use both models; the README says so.
- The read-only guarantee is two layers deep — CLI sandbox and write gate —
  but the second layer holds only where that CLI's session has gatekit
  hooks: the Claude Code plugin at user scope, or the Codex layer from
  ADR-0006 in the project. `jobs evaluate` does not verify this; `doctor`
  axis 8 reports the Codex layer's presence.
- The subagent evaluator can write `spec/PROGRESS.md` as its one
  exception; a CLI evaluator cannot, so the command moves that write to
  the main session. The trail is the same file either way.
- `workers check` still probes only for the binary and its version, not
  the login state. An evaluator whose CLI is not logged in shows up as
  `failed`, which is honest but late; a login probe remains future work.
