# ADR-0024: The stop gate reuses a contract run while nothing has changed

Status: accepted 2026-10-02. Closes the first open point of ADR-0023.

## Context

The Stop hook runs the completion contract every time a session in a `build`
or `verify` pipeline tries to end. That is the enforcement: "done" is what the
criteria say, not what the session says. It is also the slowest thing gatekit
does, and it repeated work whose answer was already known:

- `/gatekit-verify` runs the contract, writes `spec/PROGRESS.md`, and ends —
  and the Stop hook ran the same criteria over the same files a second time.
- During a build, a turn that only talks (a question, a status report) ended
  with a full run although no file had changed since the last one.

## Decision

1. **A finished run is recorded** in `.gatekit/runs/contract-last.json`: when
   it ran, the SHA-256 of `.gatekit/contract.json`, a fingerprint of the
   project tree, and the result. Both `contract run` (the CLI) and the Stop
   gate's own run record it. A CLI run cut short by `--budget` is not
   recorded.
2. **The Stop gate reuses the record** instead of running, when all hold:
   - the contract file is byte-identical to the one that ran;
   - the contract is not stale (`contract status` is `ok`);
   - the run is at most ten minutes old (`REUSE_MAX_AGE_S`);
   - the tree fingerprint is unchanged.
3. **The fingerprint** is a digest of every file's path, size and modification
   time under the project root. It skips caches and state that change without
   the work changing (`.git`, `.gatekit`, `node_modules`, `.venv`, `venv`,
   `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`) and the one
   file a verification writes after the run (`spec/PROGRESS.md`). A tree of
   more than 20,000 files is not fingerprinted and nothing is reused.
4. **The verdict does not matter.** An unchanged tree fails for the same
   reasons, so a recorded `fail` blocks with the recorded reasons.

## Why a fingerprint and not a "something was written" marker

A marker set by the write gates would miss what never passes through them: a
file the user edits in their own editor, a worker writing from another
session, a program started by name that writes on its own. The fingerprint
looks at the result — the files — so all of those invalidate the record.

## What this does and does not protect

The model can write under `.gatekit/` (it is on the spec allowlist, and the
ledger and the approvals live there), so gatekit already rests on the session
not forging its own state; this record is on the same footing and adds no
defence against forgery. What the design has to guarantee is narrower and is
what the tests pin: **an honest session cannot change something and then skip
the check by accident.** Any edit, any added or removed file, a re-derived
contract or a stale one, or ten minutes passing, runs the contract again.

## Known limits

- A change outside the tree (a database, a running server, a dependency in
  `node_modules` changed without its lock file) is seen only when the
  ten-minute window ends.
- The record belongs to the project, not to a session: a run from another
  session within the window is reused.
- Two writes to the same file that leave its size and modification time
  identical would go unseen; on NTFS the time has 100 ns resolution.
