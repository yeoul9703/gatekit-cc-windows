"""Host layers: run the gates and commands under a host other than Claude Code.

Claude Code loads gatekit as a plugin. Codex CLI has no plugin format, but it
reads the same three things from a project: hooks (``.codex/hooks.json``),
skills (``.agents/skills/<name>/SKILL.md``) and ``AGENTS.md``. This module
generates those files **from the plugin tree**, so ``plugin/`` stays the
single source and the host layer is a build product, never hand-edited.

* ``.codex/hooks.json`` registers the six gate scripts with ``--host codex``
  (see :mod:`gatekit.hookio`). Codex loads project hooks only once the
  project's ``.codex/`` layer is trusted; that trust cannot be read from
  here, so :func:`status` never claims the hooks fire.
* Each ``plugin/commands/<name>.md`` becomes a skill: ``SKILL.md`` is a
  short shim (the plugin's own trigger text plus the Codex differences) and
  ``command.md`` is the command body with ``${CLAUDE_PLUGIN_ROOT}`` and
  ``/gatekit:<name>`` rewritten for Codex.
* ``AGENTS.md`` gains a managed block between markers; text outside the
  markers is the user's and is never touched.

Everything here is stdlib and idempotent: installing twice yields the same
files.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional

from gatekit import config, paths, verdict

try:  # Python 3.11+
    import tomllib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only on 3.9/3.10 in CI
    tomllib = None  # type: ignore[assignment]

#: Hosts that need a generated layer. Claude Code is served by the plugin.
INSTALLABLE_HOSTS = ("codex",)

BLOCK_BEGIN = "<!-- gatekit:begin (managed; edit plugin/ and re-run install) -->"
BLOCK_END = "<!-- gatekit:end -->"

#: Gate registrations, mirroring plugin/hooks/hooks.json with the Codex
#: differences: file edits arrive as apply_patch, and unified exec matches
#: as Bash.
_CODEX_HOOKS = (
    ("UserPromptSubmit", None, "prompt.py", 10),
    ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit|apply_patch", "write.py", 10),
    ("PreToolUse", "Bash", "bash.py", 10),
    ("PreToolUse", "Agent|Task|collaborationspawn_agent", "spawn.py", 10),
    ("PostToolUse", "AskUserQuestion", "question.py", 10),
    ("Stop", None, "stop.py", None),  # timeout copied from the Claude hooks file
)

_SKILL_NOTES = """
## Differences under Codex

- Where the command says `AskUserQuestion`, ask the same options as a
  numbered list in plain chat and wait for the answer; Codex has no such tool.
  **Answering such a list with a bare number is the normal path here**, so it
  never changes the output language — keep replying in the language the
  conversation started in.
- Where the command says to run `WebSearch` (the domain research in
  `$gatekit-interview`), use whatever web search this session actually has.
  **If it has none, say so plainly and ask the user whether to skip that
  step or paste findings themselves** — do not route around it by spawning a
  subagent to "research" from memory. A proposal with no source is exactly
  what that step exists to avoid, and the command records a source line for
  every item it keeps.
