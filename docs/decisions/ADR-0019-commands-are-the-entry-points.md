# ADR-0019: Commands are the only entry points; rare steps live in reference docs

Status: accepted 2026-10-02. Amends ADR-0018 decision 2 (the `skills` folder is gone); superseded by ADR-0020 (entry points moved to .claude/skills; the preamble and rare-path split stay).

## Context

Each pipeline existed twice: `.claude/commands/gatekit/<name>.md` (the
execution instruction, `/gatekit:<name>`) and
`.claude/skills/gatekit-<name>/SKILL.md` (a short shim holding the natural
language triggers and pointing at the command). Claude Code lists both, so a
session carried twenty entries for ten pipelines, and the two descriptions
drifted: the setup shim said "initialize the config and check workers, not
for diagnosing an install" while the command installs uv, builds the `.venv`
and runs doctor.

The audience is beginners on native Windows who follow the upstream
plugin's material, so the names they type must stay `/gatekit:<name>`. A
probe on 2026-09-30 (`claude -p` in a scratch folder) showed that a project
skill cannot produce a colon name: `.claude/skills/gkx/build/SKILL.md` was
not listed at all, only a flat `.claude/skills/gkx-flat/SKILL.md` was. In a
project folder the colon name comes only from `.claude/commands/<ns>/`.
Moving the pipelines to skills would have renamed them to `/gatekit-<name>`.

Every command also opened with the same "load policy and language" block,
and three commands carried long sections that are needed only sometimes.

## Decision

1. **The command file is the one entry point per pipeline.** Names and count
   stay as upstream: ten commands, `/gatekit:<name>`. The ten skill shims are
   deleted.
2. **The command's `description` carries what the shim carried**: what it
   does, Korean and English trigger phrases, and the boundary to its nearest
   neighbour ("NOT for … — that is /gatekit:<other>"). At most 1024
   characters, no angle brackets.
3. **One preamble.** `.claude/gatekit/policy/preamble.md` holds language
   detection (from the spec, or from the input) and what follows from it.
   Each command's Step 0 names the preamble, which source to use, and the
   extra files that command reads.
4. **Steps needed only sometimes move to a reference doc that the command
   names together with when to read it**:
   `spec-kit/build-failures.md` (a failed or timed-out build task),
   `spec-kit/gate-criteria.md` (writing criteria),
   `docs/SETUP-REFERENCE.md` (reinstall, retry, winget codes, a broken CLI).
   Safety rules stay in the command itself: ask before installing, a
   reinstall or retry is a separate permission, never approve for the user.
5. **Tests cover the reference docs too.** `tests/test_command_docs.py`
   scans `policy/*.md` and `spec-kit/*.md` for the invocation form and
   bash-only syntax, and checks that every reference a command names exists.

## Consequences

- One listing per pipeline, and one description to keep true.
- Widening the test scan found reference docs that still called the POSIX
  launcher removed by ADR-0018 (`evaluator-brief.md`, `task-gates.md`,
  `language.md`). On Windows those commands could not run. They now use the
  uv form; the token gate's `argv` is the same invocation as a JSON list.
- `doctor.md` named Python 3.11 as the floor; it is 3.14 (ADR-0018).
- A command no longer reads top to bottom on its own: following it costs one
  extra file read at Step 0, and one more on a rare path.

## Not decided here

- The shell write gate matches only the `Bash` tool. `settings.json` turns
  the PowerShell tool on, and nothing reads PowerShell syntax
  (`Set-Content`, `Out-File`, `>`). Tracked separately.
- `uv run` without `--no-dev` installs the dev group (pyright, ruff) on the
  first command after setup, which built the `.venv` with `--no-dev`.
  Tracked separately.
