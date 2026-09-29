"""PostToolUse gate for AskUserQuestion — count questions, and judge the ones
past the budget.

An interview that keeps asking is an interview that never delivers, but a raw
count is a poor test: it permits waste inside the budget and forbids value
outside it. So the gate counts (``budget_exceeded``, unchanged) and then
records four signals that mean more than the count (ADR-0012):

``unjustified``
    An over-budget call the command could not say the purpose of. Past
    ``max_calls`` a command must write ``questions.justification`` — one line
    naming what it would write differently depending on the answer — *before*
    the call. The line is single-use.
``repeated``
    A call whose question text fingerprints onto an earlier call's. The
    policy's "you have already asked about this topic" made checkable.
``implementation_choice``
    A call whose options are all code tokens: the signature of handing the
    user a decision the command was better placed to make.
``unrealized``
    A justified call after which nothing was written before the next one. A
    justification claims the answer changes what gets written; whether
    anything was written is observable.

Every one of these is **informational**. PostToolUse has no block channel, and
pretending otherwise would be prose enforcement. Commands read the flags and
change their own behaviour.

Only the ``interview`` pipeline is budgeted (2 calls by default, configurable
via ``questions.interview_max_calls``). Other pipelines ask as needed, and
carry none of these signals.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import config, hookio, ledger, paths  # noqa: E402

#: The only pipeline with a question ceiling.
BUDGETED_PIPELINE = "interview"

#: The ledger schema default; a ledger holding this value has not been
#: deliberately overridden by a command.
DEFAULT_MAX_CALLS = 2

#: Fraction of the smaller question's content words two calls must share before
#: one counts as a repeat of the other. Deliberately high: the cost of a false
#: "you already asked this" is a command that stops asking something it should,
#: which is worse than missing a duplicate.
REPEAT_OVERLAP = 0.7
#: Below this many content words a question carries too little signal to
#: fingerprint; "ok?" and "no?" must never collide. Three is the floor a real
#: question reaches — "when should we commit this work" is three once the
#: scaffolding is dropped — so a higher bar would fingerprint nothing.
REPEAT_MIN_WORDS = 3
#: Words that carry no topic. Kept short and language-neutral: the point is to
#: drop scaffolding, not to build a stopword list.
_NOISE_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "for", "and", "or", "we", "you", "i", "it", "this", "that", "these",
    "those", "should", "shall", "would", "could", "do", "does", "did", "have",
    "has", "had", "will", "can", "may", "now", "then", "with", "at", "by",
})
_WORD_RE = re.compile(r"[0-9A-Za-z_./\-]+|[가-힣]+")
#: A code token: a path, a call, a dotted name, or an identifier with internal
#: case or underscores. Used only to warn, never to fail.
_CODE_TOKEN_RE = re.compile(
    r"""(?x)
    \w+\.(?:py|js|ts|json|md|html|css|sh|toml|ya?ml)\b   # a filename
    | \b\w+\(\)                                          # a call
    | \b\w+(?:/\w+)+                                     # a path
    | \b[a-z]+_[a-z_]+\b                                 # snake_case
    | \b[a-z]+[A-Z]\w*\b                                 # camelCase
    """
)
#: Share of a call's options that must read as code before it is warned about.
IMPLEMENTATION_OPTION_SHARE = 0.99


def _content_words(text: str) -> frozenset:
    """Topic-bearing words of *text*, lowercased and de-noised."""
    words = {w.lower() for w in _WORD_RE.findall(text or "")}
    return frozenset(w for w in words if w not in _NOISE_WORDS and len(w) > 1)


def question_topics(tool_input: Any) -> List[frozenset]:
    """One content-word fingerprint per question in *tool_input*."""
    if not isinstance(tool_input, dict):
        return []
    topics = []
    for item in tool_input.get("questions") or []:
        if not isinstance(item, dict):
            continue
        text = "%s %s" % (item.get("header") or "", item.get("question") or "")
        words = _content_words(text)
        if len(words) >= REPEAT_MIN_WORDS:
            topics.append(words)
    return topics


def repeats(topic: frozenset, earlier: List[Any]) -> Optional[int]:
    """1-based index of the earlier call *topic* repeats, or ``None``.

    Overlap is measured against the smaller fingerprint so that a question
    reworded at greater length still matches the shorter original.
    """
    for index, previous in enumerate(earlier, start=1):
        other = frozenset(previous or ())
        if len(other) < REPEAT_MIN_WORDS:
            continue
        smaller = min(len(topic), len(other))
        if smaller and len(topic & other) / smaller >= REPEAT_OVERLAP:
            return index
    return None


def looks_like_implementation_choice(tool_input: Any) -> bool:
    """True when every option of every question reads as code.

    The signature of asking the user to arbitrate a decision the command was
    better placed to make. A warning only: a question about implementation is
    sometimes exactly the right question.
    """
    if not isinstance(tool_input, dict):
        return False
    total = coded = 0
    for item in tool_input.get("questions") or []:
        if not isinstance(item, dict):
            continue
        for option in item.get("options") or []:
            if not isinstance(option, dict):
                continue
            total += 1
            text = "%s %s" % (option.get("label") or "", option.get("description") or "")
            if _CODE_TOKEN_RE.search(text):
                coded += 1
    if total == 0:
        return False
    return coded / total >= IMPLEMENTATION_OPTION_SHARE


def note_write(root, session: str) -> None:
    """Record that a file was written; clears the pending `unrealized` watch.

    Called by the write gate, which sees every Write and Edit. A justified
    question claims the answer changes what gets written, so a write after it
    is the claim coming true.
    """
    try:
        led = ledger.Ledger.load(root, session)
    except Exception:  # a ledger we cannot read must never break a write
        return
    questions = led.data.get("questions")
    if isinstance(questions, dict) and questions.get("awaiting_write"):
        questions["awaiting_write"] = False
        led.save()


def budget_for(
    cfg: Dict[str, Any],
    pipeline: Optional[str],
    session_limit: Optional[Any] = None,
) -> Optional[int]:
    """Maximum AskUserQuestion calls for *pipeline*, or ``None`` for unlimited.

    A ``max_calls`` already recorded in the ledger wins over the configured
    default: a command may tighten (or loosen) the budget for one session, and
    recomputing it from config on every call would silently erase that.
    """
    if pipeline != BUDGETED_PIPELINE:
        return None
    if session_limit is not None:
        try:
            return int(session_limit)
        except (TypeError, ValueError):
            pass
    try:
        return int(cfg.get("questions", {}).get("interview_max_calls", 2))
    except (TypeError, ValueError):
        return 2


#: Tools whose PostToolUse event means "something was written". The gate is
#: registered for these too, so a justification's promise can be observed
#: coming true (ADR-0012 decision 3).
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Count a question, or note a write. Never blocks."""
    root = hookio.event_root(event)
    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without creating state there.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    if event.get("tool_name") in WRITE_TOOLS:
        note_write(root, hookio.session_id(event))
        return hookio.allow()
    led = ledger.Ledger.load(root, hookio.session_id(event))

    questions = led.data.setdefault(
        "questions", {"asked": 0, "max_calls": 2, "budget_exceeded": False}
    )
    try:
        asked = int(questions.get("asked", 0)) + 1
    except (TypeError, ValueError):
        asked = 1
    questions["asked"] = asked

    pipeline = led.data.get("active_pipeline")
    # A blank ledger carries the schema default (2); only a value a command
    # deliberately changed counts as a session override.
    recorded = questions.get("max_calls")
    session_limit = recorded if recorded != DEFAULT_MAX_CALLS else None
    limit = budget_for(config.load(root), pipeline, session_limit)
    detail: Dict[str, Any] = {"asked": asked, "pipeline": pipeline, "max_calls": limit}

    if limit is not None:
        questions["max_calls"] = limit
        if asked > limit:
            questions["budget_exceeded"] = True

        tool_input = event.get("tool_input")

        # ADR-0012 decision 3, second half: settle the previous justified
        # call before recording this one. Nothing written since it means the
        # claim "the answer changes what I write" did not come true.
        if questions.pop("awaiting_write", False):
            questions["unrealized"] = int(questions.get("unrealized", 0) or 0) + 1
            detail["unrealized"] = True

        # decision 1: past the budget a call must arrive with its reason.
        if asked > limit:
            line = questions.get("justification")
            justified = isinstance(line, str) and line.strip()
            questions["justification"] = None
            if justified:
                detail["justified"] = line.strip()
                # Watch for the write this justification promised.
                questions["awaiting_write"] = True
            else:
                questions["unjustified"] = int(questions.get("unjustified", 0) or 0) + 1
                detail["unjustified"] = True

        # decision 2: the same topic twice. Not gated on the budget — asking
        # the same thing a second time is waste whether it is the second call
        # or the seventh.
        history = questions.setdefault("asked_topics", [])
        for topic in question_topics(tool_input):
            earlier = repeats(topic, history)
            if earlier is not None:
                questions["repeated"] = int(questions.get("repeated", 0) or 0) + 1
                questions["repeat_of"] = earlier
                detail["repeat_of"] = earlier
            history.append(sorted(topic))
        del history[:-50]  # a session's fingerprints, bounded

        # decision 4: options that are all code.
        if looks_like_implementation_choice(tool_input):
            questions["implementation_choice"] = True
            detail["implementation_choice"] = True

    led.append_event("question_asked", detail)
    led.save()
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