- Where the command says to spawn an `Agent` with a ```gatekit-scope fence,
  keep the fence in the prompt you give the subagent; the spawn gate reads it.
- Commands are invoked as `$gatekit-<name>`, not `/gatekit:<name>`.
- Project hooks fire only after you trust this project's `.codex/` layer.
- Build workers and CLI evaluators are other agent CLIs (`claude`, `codex`)
  that need the user's login and network. Inside the Codex sandbox they fail
  with "Not logged in" (observed). Run `workers check <name> --probe` first,
  and run `jobs start`, `jobs redelegate` and `jobs evaluate` with escalated
  permissions when Codex asks; say so to the user before doing it.
"""

_AGENTS_BLOCK = """{begin}
# gatekit — operating rules for this project under Codex

gatekit is installed as a host layer: hooks in `.codex/hooks.json`, skills in
`.agents/skills/gatekit-*`. Do not edit those files; they are generated from
the gatekit plugin by `python3 "{launcher}" install --host codex`.

- Work spec-first. Until `spec/05-gate.md` is approved, write only under
  `spec/`, `docs/`, `.gatekit/` and root-level Markdown; the write gate denies
  anything else, including edits made through `apply_patch` and shell
  redirects.
- Invoke the pipeline as skills: `$gatekit-discover`, `$gatekit-interview`,
  `$gatekit-mockup`, `$gatekit-design`, `$gatekit-tasks`, `$gatekit-gate`,
  `$gatekit-build`, `$gatekit-verify`, `$gatekit-doctor`, `$gatekit-setup`.
- After writing any file under `spec/`, run
  `python3 "{launcher}" spec validate` and fix `fail` findings before
  reporting.
- Verdict words are exactly `ok / warn / fail / unverified`. `unverified` is
  never rounded to a pass or a failure.
- Codex has no `AskUserQuestion` tool: where a command calls for it, ask the
  same options as a numbered list in plain chat. A bare number in reply is a
  normal answer, not a switch to English — keep the conversation's language.
- A command that calls for web search (`$gatekit-interview`'s domain
  research) needs a real source. If this session has no web search, say so
  and ask whether to skip the step or have the user paste findings; never
  substitute a subagent recalling from memory.
- Do not claim a task is done; the gates and `contract run` decide.
- `jobs start`, `jobs redelegate` and `jobs evaluate` launch another agent
  CLI that needs the user's login and network; the Codex sandbox hides those
  (observed: "Not logged in"). Probe first with `workers check <name>
  --probe`, then run those commands with escalated permissions, telling the
  user why.
{end}
"""


def _launcher(plugin_root: pathlib.Path) -> str:
    return str(pathlib.Path(plugin_root) / "bin" / "gatekit.py")


def _claude_stop_timeout(plugin_root: pathlib.Path) -> int:
    hooks = json.loads((pathlib.Path(plugin_root) / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    return int(hooks["hooks"]["Stop"][0]["hooks"][0]["timeout"])


def codex_hooks(plugin_root: pathlib.Path) -> Dict[str, Any]:
    """The ``.codex/hooks.json`` document for this plugin checkout."""
    gates = pathlib.Path(plugin_root) / "gatekit" / "gates"
    stop_timeout = _claude_stop_timeout(plugin_root)
    events: Dict[str, List[dict]] = {}
    for event, matcher, script, timeout in _CODEX_HOOKS:
        entry: Dict[str, Any] = {}
        if matcher is not None:
            entry["matcher"] = matcher
        entry["hooks"] = [
            {
                "type": "command",
                "command": 'python3 "%s" --host codex' % (gates / script),
                "timeout": timeout if timeout is not None else stop_timeout,
            }
        ]
        events.setdefault(event, []).append(entry)
    return {"hooks": events}


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _frontmatter_field(text: str, key: str) -> str:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        if line.startswith(key + ":"):
            return line[len(key) + 1:].strip()
    return ""


def rewrite_command(text: str, plugin_root: pathlib.Path) -> str:
    """The command body as Codex must read it."""
    out = text.replace("${CLAUDE_PLUGIN_ROOT}", str(pathlib.Path(plugin_root)))
    names = sorted((p.stem for p in (pathlib.Path(plugin_root) / "commands").glob("*.md")), key=len, reverse=True)
    if names:
        # Only real command names, not preceded by a URL path character and
        # not followed by more identifier, become skill references.
        pattern = re.compile(r"(?<![\w/])/gatekit:(%s)(?![\w-])" % "|".join(re.escape(n) for n in names))
        out = pattern.sub(r"$gatekit-\1", out)
    return out


def skill_shim(name: str, description: str) -> str:
    return (
        "---\nname: gatekit-%s\ndescription: %s\n---\n\n# gatekit-%s\n\n"
        "Read `command.md` in this directory and follow it step by step; it is\n"
        "the execution instruction. This file only routes to it.\n%s"
        % (name, description or ("gatekit %s pipeline" % name), name, _SKILL_NOTES)
    )


def _agents_block(plugin_root: pathlib.Path) -> str:
    return _AGENTS_BLOCK.format(begin=BLOCK_BEGIN, end=BLOCK_END, launcher=_launcher(plugin_root))


def merged_agents_md(existing: Optional[str], plugin_root: pathlib.Path) -> str:
    """*existing* with the managed block replaced or appended."""
    block = _agents_block(plugin_root).rstrip("\n") + "\n"
    if not existing:
        return block
    if BLOCK_BEGIN in existing and BLOCK_END in existing:
        start = existing.index(BLOCK_BEGIN)
        end = existing.index(BLOCK_END, start) if BLOCK_END in existing[start:] else -1
        if end > start:
            return existing[:start] + block.rstrip("\n") + existing[end + len(BLOCK_END):]
        # markers out of order: leave the user's text alone and append a fresh block
    joiner = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    return existing + joiner + block


#: A `[hooks.state."<quoted key>"]` table header. Codex quotes the whole key
#: because it embeds `/`, `.` and `:`, which bare TOML keys cannot hold.
_HOOKS_STATE_HEADER_RE = re.compile(
    r'^\[hooks\.state\."((?:[^"\\]|\\.)*)"\]\s*$'
)


def _codex_home() -> pathlib.Path:
    """`$CODEX_HOME`, defaulting to `~/.codex` — Codex's own convention."""
    override = os.environ.get("CODEX_HOME")
    return pathlib.Path(override) if override else pathlib.Path.home() / ".codex"


def _trusted_hook_keys_fallback(text: str) -> List[str]:
    """`[hooks.state."<key>"]` table names, for Python 3.9/3.10 without
    `tomllib`.

    Not a general TOML reader: `~/.codex/config.toml` mixes plugin config,
    MCP server settings and other tables this gatekit has no reason to parse,
    so a full parser would be scope creep for a dependency-free build. This
    reads exactly one shape — the table headers under `[hooks.state]` — and
    ignores everything else in the file, including whether those tables carry
    a real `trusted_hash` key; a header existing at all is Codex's own record
    that the approval flow ran for that hook.
    """
    return [
        m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        for m in (_HOOKS_STATE_HEADER_RE.match(line) for line in text.splitlines())
        if m
    ]


def _trusted_hook_keys(text: str) -> List[str]:
    """Every `hooks.state` key in *text*, via `tomllib` when available."""
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            return []
        state = ((data.get("hooks") or {}).get("state") or {})
        return list(state) if isinstance(state, dict) else []
    return _trusted_hook_keys_fallback(text)


def codex_hooks_trusted(root: pathlib.Path) -> bool:
    """True when Codex has recorded trust for *this project's* `.codex/hooks.json`.

    ADR-0015. Codex tracks two kinds of trust separately: a project's own
    `trust_level`, and a per-hook `hooks.state."<hooks.json path>:<event>:*"`
    entry keyed by content hash. Only the second gates whether a hook actually
    fires — a trusted *project* with zero `hooks.state` entries for it (the
    real shape found on a fresh install) still has every project hook skipped
    silently. A malformed or unreadable config file, or no file at all, reads
    as **not trusted**: "could not tell" must never round to "trusted" here,
    the same rule the write gate itself applies to an unreadable task scope.
    """
    hooks_path = root / ".codex" / "hooks.json"
    if not hooks_path.is_file():
        return False
    config_path = _codex_home() / "config.toml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return False
    prefix = str(hooks_path.resolve()) + ":"
    return any(key.startswith(prefix) for key in _trusted_hook_keys(text))


def install(
    root: pathlib.Path,
    host: str,
    plugin_root: Optional[pathlib.Path] = None,
    dry_run: bool = False,
) -> dict:
    """Write the host layer into *root*. Returns ``{"host", "written": [rel paths]}``."""
    if host not in INSTALLABLE_HOSTS:
        if host == "claude":
            raise ValueError("Claude Code loads gatekit as a plugin; nothing to install into the project")
        raise ValueError("unknown host %r; installable hosts: %s" % (host, ", ".join(INSTALLABLE_HOSTS)))
    root = pathlib.Path(root)
    proot = pathlib.Path(plugin_root) if plugin_root else paths.plugin_root()
    planned: List[tuple] = []

    planned.append((root / ".codex" / "hooks.json", json.dumps(codex_hooks(proot), indent=2) + "\n"))

    for command in sorted((proot / "commands").glob("*.md")):
        name = command.stem
        body = command.read_text(encoding="utf-8")
        skill_dir = root / ".agents" / "skills" / ("gatekit-" + name)
        description = _frontmatter_field(body, "description")
        planned.append((skill_dir / "SKILL.md", skill_shim(name, description)))
        planned.append((skill_dir / "command.md", rewrite_command(body, proot)))

    agents = root / "AGENTS.md"
    existing = agents.read_text(encoding="utf-8") if agents.is_file() else None
    planned.append((agents, merged_agents_md(existing, proot)))

    real_root = root.resolve()
    for path, _ in planned:
        # A symlinked .codex/ or .agents/ must not carry the layer outside the
        # project; resolve the deepest existing ancestor and check it.
        probe = path.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        try:
            probe.resolve().relative_to(real_root)
        except ValueError:
            raise ValueError("%s resolves outside the project root; refusing to write" % path.relative_to(root))

    written: List[str] = []
    for path, content in planned:
        rel = path.relative_to(root).as_posix()
        written.append(rel)
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        config.write_text_atomic(path, content)
    return {"host": host, "written": written}


def status(root: pathlib.Path, host: str, plugin_root: Optional[pathlib.Path] = None) -> dict:
    """``{"verdict", "detail", "fix"}`` for the host layer in *root*.

    ``unverified`` when absent, ``fail`` when present but broken, ``ok`` when
    every registered gate script exists. Whether Codex actually loads the
    hooks depends on project trust, which is not readable from here.
    """
    root = pathlib.Path(root)
    proot = pathlib.Path(plugin_root) if plugin_root else paths.plugin_root()
    fix = 'python3 "%s" install --host %s' % (_launcher(proot), host)
    if host != "codex":
        return {"verdict": verdict.UNVERIFIED, "detail": "no host layer for %s" % host, "fix": ""}
    path = root / ".codex" / "hooks.json"
    if not path.is_file():
        return {"verdict": verdict.UNVERIFIED, "detail": ".codex/hooks.json absent", "fix": fix}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = data["hooks"]
        commands = [h["command"] for group in groups.values() for entry in group for h in entry["hooks"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"verdict": verdict.FAIL, "detail": ".codex/hooks.json unreadable: %s" % exc, "fix": fix}
    missing = []
    for command in commands:
        parts = command.split('"')
        script = parts[1] if len(parts) > 1 else ""
        if not script or not pathlib.Path(script).is_file():
            missing.append(script or command)
    if missing:
        return {"verdict": verdict.FAIL, "detail": "hook script missing: %s" % ", ".join(missing), "fix": fix}
    skills = root / ".agents" / "skills"
    count = len([p for p in skills.glob("gatekit-*/command.md")]) if skills.is_dir() else 0
    return {
        "verdict": verdict.OK,
        "detail": "%d hook commands, %d skills; whether Codex loads project hooks depends on trusting .codex/ (not checkable here)"
        % (len(commands), count),
        "fix": "",
    }


def run(argv: List[str]) -> int:
    """``python3 -m gatekit install --host codex [--root PATH] [--dry-run]``."""
    parser = argparse.ArgumentParser(prog="gatekit install", add_help=True)
    parser.add_argument("--host", required=True, help="host to generate a layer for (%s)" % ", ".join(INSTALLABLE_HOSTS))
    parser.add_argument("--root", default=None, help="project root (default: detected)")
    parser.add_argument("--dry-run", action="store_true", help="list the files without writing")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)
    root = pathlib.Path(args.root).expanduser() if args.root else paths.project_root()
    try:
        result = install(root, args.host, dry_run=args.dry_run)
    except ValueError as exc:
        print("gatekit install: %s" % exc, file=sys.stderr)
        return 2
    verb = "would write" if args.dry_run else "wrote"
    print("%s %d files for host %s under %s" % (verb, len(result["written"]), args.host, root))
    for rel in result["written"]:
        print("  " + rel)
    if not args.dry_run:
        print("next: trust this project's .codex/ layer in Codex, then start a new Codex session.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
