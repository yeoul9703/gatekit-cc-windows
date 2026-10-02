# ADR-0023: One model; the main session owns verification

Status: accepted 2026-10-02. Supersedes ADR-0007 as the default and ADR-0013
decision 2. ADR-0003 and ADR-0015 describe a second model this fork does not
have and stay marked "not adopted".

## Context

`/gatekit-verify` was built around "producer is not evaluator": a separate
evaluator re-ran the whole completion contract and walked every check, the
main session ran the contract again to compare, and the Stop hook ran it a
third time. ADR-0013 decision 2 went further and looked for a backend whose
name differs from the host, so the grader would be a different model; with no
such backend the run carried an `evaluator_warning` ("the producer is grading
itself") that the skill had to show the user.

This fork serves people who have Claude Code and nothing else. For them the
warning appeared on every verification — the normal state was reported as a
defect — and there is no second subscription to make it go away.

The owner's objection went deeper than the warning. The main session holds
the most context. It should fix what "done" means together with the user, and
then ask others to check only what needs checking. Handing the whole job to a
second party that knows less, and distrusting the session that knows most,
has the roles the wrong way round.

## Decision

1. **The criteria are settled with the user before the code is written.**
   `/gatekit-gate` derives them, shows them, and pins the hash of
   `spec/05-gate.md` on approval; an edit expires the approval. This, not the
   identity of the grader, is what keeps a result from being bent to fit.
2. **The main session runs the contract once.** `contract run` is the verdict
   for every criterion that is a command. Nobody re-runs it for a second
   opinion.
3. **Only what a command cannot decide is handed out**: the look of a screen
   (`-visual`) and a check the gate file states in words. The main session
   lists those items and gives exactly that list to one read-only subagent,
   which did not see the building session. With no such item nothing is
   spawned.
4. **The reviewer is the host's read-only subagent by default**
   (`workers.evaluator_choice` returns `agent` with no warning). A project may
   still name a backend in `verify.evaluator`; it is used when it is enabled
   and has a `read_only_argv`, and a name that cannot review falls back to
   `agent` and says so.
5. **The main session writes `spec/PROGRESS.md`.** The reviewer writes
   nothing.

## Consequences

- One contract run in `/gatekit-verify` instead of two, and no agent at all
  for a project without screens or prose checks. The Stop hook still runs the
  contract when the session ends; that is the enforcement and is unchanged.
- A verification no longer starts with a warning on a one-model machine.
- The reviewer sees less: it is told the items, not asked to rediscover the
  job. A defect outside the criteria and outside the listed items is not
  looked for here. That is deliberate — the place to widen what is checked is
  the gate file, where the user approves it.
- `jobs evaluate` and the backend settings remain for a project that opts in;
  no skill sends a user there by default.

## Not decided here

- Whether the Stop hook may reuse a contract result from the same turn rather
  than run it again.
- Removing the backend machinery from the kernel.
