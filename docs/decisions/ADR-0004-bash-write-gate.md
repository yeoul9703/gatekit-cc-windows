# ADR-0004: The Bash tool is gated for writes, and unresolvable writes are denied

Amended by ADR-0025 (2026-10-02): a reserved word and a command substitution are read; only a certain write or arbitrary code is denied when unreadable; the limits are listed there.

## Context

`docs/ARCHITECTURE.md` §0 states that gates are hooks, not prose, and §3
registers a PreToolUse gate for `Write|Edit|MultiEdit|NotebookEdit`. Every
command in `plugin/commands/` also grants `Bash` in `allowed-tools`, and the
Bash matcher was registered on no hook at all.

The consequence was measured, not inferred. With `spec/` present and
`spec/05-gate.md` unapproved, the Write tool was denied with the
`spec_first` reason while `cat > src/x.ts` created the file. `sed -i`,
`tee`, `git apply` and `python3 -c "open(...,'w')"` behaved the same way.
The worker prompt built by `jobs.py` tells a scoped worker that writes
outside its scope "are denied by a hook, not by convention"; through Bash
that sentence was false. Rules (a) spec-before-code and (b) task
write-scope were therefore conventions for any agent that reached for the
shell, which is every agent.

## Decision

1. `hooks.json` registers a sixth hook, PreToolUse `Bash` →
   `gatekit/gates/bash.py`.
2. The gate **reads the command text statically** and extracts the paths it
   would write: redirections, `tee`, in-place `sed`/`perl`, copy/move/link
   destinations, `touch`/`rm`/`mkdir`/`truncate`/`chmod`/`chown` operands,
   `dd of=`, and the **literal output arguments** of common tools — `sort
   -o`, `curl -o/--output`, `wget -O`, `tar` extraction directory (`-C` or
   `.`) and creation archive (`-f`), `unzip -d`, `zip`'s archive. A tool
   whose output path is right there in argv is in scope: "we did not put
   it in the table" is not the same as "the binary's behaviour is
   unknowable". It tracks `cd` across command separators and newlines, strips
   `VAR=`/`sudo`/`env`/`nohup` prefixes, ignores here-document bodies and
   `/dev/*`, and parses `sh -c "…"` recursively. Each path is judged by the
   same function the Write gate uses (`write.decide_path`), so a shell
   redirect and a Write call get identical verdicts and identical reasons.
3. **Unresolvable writes are denied while a rule is active.** A path
   containing `$VAR` or backticks, `cd` to an unknown directory, `eval`,
   `xargs`, `patch`, `trap`, `find -exec`, working-tree `git` subcommands
   (including `init` and `clone`), inline interpreter code (`python3 -c`,
   `node -e`, `perl -e`), `awk`, editors driven from the command line
   (`ed`, `ex`, `vim`, `nano`, …), `busybox`, downloads that pick their own
   file name (`curl -O`, bare `wget`), process substitution and unbalanced
   quotes all make the command opaque. When rule (a) or (b)
   could deny a write, an opaque command is denied with a reason that names
   why and suggests the Write/Edit tool or a literal path. This is the same
   principle as the verdict vocabulary: "could not tell" is never rounded to
   "allowed".
4. **Fast path.** When neither rule could deny anything — no
   `GATEKIT_TASK_ID`, and the spec gate approved or `spec/` absent — the
   command is allowed without parsing. Ordinary sessions never pay for the
   gate.
5. The gate uses only `shlex`, `re`, `os` and `posixpath` (stdlib), exits 0
   on any internal error via `hookio.run`, and has allow, deny and
   internal-error tests like every other gate (§13).

## Consequences

- Rules (a) and (b) are now enforced for the shell, which is where an agent
  goes when the honest tool says no. The write-scope sentence in the worker
  prompt is true again.
- Programs invoked by name (`npm run build`, `python3 script.py`, `make`)
  are **not** inspected. The gate reads shell syntax; it does not know what
  every binary writes. This is a stated limit, not a gap to be closed by
  more regexes: a project that needs it declares its build steps as
  `gatekit-task` gates and lets the task's `write_scope` be checked after
  the fact.
- During spec authoring (rule (a) active), interactive one-liners that use a
  variable in a redirect target are refused. The reason text says why and
  what to do; the cost is one re-typed command. An independent review tried
  the cheap bypasses an agent reaches for after a denial (redirect
  spellings, `cd` tricks, nested shells, output flags, editors, archives)
  and each is now denied or resolved to its literal target; the review's
  list is in the gate's test file.
- Parsing is conservative on purpose. A heredoc terminator that is not on
  its own line, or a `>` inside an unquoted argument, can produce a false
  target; the failure mode is a spurious deny with a clear reason during an
  enforcing phase, never a silent allow.
- `doctor` axis 1 lists six gate scripts. The manual's gate table and the
  install page's axis table say six as well.
