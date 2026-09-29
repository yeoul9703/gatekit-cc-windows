# ADR-0002: Python standard library only

## Context

gatekit's hooks run on every prompt and tool call in a Claude Code
session. They need to start in well under a second and work on a
contributor's or user's machine with nothing installed beyond `python3`
itself. Common conveniences — `pyyaml` for parsing frontmatter, `jsonschema`
for validating spec fences, `rich` for prettier CLI output — would each
shave a little implementation effort off some corner of the kernel or the
CI gates.

Every one of those conveniences also introduces a dependency that has to
be installed before gatekit's hooks can run at all. A hook that fails to
import a missing package doesn't degrade gracefully in the way
`docs/ARCHITECTURE.md` §3 requires ("every hook exits 0 on any internal
error") — it fails on the very first line, before any of that error
handling has a chance to run, on every single invocation, until someone
notices and runs a package manager.

## Decision

`plugin/gatekit/`, `plugin/gatekit/gates/`, and `tools/` use only the
Python 3.9+ standard library. No `pip install`, no `npm`, no vendored
third-party source, anywhere in these trees. If an implementation seems to
need something the standard library doesn't provide, that is a signal to
write a new ADR proposing the dependency explicitly — with the trade-off
stated — rather than adding it quietly.

## Consequences

- `python3 -m gatekit <sub>` and every `tools/gate_*.py` script run
  immediately after a fresh clone, with no install step, on any machine
  with Python 3.9+. `tools/gate_manifest.py`'s "python version ≥ 3.9"
  doctor axis is the only version requirement that exists.
- CI (`.github/workflows/ci.yml`) needs no dependency-resolution step and
  no network access to run the full gate suite — `actions/setup-python`
  and a checkout are the entire setup.
- Some implementations are more verbose than they would be with a
  third-party library: JSON Schema-style validation in `spec.py` is
  hand-written, frontmatter parsing in `tools/gate_skill_size.py` is a
  small regex rather than a YAML parser, and so on. This is an accepted
  cost, not an oversight.
- A future genuine need for a dependency (for example, if a worker backend
  needs a client library gatekit itself must ship) requires its own ADR
  weighing that specific trade-off; this ADR is the default, not an
  absolute bar for all time.
