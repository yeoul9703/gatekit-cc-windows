# ADR-0022: A subagent's write scope is released when the agent ends; git global options; paths compared without case

Status: accepted 2026-10-02. Extends the spawn gate (ARCHITECTURE §3) with a
release hook, corrects the reading of `git` in ADR-0004 and ADR-0021
(decision 6, "`-C <dir>` and `-c <cfg>` skipped"), and replaces the known
limit "Path case" of ADR-0021. Doctor axis 2 now requires every gatekit hook,
which widens ADR-0021 decision 9.

## Context

**Scopes outlived their agents.** `gates/spawn.py` records the `write_scope`
of every subagent in the session ledger and refuses a spawn whose scope
intersects a recorded one. Nothing removed a record, so after the first round
of agents every later round over the same files was refused for the rest of
the session. The only way out was the manual
`ledger release-scopes --session <id> [owner]`.

Releasing automatically is only safe if the event that reports an agent's end
can be tied to the one record that agent's spawn created. Releasing the wrong
record — the scope of an agent that is still running — removes exactly the
protection the gate exists for. So the question was measured before anything
was written.

**Measurement** (2026-10-02, Windows 11, Claude Code 2.1.277, three
`claude -p` runs in a scratch folder outside this repository; hooks on
PreToolUse `Agent|Task`, PostToolUse `Agent|Task`, SubagentStart,
SubagentStop and Stop, each appending its stdin and a timestamp to a file and
returning no decision; the full record is `tmp/probe-subagent-stop.md`).
Five agents were spawned: one in the foreground, two in the background in one
message, one with `run_in_background` omitted, one more in the foreground.

A background agent, in the order the hooks fired (`t` is seconds since the
first event; the usual `transcript_path`, `cwd`, `prompt_id`,
`permission_mode` are left out here):

```json
{"t": 0.000, "hook_event_name": "PreToolUse", "session_id": "adde5114-…", "tool_name": "Agent",
 "tool_input": {"description": "probe-bg-a", "prompt": "…", "subagent_type": "general-purpose",
                "run_in_background": true},
 "tool_use_id": "toolu_01Pev69ATZ7soRgV9c7aKSWx"}
{"t": 0.105, "hook_event_name": "PostToolUse", "session_id": "adde5114-…", "tool_name": "Agent",
 "tool_response": {"isAsync": true, "status": "async_launched", "agentId": "a548d2c64c28c74d0",
                   "description": "probe-bg-a", "outputFile": "…"},
 "tool_use_id": "toolu_01Pev69ATZ7soRgV9c7aKSWx", "duration_ms": 6}
{"t": 0.105, "hook_event_name": "SubagentStart", "session_id": "adde5114-…",
 "agent_id": "a548d2c64c28c74d0", "agent_type": "general-purpose"}
{"t": 17.976, "hook_event_name": "SubagentStop", "session_id": "adde5114-…",
 "agent_id": "a548d2c64c28c74d0", "agent_type": "general-purpose", "stop_hook_active": false,
 "agent_transcript_path": "…\\subagents\\agent-a548d2c64c28c74d0.jsonl",
 "last_assistant_message": "…",
 "background_tasks": [{"id": "a548d2c64c28c74d0", "type": "subagent", "status": "running",
                       "description": "probe-bg-a", "agent_type": "general-purpose"}],
 "session_crons": []}
```

A foreground agent:

```json
{"t": 0.000, "hook_event_name": "PreToolUse", "session_id": "9875fe63-…", "tool_name": "Agent",
 "tool_input": {"description": "probe-fg", "prompt": "…", "run_in_background": false},
 "tool_use_id": "toolu_01ETcV4Cm1CDjmxAnvW1UDCr"}
{"t": 0.105, "hook_event_name": "SubagentStart", "agent_id": "add8155f3244355e0"}
{"t": 2.780, "hook_event_name": "SubagentStop", "session_id": "9875fe63-…",
 "agent_id": "add8155f3244355e0", "last_assistant_message": "DONE", "background_tasks": []}
{"t": 2.904, "hook_event_name": "PostToolUse", "session_id": "9875fe63-…", "tool_name": "Agent",
 "tool_response": {"status": "completed", "agentId": "add8155f3244355e0", "content": [...],
                   "totalDurationMs": 2801},
 "tool_use_id": "toolu_01ETcV4Cm1CDjmxAnvW1UDCr", "duration_ms": 2803}
```

