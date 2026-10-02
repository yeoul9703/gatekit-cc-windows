# ADR-0021: The PowerShell tool is gated for writes, and a Skill call records its pipeline

Status: accepted 2026-10-02. Extends ADR-0004 (the Bash write gate) to the
PowerShell tool and settles the item ADR-0020 left open under "Not decided
here": recording the active pipeline when the model loads a skill on its own.

## Context

ADR-0018 made this kit Windows-only and PowerShell 7 a requirement, and
`.claude/settings.json` switches the PowerShell tool on
(`env.CLAUDE_CODE_USE_POWERSHELL_TOOL = "1"`, `defaultShell = "powershell"`).
Two gaps followed. Both were measured on 2026-10-02 (Windows 11, Claude Code
2.1.277) with a hook that only appends its stdin to a file, in a scratch
folder outside this repository. Neither is inferred.

**Measurement A: the `Bash` matcher does not fire for the PowerShell tool.**
Three hooks were registered on PreToolUse: one with no matcher, one with
matcher `Bash`, one with matcher `PowerShell`. The model was told to run
`Set-Content -Path out.txt -Value hello` with the PowerShell tool. The hook
input was:

```json
{"hook_event_name": "PreToolUse", "tool_name": "PowerShell",
 "tool_input": {"command": "Set-Content -Path out.txt -Value hello",
                "description": "Write \"hello\" to out.txt"}}
```

(with the usual `session_id`, `cwd`, `permission_mode`, `tool_use_id` beside
it). The no-matcher hook and the `PowerShell` hook each recorded the call; the
`Bash` hook recorded nothing, and `out.txt` was created. A second run asked
for `'hello' > out2.txt` through PowerShell and `echo hi` through Bash in one
session: the `Bash` hook fired for the Bash call only, the `PowerShell` hook
for the PowerShell call only. The whole command string arrives in
`tool_input.command`; no key names the file being written. The two tools'
inputs have the same shape and differ in `tool_name` alone.

So every rule ADR-0004 enforces for the shell was a convention again on the
tool this kit tells the model to prefer: with `spec/05-gate.md` unapproved,
or inside a scoped worker, `Set-Content src/x.ts` and `'x' > src/x.ts` reach
the disk without any gate seeing them.

**Measurement B: a skill the model starts itself never appears in a prompt.**
With a project skill `gkx-build` and hooks on UserPromptSubmit and on
PreToolUse (no matcher, and matcher `Skill`):

- Typing `/gkx-build some args` gives UserPromptSubmit
  `"prompt": "/gkx-build some args"` — the user's text as typed, no tags, no
  expanded body — and **no PreToolUse call at all**: the skill body is
  injected without a `Skill` tool call.
- Typing `please run the gkx build` gives UserPromptSubmit that sentence and
  nothing else, then PreToolUse:

  ```json
  {"hook_event_name": "PreToolUse", "tool_name": "Skill",
   "tool_input": {"skill": "gkx-build"}}
  ```

  The skill name arrives without a slash or a prefix. The body injected
  afterwards does not fire UserPromptSubmit again.

`gates/prompt.py` looks for `/gatekit-<name>` in the prompt only. On the
second path `active_pipeline` stays unset, so the stop gate (armed by `build`
and `verify`) and the question budget (armed by `interview`) never engage.
Every `SKILL.md` description carries natural-language triggers precisely so
that this path is taken.

## Decision

1. **`gates/powershell.py`, registered as PreToolUse `PowerShell` →
   `_gate powershell`.** A separate entry beside `Bash`: an alternation
   matcher (`Bash|PowerShell`) was not measured, and one gate per tool keeps
   each reader of command text simple.
2. **The gate is the Bash gate with a different reader.** `bash.py` gains
   `judge_command(event, tool_name, extract)`, which holds what the two
   share: the fast path (`write.restrictions_active` — no `GATEKIT_TASK_ID`,
   spec gate approved or absent — allows without parsing), one
   `write.decide_path` verdict per extracted target, and the `opaque` denial
   in the session's `output_lang`. `bash.handle` and `powershell.handle` are
   each one call to it. A PowerShell redirect, a Bash redirect and a Write
   call therefore get the same verdict and the same reason for the same path.
