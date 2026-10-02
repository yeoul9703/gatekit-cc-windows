# gatekit architecture contract

This file is the single source of truth for module boundaries, file formats and
vocabulary. Every module, command, hook and test must agree with it. If an
implementation needs to deviate, change this file first (with an ADR in
`docs/decisions/`) and then the code.

**This repository runs gatekit standalone, for Claude Code only.** There is no
plugin manager and no second host (the upstream Codex host layer was not adopted; ADR-0018): opening
this folder in Claude Code is enough — hooks are registered directly in the
project's own `.claude/settings.json`, and each pipeline is a skill folder
under `.claude/skills/`. Sections below describe that standalone layout;
where an ADR still describes the old plugin-distributed, multi-host design,
this file's description of the current layout wins.

gatekit is a **clean-room** implementation. It borrows *patterns* that are
common engineering practice (hook-enforced gates, assumption ledgers,
hash-anchored approvals, executable completion contracts, worker job
directories) but contains no code copied from any other project.

## 0. Non-negotiables

| Rule | Why |
|---|---|
| Windows + Claude Code only; Python 3.14+ (`requires-python >=3.14`, `.python-version` 3.14) managed by uv; kernel code uses the standard library only, zero runtime dependencies (ADR-0018, ADR-0002) | the only prerequisites are Claude Code and uv; no `pip install` step exists |
| One kernel package (`.claude/gatekit/gatekit/`), reached via `.claude/gatekit/bin/gatekit.py` run by `.claude/gatekit/.venv/Scripts/python.exe` | no plugin manager; hooks are shell-less exec-form commands (ADR-0018) |
| Gates are hooks, not prose | prose instructions fire nondeterministically; hooks fire every time |
| Every hook exits 0 on any internal error and writes a one-line diagnostic to `.gatekit/runs/hook-errors.log` | a broken hook must never break the user's session |
| Verdict vocabulary is exactly `ok / warn / fail / unverified` | "not checked" must never be rounded to pass or fail |
| No absolute personal paths anywhere in the repo | keeps the checkout portable across machines |
| `.claude/skills/gatekit-<name>/SKILL.md` is the only entry point per pipeline (`/gatekit-<name>`); its `description` carries the Korean and English triggers, steps needed only sometimes live in that skill's `references/`, templates and data in its `assets/`, and what several skills share in `.claude/skills/gatekit-shared/` (ADR-0020) | one listing per pipeline; a `SKILL.md` stays short enough to follow, and everything a skill uses sits beside it |
| `SKILL.md` and reference docs never tell the model to read `docs/` | `docs/` is written for people; what the model needs lives in the skill folder |
| Data (templates, heading maps, presets, schemas) lives in JSON/Markdown files, not in prompt prose | keeps prompts small and data diffable |
| Any file > 1 MB fails CI | no committed corpora |
| Output language follows `output_lang` (see §8); Korean is never a default | open-source posture |

## 1. Repository layout

```
<project root>/
├── .claude/
│   ├── settings.json                    # 6 hook events (SessionStart, UserPromptSubmit, PreToolUse x5, PostToolUse x2, PreCompact, Stop), exec form (see §3)
│   ├── skills/                          # one folder per pipeline, /gatekit-<name> (ADR-0020)
│   │   ├── gatekit-discover/   SKILL.md  references/discovery-summary.md  assets/{ko,en}/00-discovery.md      → spec/00-discovery.md (optional first step)
│   │   ├── gatekit-interview/  SKILL.md  references/interview-subjects.md, domain-research.md  assets/{ko,en}/01-prd.md, 03-architecture.md   → spec/01-prd.md, spec/03-architecture.md
│   │   ├── gatekit-mockup/     SKILL.md  references/prototype-gate.md  assets/{ko,en}/02-screens.md           → spec/02-screens.md, spec/tokens.json, ledger gaps, optional preview (ADR-0011)
│   │   ├── gatekit-design/     SKILL.md  assets/{ko,en}/02-design.md                                          → spec/02-design.md, spec/tokens.json, spec/design/, gap entries in ledger
│   │   ├── gatekit-tasks/      SKILL.md  references/task-gates.md  assets/{ko,en}/04-tasks.md                 → spec/04-tasks.md
│   │   ├── gatekit-gate/       SKILL.md  references/gate-criteria.md  assets/{ko,en}/05-gate.md               → spec/05-gate.md, .gatekit/contract.json, approvals
│   │   ├── gatekit-build/      SKILL.md  references/build-failures.md  assets/{ko,en}/PROGRESS.md, RECOVERY.md → worker jobs over spec/04-tasks.md
│   │   ├── gatekit-verify/     SKILL.md  references/evaluator-brief.md  assets/design-antipatterns.json       → independent E2E + report check
│   │   ├── gatekit-doctor/     SKILL.md
│   │   ├── gatekit-setup/      SKILL.md  references/install-programs.md, settings.md, rare-paths.md           → config, default worker check
│   │   └── gatekit-shared/              # not a skill (no SKILL.md): what several skills and the kernel share
│   │       ├── references/preamble.md language.md questioning.md conversation.md assumptions.md verification.md   # preamble.md is every skill's Step 0
│   │       └── assets/heading-map.json (canonical headings per file per language), presets/design/*.json
│   └── gatekit/                         # the standalone kernel checkout
│       ├── bin/
│       │   └── gatekit.py               # entry point: sys.path bootstrap, then cli.main
│       ├── pyproject.toml, uv.lock      # requires-python >=3.14, no runtime deps, [tool.uv] package=false, dev group pyright[nodejs]+ruff
│       ├── .venv/                       # built by uv from uv.lock (ignored)
│       ├── scripts/                     # setup.ps1 (check/-Install/-Update/-Reinstall/-RetryFailed/-Status), packages.json (single source of winget ids, script urls, minimum versions), session-check.ps1 (SessionStart), verify.ps1
│       ├── gatekit/                     # kernel package (stdlib only)
│       │   ├── cli.py         dispatcher: `bin/gatekit.py <sub>`; `_gate <name>` dispatches to a gate module
│       │   ├── hookio.py      hook stdin/stdout contract, safe wrapper (§3)
│       │   ├── ledger.py      per-session run ledger
│       │   ├── lang.py        output_lang detection
│       │   ├── verdict.py     4-state vocabulary + aggregation
│       │   ├── contract.py    completion contract derive/validate/run
│       │   ├── approval.py    hash-anchored approvals
│       │   ├── spec.py        spec set validation
│       │   ├── jobs.py        job runner (job dir, atomic writes, spawn, gates, redelegate)
│       │   ├── workers.py     worker backends (claude default; a project may add more)
│       │   ├── doctor.py      8-axis diagnosis
│       │   ├── config.py      .gatekit/config.json loader with defaults
│       │   ├── paths.py       project root / gatekit root resolution; skills_root() and skill_dir(name) locate templates, heading-map and presets
│       │   └── gates/         hook entry points: prompt.py write.py bash.py powershell.py spawn.py release.py skill.py question.py compact.py stop.py
│       └── tests/                       # unittest, run with: cd .claude/gatekit; uv run --frozen python -m unittest discover -s tests
├── docs/ARCHITECTURE.md (this), decisions/ADR-*.md, USAGE.md, SETUP-REFERENCE.md   # for people, see §1a
└── .gitignore                           # ignores .gatekit/runs, .gatekit/jobs
```

### 1a. Who reads which document

| Location | Reader | Language | Holds |
|---|---|---|---|
| `.claude/skills/gatekit-<name>/SKILL.md` | the model | English | the entry point: step order, safety rules, the next command |
| `.claude/skills/gatekit-<name>/references/` | the model | English | detail one step of that skill reads only when it needs it; the first lines say when to read it |
| `.claude/skills/gatekit-<name>/assets/` | the model and the kernel | Korean and English | material for the output: templates, presets, JSON data |
| `.claude/skills/gatekit-shared/` | the model and the kernel | — | rules and data several skills use |
| `docs/` | people | Korean (this file and the ADRs are English) | `USAGE.md`, `SETUP-REFERENCE.md`, `ARCHITECTURE.md`, `decisions/` |

A `SKILL.md` or a reference doc never names a `docs/` file as something to
read; it may tell the user that a guide exists. Folders this layout replaced
and that no longer hold anything: `.claude/commands/`, the kernel's `policy`
folder and its template-and-reference folder (ADR-0020). Scripts stay in
`.claude/gatekit/scripts/`: the SessionStart hook, setup and verify share them.

## 2. Project state layout (inside the user's project)

