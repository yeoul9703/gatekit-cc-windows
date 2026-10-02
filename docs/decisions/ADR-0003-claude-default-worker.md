# ADR-0003: Claude CLI is the default build worker; Codex is opt-in

Status: not adopted in this fork (Claude Code only, ADR-0018).

## Context

`/gatekit:build` hands tasks from `spec/04-tasks.md` to a worker process:
an argv list plus a prompt on stdin, per `docs/ARCHITECTURE.md` §10.
`workers.py` supports more than one backend — the Claude CLI and,
optionally, Codex — because different users and organizations already
have different tooling and licensing arrangements in place, and gatekit's
job/gate machinery does not care which CLI actually does the work as long
as it honors the write-scope contract.

A newly installed gatekit plugin has to pick some default, though, and
that default determines what happens the first time someone runs
`/gatekit:build` without having configured anything.

## Decision

The `claude` backend is enabled by default in
`config.DEFAULTS["worker"]["backends"]`. The `codex` backend ships
disabled (`"enabled": false`) and is only turned on by an explicit
`/gatekit:setup codex` step, which runs `workers.check("codex")` (a
`shutil.which` existence check plus a `--version` probe) and requires the
user to confirm the result before `enable("codex")` is recorded.

## Consequences

- A fresh install works end to end with no extra setup, since gatekit is
  itself a Claude Code plugin — the Claude CLI is already the tool the
  user is running inside.
- Nobody's session silently starts shelling out to a second CLI they
  never installed or agreed to use. Enabling Codex is a deliberate,
  visible step with its own check-then-confirm gate, not a config default
  someone has to notice and turn off.
- `workers.py` treats both backends through the same interface
  (`resolve`, `check`, `run`), so this ADR is a default-and-policy
  decision, not an architectural fork — adding a third backend later
  follows the same "ships disabled, `check` before `enable`" pattern
  without needing a new ADR of its own.
- If Claude CLI availability assumptions ever change (for example, gatekit
  being used from a context where the Claude CLI is not the host process),
  this default should be revisited explicitly rather than assumed to still
  hold.