3. **What the gate reads**, statically, from `tool_input.command`:
   - statements separated by `;`, newline, `|`, `&&`, `||`, a trailing `&`;
     backtick-newline continues a line; `#` and `<# … #>` comments are
     skipped;
   - quoting: single quotes (literal, `''` for a quote), double quotes
     (backtick escapes, `""`, and `$name` / `${name}` / `$(…)` noted as
     dynamic), backtick escapes outside quotes, the typographic quotes
     PowerShell accepts as quotes, and here-strings `@'…'@` / `@"…"@`, whose
     body is one value and is never read as commands;
   - redirections `>`, `>>`, `N>`, `N>>`, `*>`, `*>>`. A target of `$null`
     or `NUL` and a merge such as `2>&1` or `*>&1` are not writes;
   - write cmdlets with their aliases and their `-Path` / `-LiteralPath` /
     `-FilePath` / `-Destination` / `-DestinationPath` / `-OutFile` /
     positional arguments: `Set-Content` (`sc`), `Add-Content` (`ac`),
     `Clear-Content` (`clc`), `Out-File`, `Tee-Object` (`tee`), `New-Item`
     (`ni`, `mkdir`, `md`; `-Path` joined with `-Name`), `Set-Item` (`si`),
     `Copy-Item` (`cp`, `copy`, `cpi`), `Move-Item` (`mv`, `move`, `mi`),
     `Remove-Item` (`rm`, `del`, `erase`, `rd`, `ri`, `rmdir`), `Rename-Item`
     (`ren`, `rni`), `Export-Csv` (`epcsv`), `Export-Clixml`, any other
     `Export-*` with a named path, `Start-Transcript`, `Compress-Archive`,
     `Expand-Archive`, `Invoke-WebRequest` (`iwr`) and `Invoke-RestMethod`
     (`irm`) `-OutFile`, and `curl -o`;
   - `Set-Location` (`cd`, `sl`, `chdir`) and `Push-Location` (`pushd`),
     tracked across statements like `cd` in the Bash gate;
   - script blocks, `(…)`, `$(…)`, `@(…)` and `@{…}`, read as nested
     statements, so the body of `if`, `foreach`, `ForEach-Object { … }` or a
     `function` is judged too; an assignment's right-hand side is read as the
     command it is.
4. **Parameters are bound the way PowerShell binds them.** Each cmdlet above
   has a table of its parameters: names, aliases, which are switches, which
   take a value, and the positional order. The tables were compared against
   `(Get-Command <name>).Parameters` and the binding rules were run in
   PowerShell before being written down: names are case-insensitive;
   `-Name:value` binds inline; a shortened name resolves when exactly one
   name or alias starts with it, and among several candidates the cmdlet's
   own parameter wins over a common one (`-V` is `-Value`, not `-Verbose`;
   `Set-Content -Pa` is ambiguous between `-Path` and `-PassThru`);
   `-LiteralPath` fills `-Path`'s positional slot. A switch never consumes the
   next word, so `New-Item -Force out.txt` writes `out.txt`.
5. **Windows paths.** A target is resolved with `ntpath` against the event's
   `cwd`: either separator, `.`/`..` collapsed, the drive letter upper-cased,
   `~` expanded, a root-relative path given the cwd's drive, trailing dots
   and spaces of a name dropped (Windows drops them). The result is an
   absolute path, which is the form `write.decide_path` already takes from
   the Write gate; it makes the path relative to the project root with
   `os.path.realpath`, which restores the on-disk spelling of the part that
   exists. `Env:`, `Variable:`, `HKLM:`, `HKCU:`, `Cert:` and `WSMan:` are
   not the file system and are not project writes.
