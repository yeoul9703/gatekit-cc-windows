# ADR-0018: Windows-only standalone folder, managed by uv

Status: accepted 2026-09-30.

## Context

gatekit began as a Claude Code plugin (upstream LovelyPaul/gatekit 0.11.2):
one plugin (ADR-0001), stdlib-only Python found by a generic interpreter name on any machine
(ADR-0002), hooks declared in the plugin's own hook file and reached through
the plugin-root variable, and a POSIX `sh` launcher script that searched for a
working Python.
This fork (yeoul9703/gatekit) serves one audience: people on Windows using
Claude Code who want to open a folder and have it work. Supporting Mac, Linux,
other hosts and several Python versions cost a launcher, path guessing and
version checks that this audience never benefits from.

## Decision

1. **Windows and Claude Code only.** Mac/Linux and other hosts are not
   supported. (Codex support, ADR-0006, was already not adopted here.)
2. **Standalone folder.** gatekit lives in the project's own `.claude/`
   (commands, `settings.json`; the skill shims were removed by ADR-0019) and `.claude/gatekit/` (kernel,
   scripts, tests). No plugin manager, no global install; opening the folder
   is enough.
3. **uv manages Python.** `.claude/gatekit/pyproject.toml`
   (`requires-python >=3.14`, `.python-version` 3.14, no runtime dependencies, `[tool.uv]
   package=false`, dev group `pyright[nodejs]` + `ruff`) and `uv.lock` let uv
   build `.claude/gatekit/.venv`. Commands run as `uv run --project
   .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py <sub>`,
   the same in PowerShell and Git Bash. Kernel code stays standard-library
   only (ADR-0002's rule survives).
4. **Exec-form hooks, no shell.** `.claude/settings.json` registers six
   events (SessionStart, UserPromptSubmit, PreToolUse x3, PostToolUse x2,
   PreCompact, Stop). Gates run
   `${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe` with
   args `bin/gatekit.py _gate <name>`. The POSIX sh wrapper is
   deleted. `env` sets `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`.
5. **SessionStart check.** `powershell.exe -NoProfile -ExecutionPolicy
   Bypass -File scripts/session-check.ps1` verifies uv, the `.venv` (and that
   its `pyvenv.cfg` home still exists) and the `claude` CLI, and warns when
   one is missing.
6. **PowerShell scripts for setup and verification.** `scripts/setup.ps1`
   checks by default and changes only what the user approved
   (`-Install pwsh,uv,claude,git,venv`, `-Update`, `-Reinstall uv,pwsh,claude`, `-RetryFailed`, `-Status`, `-Json`, `-Lang ko|en`;
   program ids and urls live in `scripts/packages.json`, failures in `.gatekit/runs/setup-last.json`,
   and `gatekit.py setup` forwards to the script; see `docs/SETUP-REFERENCE.md`;
   exit 0 ready, 1 failed, 2 consent/action needed, 3 restart needed, 4
   blocked by policy or network). `scripts/verify.ps1` runs syntax, tests,
   pyright, ruff, doctor and a `settings.json` check.
7. **Doctor has eight axes**: plugin files, hooks registered, project state,
   spec set, contract freshness, workers, python (venv >= 3.14), uv.

## Rationale (measured)

- Start-up cost of one hook call: python directly 33 ms; `uv run` 101 ms;
  pwsh 221 ms; Windows PowerShell 5.1 317 ms. Gates use the venv python
  directly (about 105 ms including gatekit's own work) and pay neither the
  `uv run` nor PowerShell cost on every prompt and tool call.
- The exec form (`command` + `args`) works without a shell, so quoting and
  profile-loading problems disappear.
- A hook that points at an executable that does not exist is silently
  ignored by Claude Code. A missing `.venv` would leave every gate off with
  no message, so SessionStart needs its own check, and that check has to be
  a command that exists on every Windows machine (`powershell.exe`).
- The 3.9 release line reached end of life in 2025-10 and 3.10 reaches it in
  2026-10;
  pinning `>=3.14` with uv-provided interpreters avoids depending on
  whatever the machine has.

## Decision change 2026-10-02 (winget install, stable product, dev group)

Three follow-ups to the change below, decided the same day. Command names are
written the new way here (`/gatekit-setup`; the skills replaced the commands).

1. **setup installs winget.** "Known cost" below ended at the Microsoft Store.
   Now `-Install winget` exists (`packages.json` lists `winget` as 권장): step 1
   asks Windows to register the App Installer package that is already on the PC
   (`Add-AppxPackage -RegisterByFamilyName`, nothing downloaded); step 2, only
   if winget is still missing, installs the `Microsoft.WinGet.Client` module and
   the NuGet provider with `-Scope CurrentUser` and runs
   `Repair-WinGetPackageManager` without `-AllUsers`; step 3 prints the Store
   link and ends at exit 2 (exit 4 when policy or the network blocks it).
   Step 2 runs automatically because it needs no administrator rights: the
   cmdlet help says only `-AllUsers` does, and `-Scope CurrentUser` installs
   into the user's folders. It is given explicitly on both cmdlets because
   Windows PowerShell 5.1 would default to AllUsers. When PowerShell 7 is
   missing too, `S2` names `-Install winget,pwsh`; winget is always done first.
   There is no `-Update winget` or `-Reinstall winget` (the Store updates it).
2. **The stable product decides `S2`, not the PATH order.** A machine with the
   stable 7.6 and a preview build side by side was reported as `warn` because
   the preview came first on PATH. The preview is a different product
   (package `Microsoft.PowerShellPreview`, MSI folder `7-preview`), so setup
   now looks for the stable one: `Get-AppxPackage -Name Microsoft.PowerShell`,
   then `Program Files\PowerShell\7`, then the version text of the `pwsh` on
   PATH. Stable and at least 7.6.0: `ok` (a preview first on PATH is only
   noted). Stable but older: `fail`, `-Update pwsh`. Preview only, or nothing:
   `fail`, `-Install pwsh`. Installed but no `pwsh` on this session's PATH:
   `warn`, exit 3. The package names live in `packages.json`
   (`appx_name`, `appx_preview_name`). `session-check.ps1` applies the same rule lightly
   (the functions live in `common.ps1`): the package lookup, the MSI folder and
   the version written in the `pwsh.exe` file. It starts no process and uses no
   network; the package lookup loads the Appx module (about half a second), and
   a machine with only a preview is named at session start.
3. **The dev group is not installed by default.** `uv run --frozen` (the form
   every skill uses) installed `pyright[nodejs]` and `ruff` on a user's machine
   because uv syncs the `dev` group by default. `[tool.uv] default-groups = []`
   stops that; `scripts/verify.ps1` asks for them with `--group dev`. `uv.lock`
   does not change.

Doctor's "hooks registered" axis now also fails when
`env.CLAUDE_CODE_USE_POWERSHELL_TOOL = "1"` or `defaultShell = "powershell"`
is missing, and points at `/gatekit-setup`.

## Decision change 2026-10-02 (PowerShell 7 is required)

PowerShell 7 was "recommended". The user decided it is required: the audience
works in native Windows without Git Bash, so Claude Code's PowerShell tool is
the shell, and Windows PowerShell 5.1 is a different language edition (no `&&`,
other default encoding). `scripts/packages.json` lists `pwsh` as 필수,
`setup.ps1` reports a missing one as a required `fail` (exit 2, `-Install pwsh`)
and `session-check.ps1` names it at session start. `.claude/settings.json`
carries `env.CLAUDE_CODE_USE_POWERSHELL_TOOL = "1"` and `defaultShell =
"powershell"`, and `setup.ps1` (S12) fails when either is missing.

The hooks and the two scripts themselves still run under Windows PowerShell
5.1, so setup can start on a machine that has no PowerShell 7 yet.

Known cost: `pwsh` installs through winget only (no official script). On a
machine where winget is missing or blocked by policy, setup now ends at exit
2 or 4 and can only point at the Microsoft Store or the IT contact.

## Decision change 2026-09-30 (Python 3.11 to 3.14)

The first draft pinned 3.11. The user decided on 3.14 because this tool will
still be used after 2026-10, when 3.10 reaches end of life; 3.11 ends
2027-10 and 3.14 ends 2030-10, so 3.14 avoids another forced migration.

## Consequences

- The only prerequisites are Claude Code (with the `claude` CLI; the desktop
  app alone does not provide it) and uv. Recommended: PowerShell 7.6 stable
  and winget; optional: Git for Windows. `/gatekit:setup` offers to install
  what is missing, asking first.
- A first session in a fresh clone has no `.venv` until `/gatekit:setup`
  builds it; the SessionStart warning says so.
- Some environments (corporate PCs) block winget or downloads; setup reports
  exit code 4 rather than working around policy.

## Supersedes

- ADR-0001 (single plugin): replaced; there is no plugin.
- ADR-0002: the "any machine with an old Python" wording is replaced;
  stdlib-only stays.
- ADR-0006 (Codex second host): already not adopted here; unchanged.