```
<project>/
├── spec/                       # human-reviewed, committed
│   ├── 00-discovery.md         # optional; ```gatekit-discovery JSON fence (§6a)
│   ├── 01-prd.md               # includes "## Assumption Ledger" / "## 가정 원장"
│   ├── 02-screens.md
│   ├── 02-design.md            # optional; patterns, components, tokens summary (ADR-0008)
│   ├── 03-architecture.md
│   ├── 04-tasks.md             # tasks as ```gatekit-task JSON fences (§6)
│   ├── 05-gate.md              # criteria as ```gatekit-criterion JSON fences (§5)
│   ├── RECOVERY.md
│   ├── PROGRESS.md
│   ├── tokens.json             # optional, from mockup or design pipeline
│   └── design/                 # optional; captures cited as evidence by 02-design.md (ADR-0008)
│       └── preview-<project>.html   # optional; drawn from the spec, never evidence (ADR-0011)
└── .gatekit/
    ├── config.json             # committed. see §9
    ├── approvals.json          # committed. see §7
    ├── contract.json           # derived from 05-gate.md by `gatekit contract derive`
    ├── runs/<session_id>.json  # ignored. ledger (§4)
    ├── runs/hook-errors.log    # ignored
    ├── attempts.json           # committed. per-task consecutive-failure counts (ADR-0014)
    └── jobs/<job_id>/          # ignored. see §10