6. **Unresolvable writes are denied while a rule is active** — the rule of
   ADR-0004 decision 3, unchanged: "could not tell" is never rounded to
   "allowed". Opaque are:
   - a variable, `$(…)`, `(…)`, a splat (`@params`) or a control-character
     escape in a target path, and a `cd` to such a place followed by a
     relative write;
   - a wildcard (`*`, `?`, `[`, `]`) in a target unless it is
     `-LiteralPath`, and `-Include` / `-Exclude` / `-Filter` on a cmdlet that
     writes what they select;
   - a parameter the table does not know, an ambiguous shortened name, more
     positional words than the cmdlet has slots: any of them may change which
     word is the path;
   - a target that comes down the pipeline (`Get-ChildItem | Remove-Item`)
     or that the cmdlet picks itself (`Start-Transcript` with no path);
   - a drive-relative path (`C:x`), a PowerShell drive that is neither a
     letter nor one of the non-file drives above, an alternate data stream;
   - `Invoke-Expression` (`iex`), `Invoke-Command`, `Start-Process`
     (`saps`, `start`), `Start-Job`, `Invoke-Item`, `Add-Type`, `Set-Alias` /
     `New-Alias` (an alias for a write cmdlet would be invisible), a write to
     the `Alias:` or `Function:` drive (the same act through the provider),
     `New-PSDrive`, `Start-BitsTransfer`;
   - the call operator `&` and dot-sourcing `.` applied to a variable or a
     script block. On a literal name the command is read as that command
     (`& 'Set-Content' a b`), and a script file is a program invoked by name;
   - .NET: a static member on any type outside a short list of pure ones
     (`[math]`, `[string]`, `[datetime]`, `[System.IO.Path]`, …; on
     `[System.IO.File]` and `[System.IO.Directory]` only the reading
     members), `New-Object` of any type outside a similar list, and an
     instance method call outside a list of string, collection and date
     methods. `[System.IO.File]::WriteAllText(…)`, `$doc.Save(…)` and
     `[scriptblock]::Create(…)` are all denied by this;
   - inline interpreter code: `python -c`, `node -e`, `ruby -e`, `perl -e`,
     `pwsh -Command`, `powershell -Command` / `-EncodedCommand`, `cmd /c`,
     `bash -c`, and an interpreter with no script argument, which reads its
     code from stdin;
   - the `git` subcommands of `bash._GIT_OPAQUE` (one list, imported), with
     `-C <dir>` and `-c <cfg>` skipped when finding the subcommand;
   - file tools that reach a PowerShell prompt from Git for Windows or
     System32 and whose arguments this gate does not read: `sed -i`, `awk`,
     `patch`, `xargs`, `dd`, `touch`, `tar`, `unzip`, `robocopy`, `xcopy`,
     `wsl`, `curl -O`, `wget`, command-line editors;
   - unbalanced quotes or brackets, an unterminated here-string, nesting
     deeper than 12 levels, a vertical tab or Unicode line separator outside
     quotes;
   - **a fault in the reader itself.** `hookio.run` turns an exception into
     "allow", which for a hand-written parser would mean that a command it
     broke on passes unread. `extract_write_targets` therefore catches its
     own exceptions and reports the command as opaque. An exception anywhere
     else in the gate still exits 0 with a line in the error log.
7. **Out of reach by design**, as in ADR-0004: a program invoked by name —
   `npm run build`, `python script.py`, `uv run …`, `pwsh -File x.ps1`,
   `.\build.ps1`. The gate reads PowerShell syntax, not what a binary or a
   script file does.
8. **`gates/skill.py`, registered as PreToolUse `Skill` → `_gate skill`.**
   When `tool_input.skill` is `gatekit-<name>` it updates `active_pipeline`
   by the prompt gate's rule: a name in `ledger.PIPELINES` sets it, `doctor`
   and `setup` clear it. The rule lives in one place — `prompt.py` now builds
   its prompt pattern and `skill_command()` from the same `gatekit-([a-z]+)`
   fragment, and both callers apply `prompt.apply_name()`. The whole string
   must be the skill name, so `gatekit-build-state` and a plugin skill
   `other:gatekit-build` are not `build`. The hook **never blocks**: it has
   no deny path and returns no payload. Any other skill, an unknown
   `gatekit-` name and malformed input leave the ledger untouched, and a
   project with no `.gatekit/` gets no state.
9. **Doctor axis 2 requires both registrations.** A PreToolUse group must
   cover `PowerShell` and run `_gate powershell`, and one must cover `Skill`
   and run `_gate skill`; a missing one is `fail`. Neither gap produces any
   symptom of its own, so doctor is where it shows. Axis 1 lists the two new
   gate scripts.
10. Both gates import nothing heavy (`ntpath`, `re`; `test_hook_imports`
    covers them), exit 0 on any internal error through `hookio.run` with one
    line in `.gatekit/runs/hook-errors.log`, and have allow, deny and
    internal-error tests, including the measured hook inputs above.