What the five agents showed, without exception:

- (a) SubagentStop carries `agent_id` and nothing else that names the spawn:
  no `tool_use_id`, no description, no prompt. PostToolUse of the Agent call
  carries both `tool_use_id` and `tool_response.agentId`.
- (b) PreToolUse at spawn time carries `tool_use_id`, equal to the one in the
  PostToolUse of the same call. It carries no agent id (the agent does not
  exist yet). `description` and `prompt` are there but are not unique: two
  agents may be given the same ones.
- (c) For a **background** agent PostToolUse fires 3–9 ms after the launch,
  with `status: "async_launched"` and `isAsync: true`, while the agent is
  running. It does not fire again when the agent ends; only SubagentStop
  does. For a **foreground** agent PostToolUse fires after the agent has
  ended, with `status: "completed"`, and after that agent's SubagentStop.
  An Agent call with `run_in_background` omitted ran in the background.
- (d) Every event, SubagentStop included, carries the parent session's
  `session_id` — the key of the ledger the scope was recorded in.
- `tool_response.agentId` = SubagentStart `agent_id` = SubagentStop `agent_id`.
- SubagentStop's `background_tasks` still lists the background agent that is
  stopping as `running`, so it cannot be used to tell which agents have
  ended, and it is not read.

So there is an exact chain: `tool_use_id` (spawn) → `tool_use_id` + `agentId`
(PostToolUse) → `agent_id` (SubagentStop).

**`git -C dir apply x` passed the Bash gate.** `bash.py` took the first word
after `git` that does not start with `-` as the subcommand. With a global
option that takes a separate value that word is the value: `dir` is not a
working-tree subcommand, so `apply` was never looked at and the command was
allowed while a write rule was active. The PowerShell gate had its own loop
that skipped `-C`/`-c` and four long options, and it treated a quoted option
(`git '--no-pager' apply x`) as the subcommand, with the same result.

**Path case.** `write.matches` compared with `fnmatchcase`. On this kit's
only platform the file system ignores case, so a worker scoped to
`src/auth/**` that wrote `SRC/Auth/new.ts` was denied when `src/auth` did not
exist yet and allowed when it did (`realpath` restores the on-disk spelling of
the existing part only). ADR-0021 recorded this as a known limit.

**Doctor checked two of the twelve gate hooks.** `REQUIRED_PRETOOLUSE_GATES`
named the PowerShell and Skill matchers. A `settings.json` that had lost the
`Bash` matcher, or routed `Write|Edit` to the wrong gate, or dropped
`NotebookEdit` from a matcher, was reported `ok` as long as each event had
some hook.

## Decision

1. **The spawn gate stores the call's `tool_use_id` with the scope.**
   `Ledger.add_scope(owner, write_scope, tool_use_id=None)`. A scope recorded
   from an event without one (not observed) has no id and is only ever
   released by hand.
2. **`gates/release.py` releases a scope when its agent ends**, registered as
   PostToolUse `Agent|Task` → `_gate release` and SubagentStop →
   `_gate release`:
   - PostToolUse, `tool_response.status == "completed"` and not `isAsync`
     (foreground): release the scope whose `tool_use_id` equals the event's.
   - PostToolUse otherwise (background launch): release nothing; write
     `tool_response.agentId` on that scope as `agent_id`.
   - SubagentStop: release the scope whose `agent_id` equals the event's.
   - SubagentStop for an id no scope knows, while some scope has a
     `tool_use_id` and no `agent_id` yet: remember the id in the ledger's
     `ended_agents` (capped at 200). A PostToolUse that then names that id
     releases instead of binding. This is the foreground order, where
     SubagentStop comes first; it also covers a background agent whose
     SubagentStop would overtake its launch event, which was not observed.