```

`paths.project_root(cwd)` = nearest ancestor containing `.gatekit/` or `.git/`, else cwd.

**Design preview (ADR-0011).** When `/gatekit-mockup` runs with no design
source, its one `AskUserQuestion` offers a preview instead of a gap question
(a stop signal suppresses both). On a yes it writes
`spec/design/preview-<project>.html` from `02-screens.md` plus `tokens.json`:
static, tokens-only — a value the tokens lack is drawn as a labelled
placeholder, never invented — and opening with a banner saying the screens
were drawn from the spec, not observed. The user's corrections are applied to
**`spec/02-screens.md`**, not to the HTML, and the preview is redrawn from it;
that file is what §10 pushes into worker briefs. No approval is recorded and
no assumption closes. A preview path must never appear in an evidence cell of
`02-screens.md` or `02-design.md` — `spec.validate` fails on it, and
`/gatekit-design` refuses one as input — because a drawing made from the spec
cannot be evidence for the spec.

## 3. Hook I/O contract (`hookio.py`)

Claude Code passes a JSON object on stdin to the hook command from
`.claude/settings.json`. Hooks use the shell-less exec form (`command` plus
`args`, no shell in between; ADR-0018). Every gate command is
`${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe` with args
`bin/gatekit.py _gate <name>` (about 105 ms per call). `_gate` imports the
named gate module and runs it against this same process's stdin — so a gate
reads its event exactly as it would running as a standalone script
(`python .../gatekit/gates/write.py`), which `gates/_bootstrap.py` also still
supports directly. The exception is SessionStart, which runs
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File
scripts/session-check.ps1` (see below). Fields used:
`session_id`, `hook_event_name`, `cwd`, `tool_name`, `tool_input`, `tool_response`,
`tool_use_id` (PreToolUse and PostToolUse of `Agent|Task`), `agent_id`
(SubagentStop), `prompt` (UserPromptSubmit), `stop_hook_active` (Stop).

Responses:

| Event | Allow | Block |
|---|---|---|
| UserPromptSubmit | exit 0; optional stdout JSON `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"…"}}` | not used |
| PreToolUse | exit 0 | stdout JSON `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"…"}}`, exit 0 |
| PostToolUse | exit 0 | not used |
| SubagentStop | exit 0 | not used |
| Stop | exit 0 | stdout JSON `{"decision":"block","reason":"…"}`, exit 0. Never block when `stop_hook_active` is true. |

`hookio.run(handler)` reads stdin, calls `handler(event: dict) -> dict | None`,
prints the returned JSON (if any), and **always exits 0**; exceptions are
appended to `.gatekit/runs/hook-errors.log` as one line `iso_ts event_name error`.
Each gate must complete in < 5 s on a normal project. The Stop gate runs the
contract (§5) and is the exception: its hook `timeout` in `.claude/settings.json` is
600 s, the largest value the Claude Code hook documentation shows, and the
gate caps the contract run at `STOP_BUDGET_CAP_S` = 570 s (`gates/stop.py`)
so start-up and teardown fit inside the timeout. A `gatekit-budget` above the
cap runs in full under `contract run` but is cut at the Stop gate, where the
cut is reported as `unverified` — honest, where a hook killed by Claude Code
would record no verdict and no log line. Tests pin `settings.json` to
`STOP_HOOK_TIMEOUT_S` and the cap to at least 30 s below it.

Registered hooks (`.claude/settings.json`, seven events, exec form, gates
calling `bin/gatekit.py _gate <name>`): SessionStart→`scripts/session-check.ps1`
(not a gate), UserPromptSubmit→`prompt`,
PreToolUse `Write|Edit|MultiEdit|NotebookEdit`→`write`,
PreToolUse `Bash`→`bash` (ADR-0004),
PreToolUse `PowerShell`→`powershell` (ADR-0021; the `Bash` matcher does not
fire for a PowerShell call, so it is its own entry),
PreToolUse `Agent|Task`→`spawn`, PreToolUse `Skill`→`skill` (ADR-0021),
PostToolUse `AskUserQuestion`→`question`,
PostToolUse `Write|Edit|MultiEdit|NotebookEdit`→`question` (clears
`awaiting_write`), PostToolUse `Agent|Task`→`release` and
SubagentStop→`release` (ADR-0022), PreCompact→`compact`, Stop→`stop`.
`doctor.REQUIRED_HOOKS` is this list as data (every row but SessionStart), and
a test holds it equal to `settings.json` in both directions.

Gate behaviour:

Every gate stands down in a project that has no `.gatekit/` directory. The
hooks live in this repository's own `.claude/settings.json`, but the
`.claude/` folder can be copied into other projects, and a project with no `.gatekit/` has never run a gatekit command and
never asked to be governed. Such a gate allows without reading further and
**creates no state there** — no ledger, no `.gatekit/`. The one exception is
`compact`, which already writes nothing when no job exists.

**SessionStart check.** A hook whose `command` points at an executable that
does not exist is silently ignored by Claude Code (measured), so a missing
`.venv` or uv would leave every gate off with no message. `session-check.ps1`
runs at session start, verifies uv, the `.venv` (including that its
`pyvenv.cfg` `home` still exists) and the `claude` CLI, and prints a warning
pointing at `/gatekit-setup` when something is missing. It targets under 10 s.

- **prompt**: ensure ledger exists for `session_id`; detect `output_lang` from `prompt` (§8) and store it — for a slash command only the `<command-args>` content is the user's words, and empty args keep the stored language; **set `active_pipeline`** when the prompt invokes `/gatekit-<pipeline>`. The hook receives a typed slash command as the bare text `/gatekit-<name> args` (measured, ADR-0021); that form at the start of the prompt, the tagged form the session transcript stores (`<command-name>/gatekit-<name></command-name>` with `<command-args>…</command-args>`), and the `# /gatekit-<name>` title line of an expanded skill body are recognised within the first 12 lines. A mid-sentence mention is not an invocation. `doctor` and `setup` clear it; an unknown name leaves it alone; a plain prompt keeps it. Entering a different pipeline resets `questions` to its defaults. `active_pipeline` has two production writers, this gate and the `skill` hook below, and both go through `prompt.apply_name` — skills never set it by prose. Inject `additionalContext` (≤ 600 chars) with `output_lang`, question budget state, active pipeline, and unresolved gate count, plus `build=<job> n/m passed, next: <task>` while a job is unfinished (ADR-0013 decision 1a: the session that returns from a compaction is told a build is live and reads `spec/PROGRESS.md` for the rest). The question field is `questions=<asked>/<max>`, followed by the ADR-0012 signals when any is non-zero — `questions=6/2 (2 unjustified, 1 repeat, impl-choice)` — printing only what is set so the 600-char budget holds. Never blocks.
- **write**: deny when (a) `config.enforce_spec_before_code` is true, `spec/` exists, `.gatekit/approvals.json` has no valid approval for `spec/05-gate.md`, and the target path is outside the allowlist `spec/**, .gatekit/**, docs/**, README*, *.md at root`; or (b) env `GATEKIT_TASK_ID` is set and the target is outside that task's `write_scope` (from the job's `task.json`). **Case is ignored** in every path comparison of this gate (ADR-0022): the kit is Windows-only, so `SRC/Auth/x.ts` and `src/auth/x.ts` are one file and get one verdict. `write.fold` lower-cases both the path and the pattern in `matches` and `in_allowlist`, so the fold applies to the allowlist of rule (a) and the scope of rule (b) alike, and to the Bash and PowerShell gates, which judge through `write.decide_path`. Nothing denied in lower case is allowed in another spelling: a path outside the allowlist or the scope stays outside it however it is cased. Reason text is in `output_lang`.
- **bash**: apply the write rules (a) and (b) to every file a Bash command would write, read statically from the command text: redirections (`>`, `>>`, `&>`, `>|`, `N>`), `tee`, `sed -i`/`perl -i`, `cp`/`mv`/`ln`/`install`/`rsync` destinations, `touch`/`rm`/`mkdir`/`truncate`/`chmod`/`chown` operands, `dd of=`, `sort -o`, `curl -o`, `wget -O`, `tar -C`/`-f`, `unzip -d`, `zip`, with `cd` tracked across `;`/`&&`/`||`/`|`/newlines, `VAR=`/`sudo`/`env`/`nohup` prefixes stripped, here-document bodies ignored, `/dev/*` targets ignored and `sh|bash|zsh -c "…"` parsed recursively. Fast path: when no rule could deny anything (no `GATEKIT_TASK_ID`, spec gate approved or absent) the command is allowed without parsing. When a rule is active and a write's target **cannot be determined** — `$VAR` or backticks in a path, `cd` to an unknown directory, `eval`, `xargs`, `patch`, `trap`, `find -exec/-delete`, working-tree `git` subcommands (`apply`, `checkout`, `restore`, `reset`, `merge`, `stash`, `init`, `clone`, …; the subcommand is found by `bash.git_subcommand_index`, which skips git's global options — `-C <path>`, `-c <name=value>`, `--git-dir`/`--work-tree`/`--namespace` with a separate or attached value, `--no-pager` and any other word starting with `-` — so `git -C dir apply x` is read as `apply`, ADR-0022; a subcommand that is a variable is opaque), inline interpreter code (`python -c`, `node -e, `perl -e`, stdin scripts), `awk`, command-line editors (`ed`, `ex`, `vim`, `nano`), `busybox`, downloads that choose their own file name (`curl -O`, bare `wget`), process substitution, unbalanced quotes — **deny** with reason `opaque`: "could not tell" is never rounded to "allowed". Programs invoked by name (`npm run build`, `python script.py`) are outside its reach by design. Reason text is in `output_lang`.
- **powershell** (ADR-0021): the `bash` gate for the PowerShell tool — same fast path, same `write.decide_path` verdict per target, same `opaque` denial, through the shared `bash.judge_command`; only the reading of the command text differs. Read statically: statements split at `;`, newline, `|`, `&&`, `||`; single quotes, double quotes, backtick escapes and here-strings (`@'…'@`, `@"…"@`, whose body is data); redirections `>`, `>>`, `N>`, `N>>`, `*>` (a target of `$null` or `NUL` and a merge such as `2>&1` are not writes); and the path arguments of `Set-Content` (`sc`), `Add-Content` (`ac`), `Clear-Content` (`clc`), `Out-File`, `Tee-Object` (`tee`), `New-Item` (`ni`, `mkdir`, `md`; `-Path` joined with `-Name`), `Set-Item` (`si`), `Copy-Item` (`cp`, `copy`, `cpi`; destination), `Move-Item` (`mv`, `move`, `mi`; source and destination), `Remove-Item` (`rm`, `del`, `erase`, `rd`, `ri`, `rmdir`), `Rename-Item` (`ren`, `rni`; old and new name), `Export-Csv`, `Export-Clixml` and other `Export-*` with a named path, `Start-Transcript`, `Compress-Archive`/`Expand-Archive` `-DestinationPath`, `Invoke-WebRequest`/`Invoke-RestMethod` `-OutFile`, `curl -o`. Each of those cmdlets has a parameter table (names, aliases, switches, positions), and a word is bound the way PowerShell binds it: names are case-insensitive, `-Name:value` is accepted, and a shortened name (`-Lit`) resolves when exactly one parameter matches, the cmdlet's own winning over a common one. `Set-Location`/`cd`/`Push-Location` are tracked; script blocks, `(…)`, `$(…)` and `@{…}` are read as nested statements; `Env:`, `Variable:`, registry and certificate drives are not project writes. Paths are Windows paths resolved with `ntpath` against the event's `cwd` (either separator, drive letter upper-cased, trailing dots and spaces dropped) and handed to `write.decide_path` as absolute paths. **Opaque**, hence denied while a rule is active: a variable, subexpression, splat or control-character escape in a path; a wildcard in a path unless it is `-LiteralPath`; `-Include`/`-Exclude`/`-Filter`; an unknown or ambiguous parameter (it may or may not consume the next word); a target that arrives through the pipeline; a drive-relative path, an unknown PowerShell drive or an alternate data stream; `Invoke-Expression`, `Invoke-Command`, `Start-Process`, `Start-Job`, `Invoke-Item`, `Add-Type`, `Set-Alias`/`New-Alias` and a write to the `Alias:` or `Function:` drive (a new command name would hide a write cmdlet), `New-PSDrive`; the call operator `&` or dot-sourcing on a variable or a script block; a .NET static call or `New-Object` outside a short list of pure types (`[System.IO.File]::WriteAllText`), and an instance method call outside a short list of string and collection methods (`$doc.Save(…)`); inline interpreter code (`python -c`, `node -e`, `pwsh -Command`, `powershell -EncodedCommand`, `cmd /c`, `bash -c`, an interpreter reading its script from stdin); the `git` subcommands in `bash._GIT_OPAQUE`, found with the Bash gate's own `git_subcommand_index` (one reader of git's global options for both gates); Unix and Windows file tools reachable from a PowerShell prompt whose arguments this gate does not read (`sed -i`, `tar`, `robocopy`, `xcopy`, `curl -O`, …); unbalanced quotes or brackets; and any fault inside this reader itself, which is caught and reported as opaque so that it is not turned into an allow by `hookio.run`. Programs invoked by name (`npm run build`, `python script.py`, `uv run …`, `pwsh -File x.ps1`) are outside its reach by design. Reason text is in `output_lang`.
- **spawn**: the spawn prompt must contain a fenced block ` ```gatekit-scope ` with JSON `{"write_scope": [globs] | "read-only", "stop_when": "…", "tools": [...] | "inherit"}`. Deny if missing/invalid, or if `write_scope` intersects any scope already recorded in the ledger for this session. Scopes are compared without regard to case (`ledger.globs_intersect`), so `SRC/Auth/**` conflicts with `src/auth/**`. On allow, record the scope in the ledger together with the call's `tool_use_id`. The scope is dropped by the `release` hook when its agent ends; one left behind (an agent that failed or was stopped) is released by hand with `gatekit.py ledger release-scopes --session <id> [owner]`, and the denial message prints that command. The load-check-save runs under `ledger.ScopeLock`. No regex over prose: parse the fence as JSON.
- **release** (PostToolUse `Agent|Task` and SubagentStop, ADR-0022): drops the scope of the agent that has ended, and only that one. The chain is equality on identifiers Claude Code issues (measured): the spawn gate stored `tool_use_id`; PostToolUse of the same call carries that `tool_use_id` and `tool_response.agentId`; SubagentStop carries `agent_id`. A **foreground** agent's PostToolUse fires after the agent has ended (`tool_response.status = "completed"`): release the scope with that `tool_use_id`. A **background** agent's PostToolUse fires a few milliseconds after the launch (`status = "async_launched"`, `isAsync = true`): release nothing, write `agentId` on the scope, and release when SubagentStop arrives with that `agent_id`. A SubagentStop whose id matches no scope while a scope still has no agent id is kept in `ended_agents` (a foreground agent's SubagentStop precedes its PostToolUse), and a PostToolUse that names an id in that list releases at once. There is no matching by description, prompt or timing: an identifier that matches no scope releases nothing. The change runs under `ledger.ScopeLock`; if the lock cannot be taken within 2 s nothing changes. Appends a `scope_released` event. **Never blocks**: no payload on any input, exit 0 on an internal error; no `.gatekit/` or no ledger for the session means no state is created.
- **skill** (PreToolUse `Skill`, ADR-0021): when the model starts a skill itself — the user asked in plain words, so the prompt names no skill and the prompt gate sees nothing — the only trace is a `Skill` tool call with `tool_input.skill` = `gatekit-<name>`. The hook takes the name with `prompt.skill_command` (the whole string must be `gatekit-<name>`, built from the same pattern the prompt gate matches) and applies `prompt.apply_name`: a pipeline sets `active_pipeline`, `doctor` and `setup` clear it. Any other skill, an unknown `gatekit-` name and malformed input are ignored without touching the ledger. It appends a `skill` event and **never blocks**: it returns no payload on any input. A typed `/gatekit-<name>` does not reach this hook (no `Skill` tool call is made), so the two writers never both fire for one invocation.
- **compact** (PreCompact, ADR-0013): stamp the latest job's state — job id, execution mode, backend, and every task's state, gate tally and detail — into `spec/PROGRESS.md` between `<!-- gatekit:build-state -->` and its closing marker, replacing that block in place so repeated compactions leave one stamp and nothing outside it is touched. The heading belongs to neither language's canonical set, so `spec validate` is unaffected. Writes nothing when no job exists; an unwritable file is swallowed, since the job dir still holds every fact. Under host execution a build lives in one session, so a compaction is routine: this hook records the narrative, which is the only thing the files did not already hold.
- **question**: increment `ledger.questions.asked`; if `asked > budget.max_calls` (default 2 for interview, unlimited otherwise) record `budget_exceeded=true` (informational; commands read it). ADR-0012 adds four signals, all informational and all confined to the budgeted pipeline, because a raw count permits waste inside the budget and forbids value outside it. Past `max_calls` a call must arrive with `questions.justification` — one line naming what the command would write differently depending on the answer — which the call **consumes** (set to `null`); a call without one raises `unjustified`. A justified call sets `awaiting_write`, and if the next `AskUserQuestion` arrives with it still set, `unrealized` is raised: the claim that the answer changes what gets written did not come true. The same gate is therefore also registered on **PostToolUse for `Write|Edit|MultiEdit|NotebookEdit`**, where it only calls `note_write` (clearing `awaiting_write`) and never counts a question — PreToolUse could not serve, since a write it sees may still be denied. Independently of the budget, each question's `header` + `question` is reduced to a content-word fingerprint (noise words dropped, ≥ `REPEAT_MIN_WORDS` 3 words) and compared against `questions.asked_topics` (last 50): overlap ≥ `REPEAT_OVERLAP` (0.7) of the smaller set raises `repeated` and records `repeat_of`. A call whose options are **all** code tokens (path, `call()`, dotted filename, `snake_case`, `camelCase`) sets `implementation_choice` — a `warn`-grade signature of handing the user a decision the command owned, never a verdict, since a question about implementation is sometimes right.
- **stop**: if `.gatekit/contract.json` exists and the ledger's `active_pipeline` is `build` or `verify`: run the contract (§5). On any `fail` or `unverified` criterion and `block_count < 3` and not `stop_hook_active`: block with a reason listing failing criteria; increment `block_count`. Otherwise allow and record `final_verdict` in the ledger (never a blank). The run is skipped when its answer is already known: a run recorded in `.gatekit/runs/contract-last.json` within the last ten minutes is reused while the contract file and the tree fingerprint (every file's path, size and modification time, caches and `spec/PROGRESS.md` aside) are unchanged — so a turn that changed nothing, or a `/gatekit-verify` that has just run the contract, does not run it twice (ADR-0024).

## 4. Session ledger (`ledger.py`)

`.gatekit/runs/<session_id>.json`, written atomically (tmp + `os.replace`).
Resolution is **strictly by session_id**; there is no "most recent file"
fallback. Schema (version 1):

```json
{
  "version": 1,
  "session_id": "…",
  "created_at": "iso", "updated_at": "iso",
  "output_lang": "ko|en",
  "active_pipeline": null | "discover" | "interview" | "mockup" | "design" | "tasks" | "gate" | "build" | "verify",
  "questions": {"asked": 0, "max_calls": 2, "budget_exceeded": false,
                "justification": null, "awaiting_write": false,
                "unjustified": 0, "unrealized": 0,
                "repeated": 0, "repeat_of": null,
                "implementation_choice": false,
                "asked_topics": [["word", "word"]]},
  "scopes": [{"owner": "agent-label-or-prompt-hash", "write_scope": ["src/auth/**"], "declared_at": "iso",
              "tool_use_id": "toolu_…", "agent_id": "…"}],
  "ended_agents": ["agent-id"],
  "stop": {"block_count": 0, "final_verdict": null, "last_reasons": []},
  "events": [{"ts": "iso", "kind": "…", "detail": {}}]
}
```

`events` is append-only, capped at 500 (oldest dropped).

A scope's `tool_use_id` is the id of the Agent/Task call that declared it
(absent when the event carried none) and `agent_id` is written once the
PostToolUse of a background launch names the agent; the `release` hook drops
the entry by either one (§3, ADR-0022). `ended_agents` holds agent ids whose
SubagentStop arrived before any scope knew the id, capped at 200. The spawn
gate and the release hook change `scopes` under `ScopeLock`, a lock file
`.gatekit/runs/<session_id>.lock` taken with `O_CREAT|O_EXCL`, waited for up
to 2 s and taken over when older than 15 s: an agent can end at any moment of
the parent's turn, and without the lock the later of two overlapping saves
would write back a list that lacks the other's change. The other gates
(prompt, skill, question, stop) do not take the lock.

## 5. Completion contract (`contract.py`)

Criteria are declared in `spec/05-gate.md` as fenced JSON blocks:

````
```gatekit-criterion
{"id": "tests-pass", "argv": ["python", "-m", "unittest", "discover"], "expect": {"exit": 0}, "timeout_s": 30, "artifacts": ["reports/junit.xml"]}
```
````

`gatekit contract derive` parses all fences into `.gatekit/contract.json`:

```json
{"version": 1, "source_sha256": "<sha of 05-gate.md>", "criteria": [ … ], "derived_at": "iso",
 "inputs": {"spec/02-screens.md": "<sha256 or \"\">", "spec/02-design.md": "<sha256 or \"\">", "spec/tokens.json": "<sha256 or \"\">"}}
```

`inputs` (ADR-0008) records the sha256 of the design files at derive time;
an absent file hashes to `""`. These are contract inputs, not the contract
itself: `contract status` is `ok` only when both `source_sha256` and every
entry in `inputs` still match the file on disk, and `fail` when any of them
differs, naming the changed file. There is no new verdict for this — a
changed design input makes the contract stale exactly as a changed
`05-gate.md` does, and the fix is the same: re-derive, then re-approve.

`gatekit contract run [--json]` executes each criterion with `subprocess.run`
(no shell), `cwd` = project root, per-criterion timeout = `min(timeout_s, remaining)`
within a run-wide budget. That budget defaults to 45 s and may be raised by a
single optional fence in `spec/05-gate.md`, capped at 600 s:

````
```gatekit-budget
{"total_budget_s": 180}
```
````

`derive` stores it as `total_budget_s` in `.gatekit/contract.json`; `execute`
uses it unless an explicit argument (`--budget`) overrides it. The cap exists
because the Stop gate runs this: a check that can outlast the user's patience
is worse than one that reports `unverified` and stands down. A declared budget
that is absent, non-numeric, zero, negative, duplicated, or above the cap is a
`derive` error. Result per criterion:
`{"id", "verdict": "ok|fail|unverified", "exit", "elapsed_s", "stdout_tail", "stderr_tail", "artifact_hashes": {path: sha256}}`.
`expect` may say more than the exit code: `stdout_contains` /
`stdout_not_contains` / `stderr_contains` / `stderr_not_contains` take a
string or a list of strings (all must hold), `stdout_regex` / `stderr_regex`
one pattern searched with `re.MULTILINE`. Output expectations are judged over
the whole stream, not the stored tail, after the exit code; an unmet one is
`fail` with the expectation named in `stderr_tail`. An unknown `expect` key, a
non-integer `exit`, a non-string value or an invalid regex is a `derive`
error and a `spec validate` `fail` — both call `contract.validate_expect`, so
they cannot disagree. This is how "no test was skipped" becomes a criterion
(`{"exit": 0, "stdout_not_contains": ["skipped", "SKIP"]}`) instead of prose.
Timeout or budget exhaustion → `unverified`, never `ok`. Missing artifact → `fail`.
Artifact paths must be relative, must not contain `..`, and after
`os.path.realpath` must stay inside the project root (symlink escape → `fail`).
If `source_sha256` no longer matches `05-gate.md`, the run verdict is
`unverified` with reason `contract_stale` (re-derive first).
Aggregate verdict follows `verdict.aggregate` (§11).

## 6. Task blocks in `spec/04-tasks.md`

````
```gatekit-task
{"id": "auth-token", "title": "JWT token helpers", "write_scope": ["src/auth/token.ts"],
 "instruction": "…self-contained brief…",
 "gates": [{"name": "typecheck", "argv": ["npx", "tsc", "--noEmit"]}],
 "depends_on": [], "round": 1}
```
````

`jobs.py` reads these; `spec.py` validates: unique ids, non-empty write_scope
(or `"read-only"`), every `depends_on` exists, no two tasks in the same round
with intersecting write_scope, every task has ≥ 1 gate. `spec.py` also
`warn`s when `spec/PROGRESS.md` is older than the latest terminal task
status under `.gatekit/jobs/`: a session that ended between the build and
the progress write leaves a file that reports the state before the tasks
finished.

A task gate is an `argv` command like any other in `gates`, run by
`jobs.py` after the worker exits (§10) — distinct from the hook-driven gates
in §3, which fire during the session rather than after a task. One ships
with gatekit: `.claude/gatekit/bin/gatekit.py _gate tokens [--root DIR]
[--lang ko|en] [--json] GLOB...` (ADR-0008), which scans the files matching the given
globs (typically the task's own `write_scope`) for colour literals not
present in `spec/tokens.json`. Its exit code is the task-gate convention,
not the hook convention: `0` (`ok`, every literal found matches a token),
`1` (`fail`, a literal named with the file, line, and nearest token by
value), `3` (`unverified`, `tokens.json` absent or unparsable, or the task
wrote no file the gate knows how to scan). `/gatekit-tasks` adds it by
default to every task whose `write_scope` touches a stylesheet, component,
or template path when `spec/tokens.json` exists. The scan is deliberately
narrow — colours only at this version — so a `fail` from it stays
trustworthy. `--root` defaults to `.`, and `jobs.run_gates` always runs a
task gate with the project root as its `cwd`, which is why the fence in
`04-tasks.md` never needs `--root`; run it by hand from another directory
without `--root` and it reports `unverified`, not the project's real state.

A task gate must be able to fail before the work exists and must be a
command that runs as written: `jobs start` executes every gate once before
spawning any worker (ADR-0009, §10) and refuses a gate whose command itself
errors. Two runner-specific rules the trial exposed: `node --test` takes glob
patterns (`tests/rules/*.test.js`), a bare directory is loaded as a module and
fails with `Cannot find module`; `gates/tokens.py` takes globs too
(`src/**`), a bare directory scans zero files and exits 3.

### 6b. Screen spec and prototype confirmation gates (ADR-0017 decisions 3, 4)

`spec.validate` reports two more `fail` conditions against `04-tasks.md` (the
file whose command, `/gatekit-tasks`, must not proceed while either stands),
both exempted when `01-prd.md`'s Non-goals section contains the literal
marker `[non-ui]` (a pure-CLI or library spec with nothing to prototype):

- **`screens_required`** — `01-prd.md` exists and `02-screens.md` does not.
  `heading-map.json`'s `absent_ok` no longer covers `02-screens.md`
  unconditionally; this check replaces that blanket allowance with the
  `[non-ui]`-conditional one. `01-prd.md`'s own absence is reported once, by
  the existing required-file check, never doubled here.
- **`prototype_required`** — `02-screens.md` exists but carries no line
  matching `Prototype confirmed <date>` / `프로토타입 확정 <date>`
  (`YYYY-MM-DD`). This line is prose the validator scans for — not a
  hash-anchored approval like `05-gate.md`'s (§7) — because
  `/gatekit-mockup`'s live-prototype revision loop (Step 7b) has no single
  moment to pin a hash to before the loop's last accepted edit. Only the
  user's explicit confirmation writes this line; the command must never
  infer it from "the prototype looks finished."

## 6a. Discovery record in `spec/00-discovery.md` (ADR-0005)

The optional first stage for a user who does not yet know what to build.
`/gatekit-discover` writes it; `/gatekit-interview` reads it as facts. One
fence:

````
```gatekit-discovery
{"problem": "…", "deadline": "4 weeks|none", "user": "name · role",
 "current_way": ["step", "step"], "frequency_per_month": 8, "minutes_per_run": 40,
 "wait": "none|…", "why_chain": ["symptom", "why", "why", "why", "cause"],
 "failed_attempts": [{"tried": "…", "result": "failed|works-but-costly", "why": "…"}] | "not-applicable",
 "unpassed": ["<gate name>"]}
```
````

`spec.validate`: the file's absence is **silent** (it is listed in
`heading-map.json` `absent_ok`); when present, exactly one fence and a
non-empty `problem` are `fail` conditions, and each of the six deepening
gates (`user`, `current_way` ≥ 2 steps, numeric `frequency_per_month` and
`minutes_per_run`, `why_chain` of strings with ≥ 3 distinct whys after the symptom — a link whose word set overlaps an earlier link by ≥ 0.6 (Jaccard) is a restatement and does not count —
`failed_attempts` non-empty with a valid `result` or `"not-applicable"`) is
`warn` when unfilled — with a distinct message when the gate is declared in
`unpassed`. A gate is never filled by the validator; `unpassed` that is not a list, or names outside the gate list, is `fail`; a gate both filled and listed in `unpassed` is `warn`. Discovery questions are plain chat (not
`AskUserQuestion`), budgeted per gate by the command at three; the question
gate does not count them.

### 6a.1 The `pains` array (ADR-0017 decisions 1 and 2)

Additive to the fence above: a `pains` top-level key holding a list of
`{"summary": "…", "chosen": bool, "verdict_suggested": {"verdict": "build|reuse|eliminate|unknown", "why": "…"}|null, "verdict": "build|reuse|eliminate|unknown"|null}`.
A record with no `pains` key at all is untouched by every check below (the
pre-ADR-0017 fence shape stays valid forever).

Once `pains` is present, `spec.validate`:

- fails if `pains` is not a list;
- fails if fewer than `PAIN_FLOOR` (3) entries exist and the top-level
  `pain_floor_waived` is not truthy (the discovery command's record of a
  user stop signal);
- fails on any entry that is not an object, whose `verdict_suggested` is
  present but not `{"verdict": <one of the four>, "why": <non-empty string>}`,
  or whose `verdict` is present but not one of the four tokens;
- fails unless **exactly one** entry has `"chosen": true`;
- on the chosen entry: fails if its confirmed `verdict` is `eliminate` or
  `reuse` (mirrors `ai-dev-pm`'s `blocksPromote()` — `/gatekit-interview`
  must not draft a spec for a pain the pipeline itself judged should not be
  built); warns (never fails) if `verdict` is `null` while
  `verdict_suggested` exists (the interviewer proposed, the user has not
  confirmed — this is the exact shape of the failure `gk-trial2`'s
  Assumption 4 named: a mapping decided without ever being posed as a
  question); `unknown` never blocks, deliberately — see `spec.py`'s comment
  on why blocking "not sure yet" would be worse than the gap it closes.

## 7. Hash-anchored approvals (`approval.py`)

`.gatekit/approvals.json`:

```json
{"version": 1, "approvals": [
  {"target": "spec/05-gate.md", "sha256": "…", "approved_by": "user", "approved_at": "iso", "note": ""}
]}
```

`gatekit approve <path> [--note …]` records the current hash (asks nothing; the
command file is responsible for asking the user via AskUserQuestion before
calling it). `gatekit approve check <path>` prints `ok` when the file's current
hash matches an approval, `fail` when it differs (approval stale) and
`unverified` when no approval exists. Never overwrite a file to satisfy a hash.

## 8. Output language (`lang.py`)

`detect(text) -> "ko" | "en"`: count Hangul syllables/jamo vs Latin letters in
`text`, after dropping whitespace-delimited tokens that are paths or code
identifiers (containing `/`, `.`, `_`, `\` or a backtick inside them) — a
named file is not the user's language; `ko` if Hangul ≥ 30% of the remaining
letters, else `en`. Empty text, or only identifiers → `en`.
The prompt gate stores the result per session; commands read it from the ledger
and must emit **every** user-facing string (chat, AskUserQuestion labels, files
written under `spec/`) in that language. Identifiers (file names, JSON keys,
CLI flags, fence names) are never translated. Templates and heading maps exist
for `ko` and `en`; other languages fall back to `en` templates and the command
must say so once.

## 9. Config (`config.py`)

`.gatekit/config.json` with defaults:

```json
{"version": 1,
 "enforce_spec_before_code": true,
 "worker": {"default": "claude", "backends": {
   "claude": {"argv": ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits"],
              "read_only_argv": ["claude", "-p", "--output-format", "json", "--permission-mode", "plan"], "enabled": true}
 }},
 "build": {"max_retries": 2, "parallel": 3, "task_timeout_s": 900},
 "questions": {"interview_max_calls": 2, "items_per_call": 4},
 "verify": {"evaluator": ""}}
```

Sandboxing is never disabled by default; a backend with a bypass flag must set
`"unsafe": true` and the job receipt records it. `read_only_argv` is the
backend as an evaluator and must not be able to write; a backend without one
cannot grade, and its writable `argv` is never substituted. `verify.evaluator`
is `agent` (the host's own read-only subagent, the default, with no warning:
ADR-0023) or a backend name, used only when that backend is enabled and has a
`read_only_argv`. `/gatekit-verify` runs the contract once in the main session
and gives the reviewer only the items a command cannot decide. A project may
add its own backend entries to `worker.backends` in `.gatekit/config.json`
for another CLI.

## 10. Jobs and workers (`jobs.py`, `workers.py`)

Job dir `.gatekit/jobs/<job_id>/`: `job.json` (tasks, backend, started_at,
config snapshot), per task `tasks/<id>/{task.json,status.json,prompt.md,output.txt,stderr.txt,gates.json,attempt-N/}`.
All JSON writes atomic. Worker = argv list + the prompt on stdin, env includes
`GATEKIT_TASK_ID=<id>` and `GATEKIT_JOB_ID=<job_id>` so the write gate can
enforce `write_scope` inside the worker session. When `spec/tokens.json`
exists, `jobs.build_prompt` (§14) adds a `## Design` section to the prompt,
generated by code from `tokens.json`: the `P<n>` pattern rows whose
`applies_to` is `all` or names an `S<n>` the task's instruction mentions,
every token group as `name: value` lines, and a pointer to
`spec/02-design.md` and `spec/02-screens.md` for anything the section does
not carry (ADR-0008). When `tokens.json` is absent the section is omitted
and the prompt is unchanged from before ADR-0008. A `## Screens` block
follows it (ADR-0011): `jobs.parse_screens` reads the per-screen sections of
`spec/02-screens.md` — the `### S<n> — <name>` heading, the layout line, the
state table — and `jobs._screen_lines` emits, for each `S<n>` the task's
title or instruction names, that screen's layout and state rows. Matching is
the same `design.referenced_ids` scan the `P<n>` rows use, so a task naming
no screen carries no block and one naming several carries each; a named
screen the spec does not describe is skipped. An unreadable or malformed
`02-screens.md` yields no block and never fails the job. `status.json.state` ∈
`queued|running|gating|passed|failed|timeout|redelegated|stopped|blocked`
(the last two from ADR-0009, below). Gates run only after
the worker exits; a worker that exits 0 but fails a gate is `failed`, never
`passed`. `redelegate <task>` archives the attempt to `attempt-N/` and re-runs
with the failed gate output appended to the prompt, up to `max_retries`.
`results --compact` prints one line per task: `id state gates_passed/total`.

**ADR-0014 — attempts are counted per task, not per job.** `status.json.attempt`
resets to 1 on every `jobs start`, so on gk-trial2 one task failed eight times
across ten jobs and `max_retries` never fired even once — the counter climbed
to 3 and restarted three separate times. `.gatekit/attempts.json` now holds
`{"tasks": {id: {"failures", "last_job", "last_gate", "updated_at"}}}`.
`jobs.record_attempt(root, task_id, state, job_id, gate)` folds one terminal
outcome in: `passed` resets to 0, `failed`/`timeout` increment, `blocked` and
`stopped` are untouched (neither is a judgement of the work). `execute_task`
and `complete_task` both call it — a host attempt counts exactly as a worker's
does — and `recheck` does not, since re-running a gate against existing code is
not an attempt at the work. Both `start` (refusing to include an exhausted
task, `consecutive_failures(root, id) >= max_retries`) and `redelegate`
(refusing when the carried count would put the task past the budget,
`carried > max_retries`, alongside the existing in-job `attempt > max_retries`
check) now raise `RetryBudgetExceeded`, CLI exit 3. `jobs start --force-retry
<id>[,<id>...]` clears one or more tasks' entries first. `status()` rows carry
`consecutive_failures`, and the table prints `(n consecutive)` whenever it is
non-zero, so a task at "attempt 1" in a fresh job that has already failed
elsewhere does not read as untried. Replaying gk-trial2's actual job history
through this counter, `start` refuses before the run's third consecutive
`e2e-full-flow` failure — the real run's other seven attempts never happen.

**ADR-0013 — who implements a task.** `build.execution` is `host` or `worker`
(`jobs.execution_mode`; an unset or unrecognised value means `host`, and
`config.DEFAULTS` carries `host` too — the hedge that kept `worker` as the
default, so projects predating the ADR would not change behaviour, left the
measured decision unapplied for every project that never edited its config,
and was dropped). Under `worker`, `start` runs as described above. Under `host`,
`start` prepares the job dir, runs preflight, writes `job.json.execution` and
`job.json.plan` — one `{id, round, parallel_candidate}` row per task, in wave
order, `parallel_candidate` true when its round holds ≥ `HOST_PARALLEL_HANDOFF`
(3) tasks — marks every task `queued` with detail `awaiting the host session`,
and **spawns nothing**. The calling session implements each task and calls
`jobs.complete_task(root, task_id)`, which runs that task's gates and writes
the same `gates.json` and `status.json` `execute_task` would; there is no
worker exit code to weigh, so the gates alone decide. Passing `--backend`
forces `worker`: naming a model is a request for that model. A worker is a
cold session of the same model, so spawning one per task buys a second opinion
from the model already present; reserve it for a differing model (adversarial
verification) or a genuinely wide round.
Under `host`, `start` never calls `_finalise_job` — nothing drains a loop the
way `worker` mode's does — so `status()` stamps `job.json.finished_at` itself,
the first time every task in the job reads as terminal; found on a real
`gk-trial2` host-execution retrial where the job otherwise finished correctly
(`verdict=ok`, all nine tasks `passed`) but `finished_at` stayed empty.

`jobs.recheck(root, task_ids=None, job_id=None) -> {"job_id", "rechecked",
"missing"}` re-reads **the current** `spec/04-tasks.md`, runs the named tasks'
gates against the working tree, and records the same files with detail
`recheck: … (no worker)`. It is the answer to a gate that moved mid-build,
which is the normal case rather than a mistake: a gate names files and commands
that do not exist until the work is done. Tasks no longer in the file are
returned in `missing`, never silently skipped.

**ADR-0013 decision 4 — the shape is approved before it is written.** `jobs.shape(root)` reports `{tasks, rounds, waves, serial, unevidenced, rounds_if_pruned}` from `spec/04-tasks.md`, and `/gatekit-tasks` shows it — rounds as prominently as the count — before writing the file. A `depends_on` is evidenced when the depending task's title or instruction names the dependency's id or a leaf from its write scope, matched on identifier boundaries so a short id is not found inside a word and a shared ancestor like `src` never counts. `rounds_if_pruned` recomputes depth from the evidenced links alone, ignoring the declared `round`, since that field is a consequence of the links. Advisory only: deciding whether an instruction *needs* a dependency requires understanding both, so nothing refuses. On gk-trial2 this reports 9 tasks / 7 rounds with three unevidenced links and 3 rounds without them.

**ADR-0013 decision 5 — a verification task is not a task.** `spec.validate` warns when a task's `write_scope` holds only test material (a path segment in `_TEST_DIR_SEGMENTS`, or a test-runner config stem) **and** its transitive dependency reach is ≥ 2. A check that passes only once several tasks are done is a completion criterion in `05-gate.md`: as a task it fails on every attempt until the last dependency lands. Reach is transitive because a chain end names one dependency and waits on all of them — the real `e2e-full-flow` declared one and waited on seven. A `warn`, never a `fail`: a legitimate test-only task exists.

ADR-0009 adds four rules to the runner:

- **Preflight.** Unless `start --no-preflight`, every selected task's gates
  run once *before* any worker is spawned; the result is written to
  `tasks/<id>/preflight.json` (same shape as `gates.json`). A task whose
  gates all pass is recorded `passed` with `detail = "gates passed at
  preflight; no worker spawned"` and gets no worker; if nothing exists yet
  under its `write_scope` the detail also carries `warn: gate passed before
  any work existed …` and the line is listed in `job.json.preflight_warnings`
  (a gate that passes on an empty tree is the signature of one that always
  passes). `jobs.classify_gate_result(gate, argv)` sorts every failing gate
  into three kinds. `command_error` — the job is refused with
  `GatePreflightError` (CLI exit 4) naming the task and gate before any
  worker runs — only when the exit code is 126 or 127, or a line matching
  `COMMAND_ERROR_PATTERNS` (`Cannot find module`, `can't open file`, `No such
  file or directory`, `command not found`, `is a directory`) **also names one
  of the gate's own arguments** (or, for `command not found`, its program):
  the interpreter could not run what the fence points at. `suspicious` — the
  job starts and a warning line is printed and stored in
  `job.json.preflight_warnings` — for exit ≥ 2 on its own, a pattern line that
  names nothing from argv (a failing test that mentions a missing fixture),
  or a usage banner opening stderr. `expected` — silent start — for every
  other failure, and always for `ok`/`unverified` results. `--dry-run` skips
  preflight. Refusal is reserved for the named-argument and 126/127 cases;
  everything ambiguous starts.
- **Dependency gating.** A task runs only when every `depends_on` id that
  is part of the same job is `passed`; otherwise it stays `queued` with
  `detail = "waiting on <id> (<state>)"` (the state is suffixed `, gates
  unverified` when the dependency's gates could not judge) and, when the job
  drains, becomes `blocked` (terminal). A blocked task was never run and never
  judged, so it is **not** in `NOT_DONE_STATES`: a job whose only non-passed
  tasks are `blocked` reports `unverified`, never `fail`. Dependencies outside
  the job never block. There is no automatic resume: the operator starts the
  blocked task with `start --tasks` once its dependency passes.
- **Re-read on redelegate.** `redelegate` parses the current
  `spec/04-tasks.md` before archiving the attempt; if the task's fence
  differs from the job's `task.json` snapshot the snapshot is replaced and
  the status detail says `task re-read from spec/04-tasks.md (gates changed
  | instruction changed | write_scope changed)`. A task id no longer in the
  file is refused with a `ValueError` naming the file. `start` still
  snapshots; edits during a run do not reach running workers. The
  redelegate prompt also carries a fixed paragraph telling the worker that
  a gate command which looks wrong is to be reported, not coded around.
- **Stop.** `_spawn_worker` records `pid` and `pid_started_at` in
  `status.json`; `execute_task` clears `pid` the moment the worker is reaped,
  before the task moves to `gating`. `jobs stop [--job ID]` writes `stop.json`
  in the job dir (the runner checks it before each task and after each worker
  returns), and for each task still in `running` — never `gating` — whose
  recorded pid is alive **and** whose `ps -o etime=` age agrees with
  `pid_started_at` within `STOP_PID_AGE_TOLERANCE_S`, calls
  `_terminate_pid` (SIGTERM, `STOP_GRACE_S` seconds, then SIGKILL). A pid
  that fails either check is listed in the result's `skipped`, never
  signalled. Every running or queued task is recorded `stopped` and
  `job.json.stopped_at` is written. `stopped` is terminal and not done.

`status.json.state` therefore ∈ `queued|running|gating|passed|failed|timeout|
redelegated|stopped|blocked`; `TERMINAL_STATES` and `NOT_DONE_STATES` in
`jobs.py` are the two sets every consumer uses. `status` reports `fail` when
any task is in a not-done state (`failed`, `timeout`, `stopped`), `unverified`
when the rest are not all `passed` (running, queued, or `blocked`), and
`done` when every task is terminal.

`jobs evaluate [--backend name] [--prompt FILE] [--lang ko|en]
[--force-read-only-evaluator]` runs one worker as the reviewer, for a project that named a backend in
`verify.evaluator` (ADR-0023; the default reviewer is a subagent and does not
use this command): job dir
`.gatekit/jobs/<job_id>/evaluate/{task.json,prompt.md,output.txt,stderr.txt,status.json}`,
`job.json.kind = "evaluate"`, env `GATEKIT_TASK_ID=evaluate` with
`task.json.write_scope = "read-only"` so the write gate refuses writes inside
the evaluator's own session regardless of backend. `state` ∈
`passed|failed|timeout`; anything but `passed` is `unverified` for every
criterion. Its stdout ends with the evaluator's reply tail, which is the
verdict table.

`evaluate` always resolves with `read_only=True` (the backend's
`read_only_argv`), which is the real protection beneath the write gate — a
backend is never handed a writable sandbox as the evaluator.
`force_read_only_evaluator` is accepted for backward compatibility and is a
no-op, since read-only is already the only mode.

`workers.py`: `list`, `check <name> [--probe]` (`shutil.which` on argv[0] →
ok/fail, `--version` probe → ok/unverified; with `--probe`, one trivial
prompt through `read_only_argv`: answered → ok, non-zero exit → `fail` with
the output tail, since a binary that cannot run a prompt here — not logged
in, or sandboxed away from its credentials — will fail every task; timed out
→ unverified), `set-default <name>`, `enable <name>`, `set-evaluator
<agent|name>`. `/gatekit-build` runs the live probe before `jobs start`.
`claude` is the only backend enabled by default; a project may add and enable
more in `.gatekit/config.json`.

## 11. Verdicts (`verdict.py`)

`OK, WARN, FAIL, UNVERIFIED`. `aggregate(list)`: any `fail` → `fail`; else any
`unverified` → `unverified`; else any `warn` → `warn`; else `ok`. Rendering:
`render(v, lang)` gives the localized label; JSON always uses the English token.

## 12. Doctor (`doctor.py`) — 8 axes

1 gatekit files present (`bin/gatekit.py`, all gate scripts and the `scripts/*.ps1` files exist and are non-empty; `pyproject.toml` and `uv.lock` exist);
2 hooks registered (the project's own `.claude/settings.json` has all seven events, each in exec form; gates point at the `.venv` python and `bin/gatekit.py`, SessionStart at `session-check.ps1`; every gate hook of `REQUIRED_HOOKS` is there — each `(event, matcher, gate)` row of §3, where each tool named in the matcher must be covered by a group under that event that runs `_gate <gate>` — and a missing one is `fail` with a detail that names it, e.g. `PreToolUse PowerShell (_gate powershell)` or `SubagentStop (_gate release)`, since none of these gaps shows any other way; `env.CLAUDE_CODE_USE_POWERSHELL_TOOL` is `"1"` and `defaultShell` is `"powershell"`);
3 project state (`.gatekit/config.json` valid, approvals valid JSON);
4 spec set (`spec.validate` verdict, or `unverified` when no `spec/`);
5 contract freshness (`source_sha256` matches);
6 workers (default backend `check`);
7 python (the `.venv` interpreter is ≥ 3.14);
8 uv (uv is on PATH and answers `--version`). Each axis returns `{axis, verdict, detail, fix}` where
`fix` is a copy-pasteable command or empty. Exit 1 iff any `fail`.

## 13. Testing convention

`cd .claude/gatekit; uv run --frozen python -m unittest discover -s tests -v` must pass with
no network and no external binaries. Tests that need a binary (`claude`) use a
fake executable created in a temp dir and prepended to `PATH`. Every gate has at
least three tests: allow, deny/block, internal-error-still-exits-0. Fixtures
under `.claude/gatekit/tests/fixtures/` are small text files only.

`jobs.py` (ADR-0009) additionally covers: preflight classification (already
passing → no worker; command error → `GatePreflightError` and CLI exit 4 with
the gate named; expected failure → worker spawned; `--no-preflight` and
`--dry-run` skip it), the early-pass warning on an empty write scope,
`looks_like_command_error` on each listed signature and on `ok`/`unverified`/
malformed input, redelegate re-reading a corrected gate and refusing a task
removed from the file, the redelegate prompt paragraph, `stop` ending a live
fake worker and marking queued tasks `stopped`, `stop` refusing to signal a
pid whose age does not match the recorded spawn time, `stopped`/`blocked`
counting as not done, and dependency gating (blocked on failure, run on pass,
out-of-job dependency ignored).

ADR-0013 adds: host execution preparing a job and spawning nothing while
recording `execution` and `plan`; `complete_task` writing the same status and
gates files worker execution does, with `unverified` not rounding; an unknown
task id refused; `--backend` forcing worker mode; a config without
`build.execution` still spawning; `recheck` passing a task whose gate was
narrowed, leaving a still-failing one `failed`, reading the current task file
rather than the job snapshot, naming tasks missing from it, and being
idempotent; and `_positionals` not mistaking an option's value for a task id. `shape` counting tasks and rounds, sharing a round between independent tasks, flagging a dependency with no evidence in the instruction while sparing one named there or named by id, and reporting the pruned round total; a task warned as verification-shaped when it writes only test paths and its **transitive** dependency reach is two or more, and not warned on one direct dependency, a source path in scope, a `read-only` scope, or a cycle; the finding staying a `warn`. The PreCompact hook: recording every task's state, naming the job, creating PROGRESS.md when absent, leaving human content intact, replacing its own block on a second compaction, writing nothing with no job, surviving a corrupt status file and an unwritable spec dir, exiting 0 as a subprocess, and leaving `spec validate` findings unchanged. ADR-0014: a failure incrementing the attempt ledger and a pass clearing it; `blocked`/`stopped` leaving it alone; `redelegate` and `start` both refusing at the budget with exit 3; `--force-retry` clearing exactly one task; `recheck` not counting while `complete_task` does; a corrupt or missing `attempts.json` reading as empty; the status row and table showing the carried count. Host execution: `finished_at` absent right after `start`, stamped by `status()` once the last task turns terminal, not stamped while one is still queued, and stamped once (idempotent on repeated calls). `evaluate` always resolving `read_only=True` regardless of backend.

ADR-0012 adds, in `gates/question.py`: a justified over-budget call consuming
its line and raising nothing; an unjustified one raising `unjustified`; the
line single-use across two calls; calls within budget needing none; a blank or
non-string line counting as absent; `budget_exceeded` keeping its meaning; an
unbudgeted pipeline carrying no signals; a repeated and a reworded-same topic
fingerprinting while a merely similar one and two short questions do not;
`repeat_of` naming the earlier call; an all-code option set warning while a
priority question and an option-less question do not; `unrealized` firing when
no write follows and not when one does; a write event clearing the watch,
never counting as a question, and never blocking; and in `gates/prompt.py`,
the signals appearing in `additionalContext` only when non-zero, a malformed
count not breaking the line, and the block staying within 600 chars.

ADR-0011 adds: the `## Screens` block present for a task naming `S2` and
absent for one naming none or naming a screen the spec lacks, only the named
screens carried, `S02` matching `S2` while `S12`/`S20` do not, the block's
layout and state rows matching the spec, ordering after `## Design` and
before `## Reporting`, an unreadable screen spec leaving the prompt usable,
the block reaching the written `prompt.md` through `start`; and in `spec.py`,
an evidence cell citing `preview-*.html` failing validation (in both
`02-screens.md` and `02-design.md`) while prose mentioning the preview and an
unrelated `*-preview.html` capture do not.

## 14. Module interfaces (exact signatures other modules may import)

```python
# paths.py
def project_root(cwd: str | None = None) -> pathlib.Path
def state_dir(root: pathlib.Path) -> pathlib.Path      # root / ".gatekit"
def spec_dir(root: pathlib.Path) -> pathlib.Path       # root / "spec"
def gatekit_root() -> pathlib.Path                      # .claude/gatekit (parent of the gatekit/ package)

# config.py
DEFAULTS: dict
def load(root: pathlib.Path) -> dict                   # deep-merged with DEFAULTS; missing file → DEFAULTS
def save(root: pathlib.Path, cfg: dict) -> None        # atomic

# lang.py
def detect(text: str) -> str                           # "ko" | "en"
def run(argv: list[str]) -> int

# verdict.py
OK, WARN, FAIL, UNVERIFIED = "ok", "warn", "fail", "unverified"
ORDER: list[str]
def aggregate(verdicts) -> str
def render(verdict: str, lang: str) -> str

# ledger.py
class Ledger:
    data: dict
    @classmethod
    def load(cls, root: pathlib.Path, session_id: str) -> "Ledger"   # creates if missing
    def save(self) -> None                                          # atomic
    def append_event(self, kind: str, detail: dict | None = None) -> None
    def add_scope(self, owner: str, write_scope: list[str], tool_use_id: str | None = None) -> None
    def scope_conflicts(self, write_scope: list[str]) -> list[dict]  # existing scopes that intersect (glob-aware, case ignored)
    def scope_of(self, key: str, value: str) -> dict | None     # key: "tool_use_id" | "agent_id"
    def bind_agent(self, tool_use_id: str, agent_id: str) -> bool   # write agent_id on the scope that call declared
    def release_scope(self, key: str, value: str) -> int        # drop the scope with that exact id (the release hook)
    def note_agent_ended(self, agent_id: str) -> None
    def agent_ended(self, agent_id: str) -> bool
    def release_scopes(self, owner: str | None = None) -> int  # manual: drop scopes by owner label (all when owner is None)
class ScopeLock:                                                # with ScopeLock(root, session_id) as held: ...
    def __init__(self, root: pathlib.Path, session_id: str, wait: float = 2.0, stale: float = 15.0) -> None
def globs_intersect(left: str, right: str) -> bool             # conservative, case ignored
def run(argv: list[str]) -> int

# hookio.py
def read_event() -> dict
def run(handler, stdin=None, exit_process=True) -> int   # never raises; always exit 0
def deny(reason: str) -> dict                          # PreToolUse deny payload
def block_stop(reason: str) -> dict                    # Stop block payload
def add_context(text: str) -> dict                     # UserPromptSubmit payload
def log_error(root: pathlib.Path, event_name: str, err: BaseException) -> None

# approval.py
def sha256_file(path: pathlib.Path) -> str
def check(root: pathlib.Path, relpath: str) -> str     # ok | fail | unverified
def approve(root: pathlib.Path, relpath: str, note: str = "", by: str = "user") -> dict
def run(argv: list[str]) -> int

# contract.py
EXPECT_KEYS: tuple[str, ...]
def validate_expect(expect, ident: str = "?") -> list[str]   # problems; empty when valid
def judge_output(expect: dict, stdout: str, stderr: str) -> list[str]   # unmet output expectations
def derive(root: pathlib.Path) -> dict                 # writes .gatekit/contract.json, returns it
def status(root: pathlib.Path) -> str                  # ok (fresh) | fail (stale) | unverified (absent)
def execute(root: pathlib.Path, total_budget_s: float | None = None, cap_s: float | None = None) -> dict   # {"verdict", "criteria":[...], "reasons":[...], "total_budget_s"}; cap_s lowers the applied budget
def run(argv: list[str]) -> int

# spec.py
def validate(root: pathlib.Path, lang: str | None = None) -> dict      # {"verdict", "findings":[{"file","verdict","message"}], "lang"}
def parse_fences(text: str, name: str) -> list[dict]                   # all ```<name> JSON fences
def run(argv: list[str]) -> int

# jobs.py
def run(argv: list[str]) -> int                        # start / status / wait / results / complete / recheck / redelegate / stop / evaluate / clean
def start(root, task_ids=None, backend_name=None, parallel=None, dry_run=False, no_preflight=False) -> dict   # raises GatePreflightError (ADR-0009)
def preflight(root, jdir, tasks: list[dict]) -> dict   # {"passed": [ids], "warnings": [str]}; raises GatePreflightError
def classify_gate_result(gate: dict, argv=None) -> str  # "command_error" | "suspicious" | "expected" (ADR-0009 decision 1)
def looks_like_command_error(gate: dict, argv=None) -> bool   # classify_gate_result(...) == "command_error"
def stop(root, job_id: str | None = None) -> dict      # {"job_id", "stopped", "signalled", "skipped"}
def evaluate(root, backend_name=None, prompt_path=None, timeout_s=None, lang="en", force_read_only_evaluator=False) -> dict   # always read-only sandbox
def load_tasks(root: pathlib.Path) -> list[dict]       # from spec/04-tasks.md via spec.parse_fences
def parse_screens(text: str) -> dict                   # {"S2": {"name","layout","states"}} from 02-screens.md (ADR-0011)
def execution_mode(cfg: dict) -> str                   # "host" | "worker" (ADR-0013)
def complete_task(root, task_id: str, job_id: str | None = None) -> dict   # host-implemented task -> gates -> status.json
def recheck(root, task_ids=None, job_id: str | None = None) -> dict        # {"job_id","rechecked","missing"}; gates only, no worker
def shape(root, task_ids=None) -> dict                 # {tasks, rounds, waves, serial, unevidenced, rounds_if_pruned} (ADR-0013)
def record_attempt(root, task_id: str, state: str, job_id="", gate="") -> int   # ADR-0014
def consecutive_failures(root, task_id: str) -> int    # ADR-0014
def clear_attempts(root, task_id: str) -> None         # --force-retry, ADR-0014
class GatePreflightError(ValueError)
TERMINAL_STATES, NOT_DONE_STATES                       # the two state sets every consumer of status.json uses

# workers.py
def resolve(root: pathlib.Path, name: str | None = None, read_only: bool = False) -> dict   # backend dict incl. name, argv, enabled, unsafe, read_only
def evaluator_name(root: pathlib.Path) -> str        # "agent" | backend name
def check(root: pathlib.Path, name: str) -> dict       # {"name","verdict","detail"}
def run(argv: list[str]) -> int

# doctor.py
def diagnose(root: pathlib.Path) -> dict               # {"verdict","axes":[{"axis","verdict","detail","fix"}]}
```