## Consequences

- Rules (a) spec-before-code and (b) task write scope hold for the PowerShell
  tool. The worker prompt's sentence that writes outside the scope "are
  denied by a hook, not by convention" is true on Windows.
- A pipeline started by a natural-language request arms the stop gate and the
  question budget exactly as a typed `/gatekit-<name>` does. The two writers
  of `active_pipeline` never both fire for one invocation: a typed slash
  command makes no `Skill` tool call.
- `Move-Item` and `Rename-Item` record the **source** as a write target as
  well as the destination, since the source disappears. This is stricter than
  the Bash gate's `mv`, which records the destination only.
- While a rule is active, PowerShell one-liners that are ordinary in a free
  session are refused: `Remove-Item *.tmp`, `Set-Content $path …`,
  `$x.Save(…)`. The reason names what could not be read and suggests the
  Write/Edit tool or a literal path; the cost is one re-typed command.
  Ordinary sessions (no task scope, gate approved or no `spec/`) never parse
  the command at all.
- Every PowerShell call and every Skill call in this repository now starts
  one more Python process. Measured through `bin/gatekit.py _gate <name>`
  (median of 15 runs, one machine): the PowerShell gate 125 ms on the fast
  path and 126 ms when it parses and denies, the Bash gate 115 ms for
  comparison, the Skill hook 111 ms for a skill it ignores and 145 ms when it
  writes the ledger; an empty `python -c pass` is 43 ms.

## Known limits

- **Programs by name are not inspected**, including a script the same
  command line wrote a moment earlier, and wrappers that run an interpreter:
  `uv run python -c "…"` and `npx … -e` are not seen as inline code, because
  `uv` and `npx` are programs invoked by name. The Bash gate has the same
  limit.
- **No variable tracking.** `$p = 'src/x.ts'; Set-Content $p y` is denied as
  opaque rather than resolved. `$env:TEMP`, `$HOME`, `$PWD` and
  `$PSScriptRoot` are variables like any other.
- **Path case** (changed by ADR-0022: scope matching now ignores case)**.** `write.matches` compares with `fnmatchcase`, and
  `realpath` restores the on-disk case only for the part of a path that
  exists. `Set-Content SRC/Auth/new.ts` against a scope of `src/auth/**` is
  therefore allowed when `SRC/Auth` exists (as `src/auth`) and denied when it
  does not. The error is a spurious deny, never a silent allow. Fixing it
  belongs in `write.py`, where it would change the Write and Bash gates too.
- **Over-reading.** A `>` inside a bare word (`echo a>b`) is read as a
  redirect although PowerShell passes `a>b` as one argument (measured); `sc`
  is read as `Set-Content` although PowerShell 7 runs `sc.exe`; a bare `::`
  in an argument (`rg std::vector`) is taken for a .NET call. Each errs
  toward a denial while a rule is active; quoting the argument avoids the
  last one.
- **Dynamic parameters** are in the tables as ordinary parameters, so
  `Set-Content x y -e utf8` is ambiguous here (`-Encoding`, `-Exclude`) while
  PowerShell binds `-Exclude`. The gate denies; the command was not doing
  what its author meant either.
- **Not read:** `--%` (stop-parsing), a `class` body beyond its nested
  blocks, `Set-ItemProperty` (file attributes, not content), `deno eval`,
  `php -r`, cmdlets from modules outside the list in decision 3 that write
  files (`Out-*` from a third-party module, `Save-*`). A third-party cmdlet
  is a program invoked by name.
- The tables were checked against PowerShell 7.7 (preview) on one machine.
  A cmdlet that gains a parameter in a later version makes a command using
  it opaque, not allowed.
- Not measured: that Claude Code honours a PreToolUse `deny` payload for the
  PowerShell tool the way it does for Bash and Write (the probe recorded hook
  inputs and did not send a decision back), whether one matcher
  `Bash|PowerShell` fires for both tools,
  the shape of `tool_input` when the model passes `timeout` or
  `run_in_background` to PowerShell or `args` to Skill (the gates read only
  `command` and `skill`, so extra keys are ignored), and whether a typed
  slash command for a skill with `disable-model-invocation` behaves the same.