3. **Nothing is matched by description, prompt, order or timing.** Each
   release is `Ledger.release_scope(key, value)` with `key` one of
   `tool_use_id` / `agent_id` and equality on the value. An event whose id
   matches no scope changes nothing, as do an event of another session,
   another tool, another hook event, and malformed input. Each of these is a
   test.
4. **The launch event never releases.** `isAsync` true keeps the scope even
   if `status` were to read `completed`.
5. **The hook never blocks.** It has no deny path and returns no payload; an
   internal error exits 0 through `hookio.run` with one line in
   `.gatekit/runs/hook-errors.log`. In a project without `.gatekit/`, or a
   session without a ledger file, it creates no state.
6. **`ledger.ScopeLock` around the two writers of `scopes`.** An agent ends
   at no particular moment of the parent's turn, so the release hook can
   overlap the spawn gate of the next call. Each loads the whole ledger and
   saves it, and the later save would write back a list without the other's
   change; a lost *add* would hide a scope from the conflict check. The lock
   is a file `.gatekit/runs/<session_id>.lock` created with
   `O_CREAT|O_EXCL`, waited for up to 2 s and taken over when older than 15 s
   (a hook's timeout is 10 s). The spawn gate goes on to judge the spawn even
   if it could not take the lock (a lock is not a reason to refuse or to wave
   through); the release hook changes nothing without it.
7. **`ledger release-scopes` stays** for a scope that is left behind, and the
   spawn gate's conflict message now says that: a scope is released when its
   agent ends; if the agent has ended and the scope is still there, run the
   printed command.
8. **One reader of git's global options.** `bash.git_subcommand_index(args)`
   returns the position of the subcommand among the words after `git`: a word
   in `bash.GIT_VALUE_FLAGS` (`-C`, `-c`, `--git-dir`, `--work-tree`,
   `--namespace`, `--super-prefix`, `--config-env`, `--attr-source`) is
   skipped together with the word after it; any other word starting with `-`
   is skipped alone, which covers `--no-pager`, `-p`, `--bare` and the
   attached spellings `--git-dir=<path>`, `--work-tree=<path>`. `--exec-path`
   is not a value flag: git takes its value attached only
   (`--exec-path[=<path>]`), and the PowerShell gate's old list, which had it,
   read `git --exec-path apply p` as the subcommand `p`. Both gates call this
   function; `powershell.py` has no list of its own. In the Bash gate a
   subcommand containing `$` or a backtick is now opaque, as a dynamic one
   already was in the PowerShell gate.
9. **Paths are compared without regard to case.** `write.fold` (lower case)
   is applied to both the path and the pattern in `write.matches` and
   `write.in_allowlist` — explicitly, not through `fnmatch.fnmatch`, so the
   verdict does not depend on the interpreter's platform. Scope of the
   change:
   - rule (b), the task scope: `SRC/Auth/x.ts` is inside `src/auth/**`, and a
     scope written `SRC/Auth/**` covers `src/auth/x.ts`;
   - rule (a), the allowlist: `SPEC/x.md`, `Docs/a.md`, `.GATEKIT/config.json`
     and `readme.MD` are the files their usual spellings name, and are
     writable as those are;
   - the Bash and PowerShell gates, which reach both rules through
     `write.decide_path`;
   - `ledger.globs_intersect`, which is the deny side of the same question:
     `SRC/Auth/**` now conflicts with `src/auth/**` at the spawn gate, and in
     `spec validate`'s check that two tasks' scopes do not overlap.

   This widens what is allowed, so the deny side was checked for a spelling
   that could slip through, and pinned with tests: both rules deny by "not
   in the list", and the list is folded the same way as the path, so a path
   outside the allowlist or the scope is outside it in every casing
   (`SRC/app.ts`, `Src/NOTES.MD`, `X/SPEC/a.md`, `SPECS/x.md`); a scoped
   worker is still refused `SPEC/01-prd.md`, `.GATEKIT/config.json` and
   `README.MD`; a read-only task is refused every spelling; a root given in
   another case is still the root. `write.py` has no rule that denies by
   matching a name (no protected-path list), so there is no deny pattern that
   a different casing could miss. The fixed paths the gate reads itself
   (`spec/`, `spec/05-gate.md`, `.gatekit/jobs/…/task.json`) are opened
   through the file system, which ignores case on its own.
10. **Doctor axis 2 requires every gatekit hook.** `doctor.REQUIRED_HOOKS` is
    the hook table as data — twelve `(event, matcher, gate)` rows, every
    registration except SessionStart. For a row with a matcher each tool in
    it must be covered by a group under that event that runs `_gate <gate>`;
    a missing one is `fail` and is named (`PreToolUse NotebookEdit (_gate
    write)`, `SubagentStop (_gate release)`). A test derives the same triples
    from the repository's `.claude/settings.json` and requires the two sets
    to be equal in both directions, so a hook added to one without the other
    fails the suite. `EXPECTED_HOOK_EVENTS` gains `SubagentStop`.
11. **Doctor axis 1 is named `gatekit files`** (was `plugin files`; the kit
    has not been a plugin since ADR-0018). Order and verdicts are unchanged.

## Consequences

- A second round of agents over the same files is allowed once the first
  round's agents have ended, with no manual step, for foreground and
  background agents alike. While an agent runs, its scope is still refused to
  others — a test spawns over a launched background agent's files and is
  denied until that agent's SubagentStop.
- Every Agent call now starts one more Python process after it returns, and
  every SubagentStop starts one, including for agents that declared
  `read-only` (their record is dropped the same way).
- A lock file appears beside the ledger for the few milliseconds of a spawn
  or a release.
- `git -C <dir> apply`, `git -c k=v checkout`, `git --git-dir=… reset` and
  the like are denied as opaque while a write rule is active, in both shells.
  `git -C <dir> status` and `git -c apply=1 log` stay allowed: the value of
  an option is not read as a subcommand.
- Scopes that differ only in case are now one scope: allowed for the writer
  who holds it, a conflict for a second agent or a second task that claims
  it.
- A `settings.json` that lost any gatekit hook fails doctor with the missing
  hook named. A project copied from an older checkout shows
  `PostToolUse Agent (_gate release)` and `SubagentStop (_gate release)`
  until its `settings.json` is restored from git.

## Known limits

- **Not measured:** an agent that fails, is killed, or whose tool call is
  interrupted (whether SubagentStop or PostToolUse fires at all); an agent
  spawned by a subagent (which `session_id` its events carry); an agent woken
  again by `SendMessage` after its SubagentStop (its scope is already
  released, and a second SubagentStop finds nothing); a Claude Code version
  whose tool is named `Task` (the measured name is `Agent`; the hook accepts
  both, as the spawn gate does); an interactive session rather than
  `claude -p`. In each of these the failure this design allows is a scope
  that stays recorded — the state before this ADR, cleared with
  `ledger release-scopes` — except the `SendMessage` case, where a resumed
  agent writes without a recorded scope.
- **Foreground release rests on `status: "completed"`.** A foreground call
  that returns with another status is bound, not released, and is then
  released only if its SubagentStop was already seen (`ended_agents`).
- **The lock covers the spawn gate and the release hook only.** The prompt,
  skill, question and stop gates also load and save the whole ledger and do
  not take it; one of them overlapping a spawn or a release can still write
  back an older `scopes` list. They run at turn boundaries and around
  AskUserQuestion and Write calls, so the overlap needs an agent to end
  within the few milliseconds one of them holds the ledger. Closing it means
  locking every gate's save, which was left out of this change.
- **Two releases that both wait out the 2 s lock** leave the later one's
  scope recorded.
- **Case folding is `str.lower()`**, not the file system's own table; the two
  differ for a handful of non-ASCII letters. NTFS can also be switched to
  case-sensitive per directory, where two spellings are two files and this
  gate treats them as one.
- **git:** an option this list does not know that takes a separate value
  (none in git 2.54) would make its value read as the subcommand. An alias
  defined with `-c alias.x=apply` and then called (`git -c alias.x=apply x`)
  is read as the subcommand `x`.
- ADR-0021's text still describes the PowerShell gate's own `-C`/`-c` skip
  and the path-case limit; this ADR is the current statement of both.
