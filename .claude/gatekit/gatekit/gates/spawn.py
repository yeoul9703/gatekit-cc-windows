"""PreToolUse gate for Agent / Task — every subagent declares its write scope.

Parallel agents that write to overlapping files silently clobber each other's
work. This gate makes the scope explicit and checks it before the subagent
starts: the spawn prompt must carry a fenced block

    ```gatekit-scope
    {"write_scope": ["src/auth/**"], "stop_when": "tests pass", "tools": "inherit"}
    ```

and the declared scope must not intersect one already claimed in this session.

The fence is parsed **as JSON**, never with a regex over prose. A prompt that
merely talks about ``write_scope`` in a sentence does not satisfy the gate, so
an agent cannot talk its way past enforcement.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio, ledger, paths  # noqa: E402

FENCE_NAME = "gatekit-scope"

READ_ONLY = "read-only"

_FENCE_RE = re.compile(
    r"^[ \t]*```[ \t]*(?P<name>[A-Za-z0-9_-]+)[ \t]*\r?\n(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)

_MESSAGES = {
    "en": {
        "missing": (
            "gatekit: this spawn has no ```{fence} fence. Add one to the prompt, "
            'e.g. {{"write_scope": ["src/auth/**"], "stop_when": "tests pass", '
            '"tools": "inherit"}} — or "read-only" for a reviewer.'
        ),
        "invalid": "gatekit: the ```{fence} fence is not usable: {detail}",
        "conflict": (
            "gatekit: write_scope {scope} overlaps a scope already active in this "
            "session ({owners}). Narrow the scope or wait for that agent to finish. "
            "A scope stays recorded after its agent ends; once it has finished, "
            "release it with: {release}"
        ),
    },
    "ko": {
        "missing": (
            "gatekit: 이 spawn 에는 ```{fence} 펜스가 없습니다. 프롬프트에 추가하세요. "
            '예: {{"write_scope": ["src/auth/**"], "stop_when": "테스트 통과", '
            '"tools": "inherit"}} — 리뷰 전용이면 "read-only".'
        ),
        "invalid": "gatekit: ```{fence} 펜스를 사용할 수 없습니다: {detail}",
        "conflict": (
            "gatekit: write_scope {scope} 가 이 세션에서 이미 활성화된 범위와 겹칩니다 "
            "({owners}). 범위를 좁히거나 해당 에이전트가 끝날 때까지 기다리세요. "
            "범위는 에이전트가 끝난 뒤에도 기록에 남습니다. 끝났다면 이 명령으로 해제하세요: {release}"
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


def extract_fence(text: str) -> Optional[str]:
    """Return the body of the first ``gatekit-scope`` fence, or ``None``."""
    for match in _FENCE_RE.finditer(text or ""):
        if match.group("name") == FENCE_NAME:
            return match.group("body")
    return None


def parse_scope(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parse and validate the scope declaration from a spawn prompt.

    Returns ``(declaration, "")`` on success or ``(None, reason)`` on failure.
    ``write_scope`` must be either the literal string ``read-only`` or a
    non-empty list of glob strings, and ``stop_when`` must be present: an agent
    with no stated finish condition cannot be checked against one.
    """
    body = extract_fence(text)
    if body is None:
        return None, "missing"

    try:
        parsed = json.loads(body)
    except ValueError as err:
        return None, f"not valid JSON ({err})"
    if not isinstance(parsed, dict):
        return None, "the fence must contain a JSON object"

    scope = parsed.get("write_scope")
    if isinstance(scope, str):
        if scope.strip() != READ_ONLY:
            return None, (
                f"write_scope must be a list of globs or the string '{READ_ONLY}'"
            )
        scope = READ_ONLY
    elif isinstance(scope, list):
        if not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            return None, "write_scope must be a non-empty list of glob strings"
        scope = [item.strip() for item in scope]
    else:
        return None, "write_scope is required (a list of globs or 'read-only')"

    stop_when = parsed.get("stop_when")
    if not isinstance(stop_when, str) or not stop_when.strip():
        return None, "stop_when is required and must be a non-empty string"

    tools = parsed.get("tools", "inherit")
    if not isinstance(tools, (str, list)):
        return None, "tools must be a list or the string 'inherit'"

    return {"write_scope": scope, "stop_when": stop_when.strip(), "tools": tools}, ""


def owner_label(tool_input: Dict[str, Any], prompt: str) -> str:
    """Human-readable owner for the recorded scope.

    Prefers the caller's ``description``; falls back to a short prompt hash so
    two anonymous agents remain distinguishable in the ledger.
    """
    description = tool_input.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:12]


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate the spawn's scope fence and record it, or deny."""
    root = hookio.event_root(event)
    session = hookio.session_id(event)
    tool_input = event.get("tool_input") or {}
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else ""
    prompt = prompt if isinstance(prompt, str) else ""

    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without touching it, rather than denying spawns (and
    # creating a ledger) in work gatekit has nothing to say about.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    led = ledger.Ledger.load(root, session)
    lang = led.output_lang

    declaration, problem = parse_scope(prompt)
    if declaration is None:
        reason = (
            _message(lang, "missing", fence=FENCE_NAME)
            if problem == "missing"
            else _message(lang, "invalid", fence=FENCE_NAME, detail=problem)
        )
        led.append_event("spawn_denied", {"why": problem})
        led.save()
        return hookio.deny(reason)

    scope = declaration["write_scope"]
    conflicts = led.scope_conflicts(scope)
    if conflicts:
        owners = ", ".join(str(c.get("owner", "?")) for c in conflicts)
        scope_text = scope if isinstance(scope, str) else ", ".join(scope)
        led.append_event("spawn_denied", {"why": "scope_conflict", "owners": owners})
        led.save()
        return hookio.deny(
            _message(
                lang, "conflict", scope=scope_text, owners=owners,
                release="%s ledger release-scopes --session %s" % (paths.cli_invocation(), session),
            )
        )

    owner = owner_label(tool_input if isinstance(tool_input, dict) else {}, prompt)
    led.add_scope(owner, scope)
    led.append_event(
        "scope_declared",
        {"owner": owner, "write_scope": scope, "stop_when": declaration["stop_when"]},
    )
    led.save()
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
