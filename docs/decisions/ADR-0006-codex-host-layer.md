> **Not adopted in this fork.** This repository runs gatekit as a standalone,
> Claude-Code-only install (no plugin manager, no other host). Codex support
> described below was removed; kept here for history only.

# ADR-0006: Codex CLI as a second host, served by a generated layer, not a second source

## Context

gatekit ships as a Claude Code plugin. Its kernel (`plugin/gatekit/`) and
its six gates are host-agnostic Python, but the way they reach a session —
`hooks/hooks.json`, `commands/*.md`, `skills/*/SKILL.md` — is Claude Code's
plugin format. People who build with Codex CLI got the CLI and the
templates, and none of the gates: the write scope, the spawn scope, the
contract at Stop, the question budget were all absent, and nothing said so.

Codex CLI has its own hook system with the same stdin object and the same
deny and additionalContext payloads as Claude Code; only its Stop block
differs. It loads `.codex/hooks.json` from a trusted project, discovers
skills under `.agents/skills/`, and reads `AGENTS.md`. It has no plugin
format and no `AskUserQuestion` tool, and it edits files through
`apply_patch` rather than Write/Edit.

The owner's other starter kit solves multi-tool distribution with `ruler`,
an npm tool that fans one rules file out to per-tool copies. It manages
prose only, adds an npm dependency (ADR-0002 forbids one), and treats the
generated files as git-ignored build products, which is the opposite of
gatekit's committed, CI-checked layout.

## Decision

1. The gates learn their host from `--host <name>` on their own argv
   (`hookio.host_from_argv`, default `claude`) and `hookio.adapt_output`
   renders the Stop block in the host's dialect. One script per gate serves
   both hosts; nothing about a gate's decision logic depends on the host.
2. The write gate accepts Codex's `apply_patch`: every file named by a
   `*** Add/Update/Delete File:` or `*** Move to:` header is judged with the
   same `decide_path`, and a patch that names no file is refused while a rule
   is active.
3. `hosts.py` generates the Codex layer **from `plugin/`** with
   `gatekit install --host codex`: `.codex/hooks.json`, one skill per
   command (a short `SKILL.md` shim over a rewritten `command.md` copy), and
   a managed block in `AGENTS.md`. The plugin tree is the only source; the
   layer is a build product that is regenerated, never edited. This is what
   `ruler` does for prose, done in the standard library, for hooks and
   commands too.
4. `doctor` gains an eighth axis over the layer. Absent is `ok` because a
   Claude Code project needs none; present but pointing at missing gate
   scripts is `fail`.
5. Parity is published as a table with the verdict vocabulary. Anything not
   observed in a real Codex session is `unverified`, not "supported".

## Consequences

- A Codex user gets the same six gates as a Claude Code user, with the
  same reasons in the same language, from a git clone and one Python
  command. No npm, no second copy of any rule.
- Codex loads project hooks only after the user trusts the project's
  `.codex/` layer. gatekit cannot read that decision, so `hosts.status`
  never claims the hooks fire, and the install output tells the user to
  trust the project and start a new session.
- Observed in a real Codex 0.154 session after this ADR was first written:
  shell commands arrive as `Bash` events even when Codex runs them through
  its code-mode `exec` tool; `apply_patch` arrives as its own event carrying
  the patch text and is denied before approval; subagents spawn through
  `collaborationspawn_agent`, whose payload holds only a task name and an
  encrypted message, so the spawn gate allows it and records
  `spawn_unscoped` while the subagent's own writes (which arrive with
  `agent_id`) still meet the write and bash gates. There is no
  `AskUserQuestion`; the skill shim rewrites those steps as numbered options
  in plain chat and the question gate has nothing to count.
- `AGENTS.md` under Codex is the counterpart of `CLAUDE.md`; the managed
  block carries only operating rules, and the user's own text around it
  survives every reinstall.
- Antigravity is deliberately out of scope for this ADR: its hook payload
  is a different shape (`toolCall.name`/`args`, `conversationId`, no
  UserPromptSubmit), and it is deprecating workflows in favour of skills.
  The adapter seam introduced here (`host_from_argv`, `adapt_output`,
  `hosts.install`) is where it would attach, after a real installation is
  available to test against.
