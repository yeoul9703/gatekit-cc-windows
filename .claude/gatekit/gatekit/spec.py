"""Spec set validation (`bin/gatekit.py spec validate`).

Validates the seven files under `spec/` against the canonical heading map and
the structural conventions the rest of gatekit depends on:

* which files exist (01-prd.md and 05-gate.md are required, rest warn;
  00-discovery.md is an optional stage whose absence is silent)
* 00-discovery.md: one ```gatekit-discovery fence; each unfilled deepening
  gate is a warn, never silent
* headings: every canonical heading present, no heading from the other
  language's set (cross-language residue is a hard fail)
* 01-prd.md: inline assumption blockquotes match the assumption ledger table,
  and no inline marker still cites a row a later row supersedes
* tokens.json: the v2 shape, when the file exists; every finding is a warn,
  because the kernel does not need this file to run
* 04-tasks.md: ```gatekit-task fences are well-formed and mutually consistent
* 05-gate.md: ```gatekit-criterion fences are well-formed, plus a
  "not counted as done" section
* traceability: every task id is referenced somewhere in 05-gate.md

Findings never round `unverified` to either side; see verdict.py.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional, TypeGuard, Union

from gatekit import lang as lang_mod
from gatekit import jobstore, paths
from gatekit import verdict as V

# --------------------------------------------------------------------------
# heading map
# --------------------------------------------------------------------------

_HEADING_MAP_CACHE: Optional[Dict[str, Any]] = None


def heading_map() -> Dict[str, Any]:
    """Load `gatekit-shared/assets/heading-map.json` (cached)."""
    global _HEADING_MAP_CACHE
    cached = _HEADING_MAP_CACHE
    if cached is None:
        path = paths.skill_dir("shared") / "assets" / "heading-map.json"
        with path.open(encoding="utf-8") as fh:
            cached = _HEADING_MAP_CACHE = json.load(fh)
    return cached


def spec_files() -> List[str]:
    return list(heading_map()["files"])


def required_files() -> List[str]:
    return list(heading_map()["required_files"])


def absent_ok_files() -> List[str]:
    """Optional stages: a missing file is not a finding."""
    return list(heading_map().get("absent_ok", []))


# --------------------------------------------------------------------------
# fence parsing
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<ticks>`{3,})[ \t]*(?P<name>[A-Za-z0-9_-]+)[ \t]*$"
)


def _iter_fences(text: str, name: str):
    """Yield (start_line_number, body_text) for each ```<name> fence.

    Line numbers are 1-based and point at the opening fence line, so error
    messages can name the exact place a malformed block starts.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _FENCE_RE.match(lines[i])
        if not match or match.group("name") != name:
            i += 1
            continue
        ticks = match.group("ticks")
        closing = re.compile(r"^[ \t]*" + "`" * len(ticks) + r"[ \t]*$")
        body: List[str] = []
        j = i + 1
        while j < len(lines) and not closing.match(lines[j]):
            body.append(lines[j])
            j += 1
        yield i + 1, "\n".join(body)
        i = j + 1


def parse_fences(text: str, name: str) -> List[dict]:
    """Return the decoded JSON object of every ```<name> fence in `text`.

    Malformed blocks are skipped here and reported by the validators, which
    use `_parse_fences_detailed` to keep the line number.
    """
    return [item for _, item, err in _parse_fences_detailed(text, name) if err is None]


def _parse_fences_detailed(text: str, name: str):
    """Yield (line_no, parsed_or_None, error_message_or_None)."""
    out = []
    for line_no, body in _iter_fences(text, name):
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            out.append((line_no, None, str(exc)))
            continue
        if not isinstance(parsed, dict):
            out.append((line_no, None, "fence body must be a JSON object"))
            continue
        out.append((line_no, parsed, None))
    return out


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


def _finding(file: str, verdict: str, message: str) -> dict:
    return {"file": file, "verdict": verdict, "message": message}


# --------------------------------------------------------------------------
# messages (localized; identifiers stay untranslated)
# --------------------------------------------------------------------------

MESSAGES = {
    "ko": {
        "missing_required": "필수 파일이 없습니다.",
        "missing_optional": "파일이 없습니다. 파이프라인이 아직 이 단계를 만들지 않았을 수 있습니다.",
        "unreadable": "파일을 읽을 수 없습니다: {err}",
        "heading_missing": "필수 제목이 없습니다: {heading}",
        "cross_lang": "다른 언어({other})의 제목이 섞여 있습니다: {heading}",
        "ledger_missing_section": "가정 원장 표를 찾을 수 없습니다.",
        "ledger_orphan_inline": "본문 가정 {num}번에 대응하는 원장 행이 없습니다.",
        "ledger_orphan_row": "원장 {num}번 행에 대응하는 본문 가정 표기가 없습니다.",
        "ledger_superseded": "본문이 아직 대체된 가정 A{num}을(를) 가리키고 있습니다. 이를 대체한 A{successor}을(를) 참조하도록 고치세요.",
        "ledger_blocking_unconfirmed": "가정 {num}번은 blocking(y)인데 아직 confirmed(n)입니다. 확인 전에는 다음 단계로 넘어갈 수 없습니다 (ADR-0017).",
        "preview_as_evidence": "근거 칸이 미리보기 파일({path})을 인용하고 있습니다. 미리보기는 이 명세에서 그린 것이므로 명세의 근거가 될 수 없습니다 (ADR-0011).",
        "tokens_unparsable": "spec/tokens.json 을 JSON 객체로 읽을 수 없습니다: {err}",
        "tokens_source": "source 는 {expect} 여야 합니다.",
        "tokens_patterns": "patterns 는 행 객체의 리스트여야 합니다.",
        "tokens_pattern_row": "patterns[{index}] 는 객체여야 합니다.",
        "tokens_pattern_key": "patterns[{index}] 에 {field} 가 없거나 비어 있습니다.",
        "tokens_pattern_applies_to": "patterns[{index}] 의 applies_to 는 \"all\" 이거나 화면 id 리스트여야 합니다.",
        "tokens_group": "{group} 은(는) 토큰 객체를 값으로 가져야 합니다.",
        "tokens_value": "{group}.{name} 의 값은 문자열이거나 객체여야 합니다.",
        "fence_malformed": "{line}번째 줄의 ```{name} 블록 JSON이 잘못되었습니다: {err}",
        "task_no_fences": "```gatekit-task 블록이 하나도 없습니다.",
        "task_is_verification": "작업 {id}은(는) 테스트 경로만 쓰면서 작업 {n}개에 의존합니다. 여러 작업이 끝나야 통과하는 검사는 작업이 아니라 spec/05-gate.md의 완료 기준입니다 — 작업으로 두면 마지막 하나가 끝날 때까지 매번 실패합니다 (ADR-0013).",
        "task_missing_id": "{line}번째 줄 작업 블록에 id가 없습니다.",
        "task_duplicate_id": "작업 id가 중복됩니다: {id}",
        "task_scope_empty": "작업 {id}의 write_scope가 비어 있습니다. 글롭 목록이거나 \"read-only\"여야 합니다.",
        "task_depends_unknown": "작업 {id}의 depends_on에 존재하지 않는 id가 있습니다: {dep}",
        "task_scope_collision": "같은 라운드({round})의 작업 {a}와 {b}의 write_scope가 겹칩니다: {glob_a} ↔ {glob_b}",
        "task_no_gate": "작업 {id}에 게이트가 없습니다. 최소 1개가 필요합니다.",
        "crit_no_fences": "```gatekit-criterion 블록이 하나도 없습니다.",
        "crit_missing_id": "{line}번째 줄 기준 블록에 id가 없습니다.",
        "crit_duplicate_id": "완료 기준 id가 중복됩니다: {id}",
        "crit_argv": "완료 기준 {id}의 argv는 비어 있지 않은 문자열 리스트여야 합니다.",
        "crit_expect": "완료 기준 {id}의 expect 가 잘못되었습니다: {detail}",
        "crit_not_done_section": "\"완료로 보지 않는 조건\" 절이 없습니다.",
        "trace_missing": "작업 {id}를 참조하는 완료 기준이 없습니다.",
        "progress_stale": "PROGRESS.md 가 마지막 잡 결과({job} · {when})보다 오래되었습니다. 세션이 중간에 끊긴 흔적입니다. `jobs results` 로 확인하고 갱신하세요.",
        "disc_no_fence": "```gatekit-discovery 블록이 정확히 하나 있어야 합니다 (현재 {count}개).",
        "disc_no_problem": "problem 이 비어 있습니다. 해법이 섞이지 않은 문제 문장 한 줄이 필요합니다.",
        "disc_gate_unfilled": "심화 게이트 {gate} 가 채워지지 않았습니다 ({why}). 일부러 건너뛰었다면 unpassed 에 적으세요.",
        "disc_gate_unpassed": "심화 게이트 {gate} 는 unpassed 로 선언되었습니다. interview 는 이 항목을 사실이 아니라 가정으로 읽습니다.",
        "disc_unknown_unpassed": "unpassed 에 알 수 없는 게이트 이름이 있습니다: {name}",
        "disc_unpassed_type": "unpassed 는 게이트 이름의 리스트여야 합니다.",
        "disc_unpassed_but_filled": "심화 게이트 {gate} 가 채워져 있는데 unpassed 에도 있습니다. 둘 중 하나를 고치세요.",
        "disc_deadline": "deadline 이 비어 있습니다. 없으면 \"none\" 이라고 적으세요.",
        "disc_user": "실사용자(user) 한 명의 이름·역할",
        "disc_current_way": "current_way 는 순서가 있는 단계 2개 이상",
        "disc_frequency_per_month": "frequency_per_month 는 숫자",
        "disc_minutes_per_run": "minutes_per_run 은 숫자",
        "disc_why_chain": "why_chain 은 문자열 리스트, 증상 + 서로 다른(바꿔 말하기 제외) '왜' 3칸 이상",
        "disc_failed_attempts": "failed_attempts 는 result 가 failed|works-but-costly 인 항목 1개 이상, 또는 \"not-applicable\"",
        "disc_insights_count_type": "insights_count 는 0 이상의 숫자여야 합니다.",
        "disc_insights_count_low": "insights_count 가 {count}로 낮습니다(최소 {floor} 권장). 상한은 없습니다 — 더 물어서 자연스럽게 늘어난 값을 적으세요.",
        "pains_not_list": "pains 는 리스트여야 합니다.",
        "pains_below_floor": "불편이 {count}개뿐입니다. 최소 3개를 먼저 채운 뒤 좁혀야 합니다 (ADR-0017). 사용자가 그만하라고 했다면 pain_floor_waived 를 true 로 적으세요.",
        "pain_not_object": "pains[{index}] 는 객체여야 합니다.",
        "pain_verdict_suggested_invalid": "pains[{index}].verdict_suggested.verdict 는 build|reuse|eliminate|unknown 중 하나여야 합니다.",
        "pain_verdict_suggested_no_why": "pains[{index}].verdict_suggested 에 근거(why)가 없습니다.",
        "pain_verdict_invalid": "pains[{index}].verdict 값이 잘못되었습니다: {value} (build|reuse|eliminate|unknown 중 하나)",
        "pains_chosen_count": "chosen 이 true 인 불편이 정확히 1개여야 합니다 (현재 {count}개).",
        "pain_verdict_blocks": "고른 문제의 확정 판정이 {verdict} 입니다 — 이 판정은 interview 진행을 막습니다 (ADR-0017). 없애거나 재활용할 것이면 이 문제를 만들지 않고 다른 불편을 고르세요.",
        "pain_verdict_unconfirmed": "고른 문제에 verdict_suggested 만 있고 사용자가 확정한 verdict 가 없습니다. 인터뷰어의 제안을 사용자 확인 없이 그대로 다음 단계로 넘기지 마세요 (ADR-0017).",
        "screens_required": "spec/02-screens.md 가 없습니다. 01-prd.md 가 화면을 수반하는 프로젝트로 보이므로(비UI로 선언하려면 목표가 아닌 것에 [non-ui] 표시), /gatekit-tasks 를 실행하기 전에 /gatekit-mockup 을 먼저 실행하세요 (ADR-0017).",
        "prototype_required": "화면 명세가 있는데 프로토타입 확정 기록이 없습니다. /gatekit-mockup 이 만든 살아있는 HTML 프로토타입을 사용자가 확인·수정한 뒤 확정해야 /gatekit-tasks 를 진행할 수 있습니다 (ADR-0017).",
        "ok": "검사를 통과했습니다.",
    },
    "en": {
        "missing_required": "Required file is missing.",
        "missing_optional": "File is missing. The pipeline may not have produced this stage yet.",
        "unreadable": "File could not be read: {err}",
        "heading_missing": "Required heading is missing: {heading}",
        "cross_lang": "A heading from the other language ({other}) is present: {heading}",
        "ledger_missing_section": "Assumption ledger table not found.",
        "ledger_orphan_inline": "Inline assumption {num} has no matching ledger row.",
        "ledger_orphan_row": "Ledger row {num} has no matching inline assumption marker.",
        "ledger_superseded": "The text still points at superseded assumption A{num}. Reference A{successor}, which supersedes it.",
        "ledger_blocking_unconfirmed": "Assumption {num} is blocking (y) but still not confirmed (n). This must be confirmed before proceeding (ADR-0017).",
        "preview_as_evidence": "An evidence cell cites a preview file ({path}). A preview is drawn from this spec, so it cannot be evidence for it (ADR-0011).",
        "tokens_unparsable": "spec/tokens.json could not be read as a JSON object: {err}",
        "tokens_source": "source must be {expect}.",
        "tokens_patterns": "patterns must be a list of row objects.",
        "tokens_pattern_row": "patterns[{index}] must be an object.",
        "tokens_pattern_key": "patterns[{index}] is missing a non-empty {field}.",
        "tokens_pattern_applies_to": "patterns[{index}] needs applies_to to be \"all\" or a list of screen ids.",
        "tokens_group": "{group} must map to an object of tokens.",
        "tokens_value": "{group}.{name} must be a string or an object.",
        "fence_malformed": "Malformed JSON in the ```{name} block at line {line}: {err}",
        "task_no_fences": "No ```gatekit-task blocks found.",
        "task_is_verification": "Task {id} writes only test paths and depends on {n} tasks. A check that passes only once several tasks are done is a completion criterion in spec/05-gate.md, not a task — left as a task it fails on every attempt until the last one lands (ADR-0013).",
        "task_missing_id": "The task block at line {line} has no id.",
        "task_duplicate_id": "Duplicate task id: {id}",
        "task_scope_empty": "Task {id} has an empty write_scope. Use a list of globs or \"read-only\".",
        "task_depends_unknown": "Task {id} depends on an unknown id: {dep}",
        "task_scope_collision": "Tasks {a} and {b} in round {round} have intersecting write_scope: {glob_a} vs {glob_b}",
        "task_no_gate": "Task {id} has no gate. At least one is required.",
        "crit_no_fences": "No ```gatekit-criterion blocks found.",
        "crit_missing_id": "The criterion block at line {line} has no id.",
        "crit_duplicate_id": "Duplicate criterion id: {id}",
        "crit_argv": "Criterion {id} needs argv to be a non-empty list of strings.",
        "crit_expect": "Criterion {id} has an invalid expect: {detail}",
        "crit_not_done_section": "The \"not counted as done\" section is missing.",
        "trace_missing": "No completion criterion references task {id}.",
        "progress_stale": "PROGRESS.md is older than the latest job result ({job} · {when}); a session was cut short. Check `jobs results` and update it.",
        "disc_no_fence": "Exactly one ```gatekit-discovery block is required (found {count}).",
        "disc_no_problem": "problem is empty. One problem sentence with no solution in it is required.",
        "disc_gate_unfilled": "Deepening gate {gate} is not filled ({why}). If it was skipped on purpose, list it in unpassed.",
        "disc_gate_unpassed": "Deepening gate {gate} is declared unpassed. interview reads this item as an assumption, not a fact.",
        "disc_unknown_unpassed": "unpassed names an unknown gate: {name}",
        "disc_unpassed_type": "unpassed must be a list of gate names.",
        "disc_unpassed_but_filled": "Deepening gate {gate} is filled but also listed in unpassed. Fix one of the two.",
        "disc_deadline": "deadline is empty. Write \"none\" when there is none.",
        "disc_user": "user must name one real person with a role",
        "disc_current_way": "current_way needs at least two ordered steps",
        "disc_frequency_per_month": "frequency_per_month must be a number",
        "disc_minutes_per_run": "minutes_per_run must be a number",
        "disc_why_chain": "why_chain must be a list of strings: the symptom plus at least three distinct (not reworded) whys",
        "disc_failed_attempts": "failed_attempts needs one entry with result failed|works-but-costly, or \"not-applicable\"",
        "disc_insights_count_type": "insights_count must be a number >= 0.",
        "disc_insights_count_low": "insights_count is low ({count}, {floor}+ recommended). There is no ceiling — ask more and record the naturally higher number.",
        "pains_not_list": "pains must be a list.",
        "pains_below_floor": "Only {count} pain(s) surfaced. At least 3 must be surfaced before narrowing (ADR-0017). If the user gave a stop signal, record pain_floor_waived: true.",
        "pain_not_object": "pains[{index}] must be an object.",
        "pain_verdict_suggested_invalid": "pains[{index}].verdict_suggested.verdict must be one of build|reuse|eliminate|unknown.",
        "pain_verdict_suggested_no_why": "pains[{index}].verdict_suggested is missing its justification (why).",
        "pain_verdict_invalid": "pains[{index}].verdict has an invalid value: {value} (must be build|reuse|eliminate|unknown)",
        "pains_chosen_count": "Exactly one pain must have chosen: true (found {count}).",
        "pain_verdict_blocks": "The chosen pain's confirmed verdict is {verdict} — this verdict blocks progressing to interview (ADR-0017). If it should be eliminated or reused, pick a different pain instead of building this one.",
        "pain_verdict_unconfirmed": "The chosen pain has a verdict_suggested but no user-confirmed verdict. Do not carry the interviewer's proposal into the next stage without the user confirming it (ADR-0017).",
        "screens_required": "spec/02-screens.md is missing. 01-prd.md appears to be a UI-bearing project (mark it [non-ui] in Non-goals to declare otherwise); run /gatekit-mockup before /gatekit-tasks (ADR-0017).",
        "prototype_required": "A screen spec exists but no prototype confirmation is recorded. The user must open, revise, and confirm the live HTML prototype /gatekit-mockup built before /gatekit-tasks can proceed (ADR-0017).",
        "ok": "Checks passed.",
    },
}


def _msg(lang: str, key: str, **kw) -> str:
    table = MESSAGES.get(lang) or MESSAGES["en"]
    template = table.get(key) or MESSAGES["en"][key]
    return template.format(**kw)


# --------------------------------------------------------------------------
# assumption ledger
# --------------------------------------------------------------------------

# Inline markers look like:  > ⚠️ 가정: ... (A3)   /   > ⚠️ Assumption 3: ...
_INLINE_ASSUMPTION_RE = re.compile(
    r"^\s*>\s*(?:⚠️|⚠)?\s*(?:가정|Assumption)\s*"
    r"(?:[#A]?\s*(?P<num1>\d+))?\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_TRAILING_NUM_RE = re.compile(r"\(\s*[A#]?\s*(?P<num>\d+)\s*\)\s*$")
# Ledger rows look like:  | A3 | ... | ... | ... |
_LEDGER_ROW_RE = re.compile(r"^\s*\|\s*[A#]?\s*(?P<num>\d+)\s*\|")


def _inline_assumption_numbers(text: str) -> List[int]:
    nums: List[int] = []
    for line in text.splitlines():
        match = _INLINE_ASSUMPTION_RE.match(line)
        if not match:
            continue
        num = match.group("num1")
        if num is None:
            trailing = _TRAILING_NUM_RE.search(match.group("rest").strip())
            num = trailing.group("num") if trailing else None
        if num is not None:
            nums.append(int(num))
    return nums


def _ledger_section(text: str, lang: str) -> Optional[str]:
    """Return the text of the assumption-ledger section, or None."""
    headings = heading_map()[lang]["01-prd.md"]
    ledger_heading = headings[-1]  # ledger is the last canonical heading
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == ledger_heading:
            start = idx + 1
            break
    if start is None:
        return None
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end])


def _ledger_row_numbers(section: str) -> List[int]:
    nums: List[int] = []
    for line in section.splitlines():
        match = _LEDGER_ROW_RE.match(line)
        if not match:
            continue
        # skip the separator row (|---|---|) — it never matches the digit rule
        nums.append(int(match.group("num")))
    return nums


# A design input that contradicts an existing assumption does not delete its
# row; it appends one whose evidence says which row it retires (ADR-0008
# decision 8). Both language forms are recognised because the ledger is written
# in the project's output_lang.
#
# Both forms require an explicit ``A<n>`` row reference. A bare digit before
# 대체 is ordinary prose — "카드 3 대체 수단을 지원한다" is about fallbacks, not
# about retiring ledger row 3 — and matching it retired rows on the strength of
# an unrelated sentence.
_SUPERSEDES_RE = re.compile(
    r"(?:supersedes\s*[A#]\s*(?P<num_en>\d+)"
    r"|[A#]\s*(?P<num_ko>\d+)\s*(?:번\s*)?대체"
    r"|대체\s*[:：]\s*[A#]\s*(?P<num_ko2>\d+))",
    re.IGNORECASE,
)


def _supersessions(section: str) -> Dict[int, int]:
    """``{superseded_row: superseding_row}`` from the ledger's evidence cells."""
    out: Dict[int, int] = {}
    for line in section.splitlines():
        row = _LEDGER_ROW_RE.match(line)
        if not row:
            continue
        successor = int(row.group("num"))
        # Look only past the row's own id cell, so `| A2 | ... |` never reads
        # its own number as the one it supersedes.
        rest = line.split("|", 2)[-1]
        for match in _SUPERSEDES_RE.finditer(rest):
            num = match.group("num_en") or match.group("num_ko") or match.group("num_ko2")
            if num is None:
                continue
            superseded = int(num)
            if superseded != successor:
                out[superseded] = successor
    return out


#: ADR-0011 decision 4. A preview is a *local* `preview-<name>.html` this tool
#: drew. Matched on the basename so `spec/design/preview-x.html` and a bare
#: `preview-x.html` are both caught, while `apple-preview.html` — a captured
#: source, not a drawing — is not.
_PREVIEW_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[\w./-]*/)?(preview-[\w.-]*\.html)(?![\w])", re.IGNORECASE
)
#: A cell naming a remote page cites something *observed*, which is exactly the
#: evidence this spec is supposed to carry — even when the vendor happens to
#: call their page `preview-something.html`. Only local paths are drawings.
_REMOTE_URL_RE = re.compile(r"\b(?:https?|ftp)://\S+", re.IGNORECASE)
#: Fenced blocks are pictures of markdown, not markdown: a row shown inside one
#: is documentation of the rule, not a citation subject to it.
_FENCE_LINE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})")


def _check_preview_citations(name: str, text: str, lang: str) -> List[dict]:
    """A preview file must never be cited as evidence in this spec.

    The preview is drawn *from* this spec; citing it back would let the spec
    corroborate itself, turning something designed into something observed.
    Only table rows outside fenced blocks are checked — prose that mentions the
    preview ("the owner looked at it") is not a citation, and neither is a
    fenced example showing what a bad row looks like. A remote URL is spared
    whatever it is named: fetching a live page is observation.
    """
    findings: List[dict] = []
    seen = set()
    fence = None
    for line in (text or "").splitlines():
        marker = _FENCE_LINE_RE.match(line)
        if marker:
            mark = marker.group(0).strip()[0]
            if fence is None:
                fence = mark
            elif mark == fence:
                fence = None
            continue
        if fence is not None:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # Drop remote URLs before matching: a vendor page called
        # `preview-widget.html` is an observed source, not our drawing.
        scannable = _REMOTE_URL_RE.sub(" ", stripped)
        for match in _PREVIEW_PATH_RE.finditer(scannable):
            path = match.group(1)
            if path in seen:
                continue
            seen.add(path)
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "preview_as_evidence", path=path))
            )
    return findings


#: ADR-0017 decision 5. Two new optional trailing columns on the ledger table:
#: `Blocking` (y/n — is this row load-bearing enough that being wrong sinks
#: the plan) and `Confirmed` (y/n — has anyone actually verified it). Both
#: columns are additive: a row with neither (every pre-ADR-0017 ledger) is
#: untouched by this check. Two columns rather than one, because the
#: template's existing prose convention ("when confirmed, replace the basis
#: with the confirmed fact") cannot be checked mechanically — there is no way
#: to tell "this basis cell was rewritten to a confirmed fact" from "this
#: basis cell always read this" by pattern-matching text alone.
_YES_NO_RE = re.compile(r"^\s*(y|n|yes|no)\s*$", re.IGNORECASE)


def _row_cells(line: str) -> List[str]:
    """Split a markdown table row into its cell texts, dropping the empty
    leading/trailing pieces `"| a | b |".split("|")` produces."""
    parts = line.strip().split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _is_yes(cell: Optional[str]) -> bool:
    return bool(cell) and cell.strip().lower() in ("y", "yes")


def _blocking_unconfirmed_rows(section: str) -> List[int]:
    """Ledger row numbers marked blocking (y) with confirmed not (y).

    Only rows carrying *both* trailing columns are considered — a ledger
    table with neither column has nothing for this check to see, which is
    the backward-compatibility guarantee `test_spec_blocking_assumptions.py`
    pins.
    """
    out: List[int] = []
    for line in section.splitlines():
        row = _LEDGER_ROW_RE.match(line)
        if not row:
            continue
        cells = _row_cells(line)
        if len(cells) < 7:
            continue  # no Blocking/Confirmed columns on this row
        blocking, confirmed = cells[-2], cells[-1]
        if not (_YES_NO_RE.match(blocking) and _YES_NO_RE.match(confirmed)):
            continue
        if _is_yes(blocking) and not _is_yes(confirmed):
            out.append(int(row.group("num")))
    return out


def _check_ledger(text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    section = _ledger_section(text, lang)
    if section is None:
        # the heading check already reported the missing heading
        return findings
    inline = _inline_assumption_numbers(text)
    rows = _ledger_row_numbers(section)
    inline_set, row_set = set(inline), set(rows)
    for num in sorted(inline_set - row_set):
        findings.append(
            _finding("01-prd.md", V.FAIL, _msg(lang, "ledger_orphan_inline", num=num))
        )
    for num in sorted(row_set - inline_set):
        findings.append(
            _finding("01-prd.md", V.WARN, _msg(lang, "ledger_orphan_row", num=num))
        )
    # A superseded row that the text still cites, while nothing cites the row
    # that replaced it, means the reader is being sent to the retired answer.
    for superseded, successor in sorted(_supersessions(section).items()):
        if superseded in inline_set and successor not in inline_set:
            findings.append(
                _finding(
                    "01-prd.md",
                    V.WARN,
                    _msg(lang, "ledger_superseded", num=superseded, successor=successor),
                )
            )
    # ADR-0017 decision 5: blocking(y) + confirmed(n) fails outright — the
    # owner's explicit strict choice over the milder warn-only alternative.
    for num in sorted(_blocking_unconfirmed_rows(section)):
        findings.append(
            _finding("01-prd.md", V.FAIL, _msg(lang, "ledger_blocking_unconfirmed", num=num))
        )
    return findings


# --------------------------------------------------------------------------
# headings
# --------------------------------------------------------------------------


def _present_headings(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            out.append(re.sub(r"\s+", " ", stripped))
    return out


def _check_headings(name: str, text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    hm = heading_map()
    other = "en" if lang == "ko" else "ko"
    canonical = hm[lang].get(name, [])
    other_set = set(hm[other].get(name, []))
    present = _present_headings(text)
    present_set = set(present)

    for heading in canonical:
        if heading not in present_set:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "heading_missing", heading=heading))
            )
    # Cross-language residue: a heading that belongs to the other language's
    # canonical set for this file and is not also valid in this language.
    canonical_set = set(canonical)
    for heading in present:
        if heading in other_set and heading not in canonical_set:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(lang, "cross_lang", other=other, heading=heading),
                )
            )
    return findings


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------


def _scope_globs(task: dict) -> List[str]:
    scope = task.get("write_scope")
    if isinstance(scope, str):
        return [] if scope == "read-only" else [scope]
    if isinstance(scope, list):
        return [g for g in scope if isinstance(g, str) and g.strip()]
    return []


#: Directory names that mark a path as test material rather than product code.
#: A task writing only these produces nothing a user touches, which — combined
#: with depending on several tasks — is the signature of a verification step
#: masquerading as a task (ADR-0013 decision 5).
_TEST_DIR_SEGMENTS = ("tests", "test", "e2e", "spec", "__tests__", "cypress",
                      "features", "integration")
#: Config files that belong to a test runner, so a scope holding one plus test
#: directories is still test-only.
_TEST_CONFIG_STEMS = ("playwright.config", "vitest.config", "jest.config",
                      "cypress.config", "karma.conf", "conftest")


def _transitive_deps(task_id: str, by_id: Dict[str, dict]) -> set:
    """Every task *task_id* depends on, directly or through another.

    Direct count is the wrong measure: a check at the end of a chain names one
    dependency and still needs everything behind it. `e2e-full-flow` on the
    gk-trial2 run declared exactly one, and waited on all eight.
    """
    seen: set = set()
    stack = [d for d in (by_id.get(task_id, {}).get("depends_on") or [])
             if isinstance(d, str)]
    while stack:
        dep = stack.pop()
        if dep in seen or dep == task_id or dep not in by_id:
            continue
        seen.add(dep)
        stack.extend(d for d in (by_id[dep].get("depends_on") or [])
                     if isinstance(d, str))
    return seen


def _writes_only_tests(task: dict) -> bool:
    """True when every glob in the task's write scope is test material.

    A `read-only` scope is not: it writes nothing at all, which is a different
    thing (an investigation task) and must not be warned about.
    """
    globs = _scope_globs(task)
    if not globs:
        return False
    for glob in globs:
        parts = [p for p in glob.replace("\\", "/").split("/") if p and p != "."]
        if not parts:
            return False
        stem = parts[-1].split(".")[0]
        if any(p in _TEST_DIR_SEGMENTS for p in parts):
            continue
        if any(stem == s.split(".")[0] for s in _TEST_CONFIG_STEMS):
            continue
        return False
    return True


def _not_done_heading(lang: str) -> str:
    """Return the canonical 'not counted as done' heading for *lang* by name.

    Looked up by content rather than by position so reordering
    heading-map.json cannot silently change which section is required.
    """
    headings = heading_map()[lang]["05-gate.md"]
    for h in headings:
        low = h.lower()
        if "not counted" in low or "완료로 보지 않는" in h:
            return h
    return headings[-1]


def _globs_intersect(a: str, b: str) -> bool:
    """Delegate to the ledger's single implementation so `spec validate` and the
    spawn gate can never disagree about what collides."""
    from gatekit.ledger import globs_intersect
    return globs_intersect(a, b)


def _check_tasks(text: str, lang: str) -> List[dict]:
    name = "04-tasks.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-task")
    for line_no, _parsed, err in detailed:
        if err is not None:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(lang, "fence_malformed", line=line_no, name="gatekit-task", err=err),
                )
            )
    tasks = [(line_no, p) for line_no, p, err in detailed if err is None]
    if not tasks:
        if not any(err for _, _, err in detailed):
            findings.append(_finding(name, V.FAIL, _msg(lang, "task_no_fences")))
        return findings

    seen: set = set()
    ids: List[str] = []
    for line_no, task in tasks:
        tid = task.get("id")
        if not isinstance(tid, str) or not tid.strip():
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_missing_id", line=line_no))
            )
            continue
        if tid in seen:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_duplicate_id", id=tid))
            )
        seen.add(tid)
        ids.append(tid)

    for _, task in tasks:
        tid = task.get("id")
        if not isinstance(tid, str):
            continue
        scope = task.get("write_scope")
        if scope != "read-only" and not _scope_globs(task):
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "task_scope_empty", id=tid))
            )
        for dep in task.get("depends_on") or []:
            if dep not in seen:
                findings.append(
                    _finding(
                        name, V.FAIL, _msg(lang, "task_depends_unknown", id=tid, dep=dep)
                    )
                )
        gates = task.get("gates")
        if not isinstance(gates, list) or not gates:
            findings.append(_finding(name, V.FAIL, _msg(lang, "task_no_gate", id=tid)))
        # ADR-0013 decision 5: a check that only passes once several other
        # tasks are done belongs in 05-gate.md. As a task it fails on every
        # attempt until the last dependency lands — `e2e-full-flow` failed five
        # times that way, while the same command already sat in the gate file.
        if _writes_only_tests(task):
            reach = len(_transitive_deps(tid, {str(x.get("id")): x for _, x in tasks}))
            if reach >= 2:
                findings.append(
                    _finding(name, V.WARN,
                             _msg(lang, "task_is_verification", id=tid, n=reach))
                )

    # same-round write_scope intersection
    by_round: Dict[Any, List[dict]] = {}
    for _, task in tasks:
        by_round.setdefault(task.get("round", 1), []).append(task)
    for round_key, group in by_round.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                for glob_a in _scope_globs(a):
                    for glob_b in _scope_globs(b):
                        if _globs_intersect(glob_a, glob_b):
                            findings.append(
                                _finding(
                                    name,
                                    V.FAIL,
                                    _msg(
                                        lang,
                                        "task_scope_collision",
                                        round=round_key,
                                        a=a.get("id"),
                                        b=b.get("id"),
                                        glob_a=glob_a,
                                        glob_b=glob_b,
                                    ),
                                )
                            )
    return findings


# --------------------------------------------------------------------------
# gate criteria
# --------------------------------------------------------------------------


def _check_criteria(text: str, lang: str) -> List[dict]:
    name = "05-gate.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-criterion")
    for line_no, _parsed, err in detailed:
        if err is not None:
            findings.append(
                _finding(
                    name,
                    V.FAIL,
                    _msg(
                        lang,
                        "fence_malformed",
                        line=line_no,
                        name="gatekit-criterion",
                        err=err,
                    ),
                )
            )
    criteria = [(line_no, p) for line_no, p, err in detailed if err is None]
    if not criteria and not any(err for _, _, err in detailed):
        findings.append(_finding(name, V.FAIL, _msg(lang, "crit_no_fences")))

    seen: set = set()
    for line_no, crit in criteria:
        cid = crit.get("id")
        if not isinstance(cid, str) or not cid.strip():
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "crit_missing_id", line=line_no))
            )
            continue
        if cid in seen:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "crit_duplicate_id", id=cid))
            )
        seen.add(cid)
        argv = crit.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(a, str) and a != "" for a in argv)
        ):
            findings.append(_finding(name, V.FAIL, _msg(lang, "crit_argv", id=cid)))
        if "expect" in crit and crit["expect"] is not None:
            from gatekit import contract as contract_mod

            for problem in contract_mod.validate_expect(crit["expect"], cid):
                findings.append(_finding(name, V.FAIL, _msg(lang, "crit_expect", id=cid, detail=problem)))

    not_done = _not_done_heading(lang)
    if not_done not in set(_present_headings(text)):
        findings.append(_finding(name, V.FAIL, _msg(lang, "crit_not_done_section")))
    return findings


# --------------------------------------------------------------------------
# traceability
# --------------------------------------------------------------------------


def _check_traceability(tasks_text: str, gate_text: str, lang: str) -> List[dict]:
    findings: List[dict] = []
    task_ids: List[str] = [
        tid
        for t in parse_fences(tasks_text, "gatekit-task")
        if isinstance(tid := t.get("id"), str)
    ]
    for tid in task_ids:
        if tid not in gate_text:
            findings.append(
                _finding("05-gate.md", V.WARN, _msg(lang, "trace_missing", id=tid))
            )
    return findings


# --------------------------------------------------------------------------
# progress freshness
# --------------------------------------------------------------------------

#: The one definition lives in jobstore: a stopped or blocked task is finished too.
_TERMINAL_STATES = jobstore.TERMINAL_STATES


def _latest_job_finish(root: pathlib.Path):
    """``(job_id, iso)`` of the most recent terminal task status, or ``None``."""
    jobs_dir = paths.state_dir(root) / "jobs"
    if not jobs_dir.is_dir():
        return None
    latest = None
    for status_path in jobs_dir.glob("*/tasks/*/status.json"):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("state") not in _TERMINAL_STATES:
            continue
        stamp = data.get("finished_at") or data.get("updated_at")
        if not isinstance(stamp, str):
            continue
        job_id = status_path.parents[2].name
        if latest is None or stamp > latest[1]:
            latest = (job_id, stamp)
    return latest


def _iso_to_epoch(stamp: str) -> Optional[float]:
    import datetime as _dt

    text = stamp.strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


def _check_progress_freshness(root: pathlib.Path, lang: str) -> List[dict]:
    """A PROGRESS.md written before the latest job finished is stale: the
    session that ran the job ended before Step 5 could record the result."""
    progress = paths.spec_dir(root) / "PROGRESS.md"
    if not progress.is_file():
        return []
    latest = _latest_job_finish(root)
    if latest is None:
        return []
    finished = _iso_to_epoch(latest[1])
    if finished is None:
        return []
    try:
        mtime = progress.stat().st_mtime
    except OSError:
        return []
    if mtime + 1.0 >= finished:
        return []
    return [_finding("PROGRESS.md", V.WARN, _msg(lang, "progress_stale", job=latest[0], when=latest[1]))]


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

#: The deepening gates, in the order the command fills them. Each unfilled
#: gate is a ``warn`` so the record stays honest about what it lacks.
DISCOVERY_GATES = (
    "user",
    "current_way",
    "frequency_per_month",
    "minutes_per_run",
    "why_chain",
    "failed_attempts",
)

_ATTEMPT_RESULTS = ("failed", "works-but-costly")

#: Two why-links whose word sets overlap this much are the same statement
#: reworded. A word-overlap test is a heuristic, not understanding: it catches
#: "files hard to find" / "hard to find files", not a true synonym. It is the
#: honest limit of a stdlib validator, and the command still requires the
#: user to confirm the cause in their own words.
_RESTATEMENT_OVERLAP = 0.6

_STOPWORDS = frozenset(
    "a an the is are was were be been it its of to in on at for and or but "
    "that this these those there they them we you i my our your not no so "
    "because since when then than very just".split()
)


def _word_set(text: str) -> set:
    words = re.findall(r"[0-9A-Za-z가-힣]+", str(text).lower())
    return {w for w in words if w not in _STOPWORDS}


def _overlap(a: set, b: set) -> float:
    """Jaccard overlap of two word sets; 0 when either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _is_not_applicable(value: Any) -> bool:
    """``"not-applicable"`` as a bare string or as the only list item."""
    if isinstance(value, str):
        return value.strip().lower() == "not-applicable"
    return (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], str)
        and value[0].strip().lower() == "not-applicable"
    )


def _is_number(value: Any) -> TypeGuard[Union[int, float]]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _gate_filled(gate: str, record: dict) -> bool:
    value = record.get(gate)
    if gate == "user":
        return isinstance(value, str) and bool(value.strip())
    if gate == "current_way":
        return isinstance(value, list) and len([s for s in value if isinstance(s, str) and s.strip()]) >= 2
    if gate in ("frequency_per_month", "minutes_per_run"):
        return _is_number(value) and value > 0
    if gate == "why_chain":
        if not isinstance(value, list) or len(value) < 4:
            return False
        if not all(isinstance(item, str) and item.strip() for item in value):
            return False
        accepted: List[set] = [_word_set(value[0])]
        distinct = 0
        for item in value[1:]:
            words = _word_set(item)
            if not words:
                continue
            # A link that mostly restates an earlier one is not a new "why".
            if any(_overlap(words, earlier) >= _RESTATEMENT_OVERLAP for earlier in accepted):
                continue
            accepted.append(words)
            distinct += 1
        return distinct >= 3
    if gate == "failed_attempts":
        if _is_not_applicable(value):
            return True
        if not isinstance(value, list) or not value:
            return False
        return all(
            isinstance(a, dict)
            and isinstance(a.get("tried"), str) and a["tried"].strip()
            and a.get("result") in _ATTEMPT_RESULTS
            for a in value
        )
    return False


#: ADR-0017 decision 2. `unknown` is deliberately absent from the blocking
#: set — see `_check_pains`'s comment on why blocking it would be a mistake.
PAIN_VERDICTS = ("build", "reuse", "eliminate", "unknown")

#: Verdicts that refuse promotion to /gatekit-interview (ADR-0017 decision 2,
#: mirroring ai-dev-pm's `blocksPromote()`).
_PAIN_VERDICTS_BLOCKING = ("eliminate", "reuse")

#: ADR-0017 decision 1: discovery must surface at least this many distinct
#: pains before narrowing to one, unless the user gave a stop signal (recorded
#: as `pain_floor_waived`). A stated count, not a measured one — see the ADR's
#: "Three, not grill-me's twenty" note.
PAIN_FLOOR = 3


def _check_pains(record: dict, lang: str) -> List[dict]:
    """ADR-0017 decisions 1 and 2: the `pains` array in the discovery fence.

    Additive to the pre-ADR-0017 fence shape: a record with no `pains` key at
    all is untouched by this function (early return), so every discovery
    record written before this ADR — and `test_spec_discovery.py`'s
    `full_record()` — stays valid with no new findings.
    """
    name = "00-discovery.md"
    if "pains" not in record:
        return []
    findings: List[dict] = []
    pains = record.get("pains")
    if not isinstance(pains, list):
        return [_finding(name, V.FAIL, _msg(lang, "pains_not_list"))]

    # Decision 1: the branch floor. `pain_floor_waived` is the discovery
    # command's record of a stop signal (policy/questioning.md) — the user
    # said stop, so fewer than the floor is honest, not a shortcut.
    waived = bool(record.get("pain_floor_waived"))
    if len(pains) < PAIN_FLOOR and not waived:
        findings.append(_finding(name, V.FAIL, _msg(lang, "pains_below_floor", floor=PAIN_FLOOR, count=len(pains))))

    chosen_pains = []
    for index, pain in enumerate(pains):
        if not isinstance(pain, dict):
            findings.append(_finding(name, V.FAIL, _msg(lang, "pain_not_object", index=index)))
            continue
        if pain.get("chosen"):
            chosen_pains.append((index, pain))

        suggested = pain.get("verdict_suggested")
        if suggested is not None:
            if not isinstance(suggested, dict) or suggested.get("verdict") not in PAIN_VERDICTS:
                findings.append(_finding(name, V.FAIL, _msg(lang, "pain_verdict_suggested_invalid", index=index)))
            elif not (isinstance(suggested.get("why"), str) and suggested["why"].strip()):
                findings.append(_finding(name, V.FAIL, _msg(lang, "pain_verdict_suggested_no_why", index=index)))

        confirmed = pain.get("verdict")
        if confirmed is not None and confirmed not in PAIN_VERDICTS:
            findings.append(_finding(name, V.FAIL, _msg(lang, "pain_verdict_invalid", index=index, value=confirmed)))

    # Exactly one chosen pain: none means Step 2's ranking never happened;
    # two or more means the ranking recorded a tie nobody broke.
    if len(chosen_pains) != 1:
        findings.append(_finding(name, V.FAIL, _msg(lang, "pains_chosen_count", count=len(chosen_pains))))
        return findings

    _, chosen = chosen_pains[0]
    confirmed = chosen.get("verdict")
    if confirmed in _PAIN_VERDICTS_BLOCKING:
        # ai-dev-pm's promote() gate, adapted: a pain that should be
        # eliminated or that duplicates an existing tool must not reach
        # /gatekit-interview. This mirrors VALIDATION_FAILED there — a
        # code-level refusal, not a prompt suggestion.
        findings.append(_finding(name, V.FAIL, _msg(lang, "pain_verdict_blocks", verdict=confirmed)))
    elif confirmed is None:
        # Proposed but not yet confirmed by the user — exactly the gap
        # gk-trial2's Assumption 4 fell into (the interviewer decided a
        # mapping and nobody confirmed it). This must be visible, but it is
        # not yet a known-bad verdict, so it warns rather than blocks.
        #
        # `unknown` is deliberately never in _PAIN_VERDICTS_BLOCKING either:
        # blocking "we don't know yet" would make refusing to decide the
        # strategy that avoids the gate, which is worse than letting an
        # honestly-uncertain pain through (ai-dev-pm's same reasoning).
        findings.append(_finding(name, V.WARN, _msg(lang, "pain_verdict_unconfirmed")))

    return findings


#: A floor, never a ceiling. grill-me counts "distinct decision branches
#: resolved" and refuses to close below 20-30; discover's own free-form
#: conversation (2026-09-20) borrows the same "a mechanical count, not a
#: self-reported feeling of being done" spirit, at a much smaller floor
#: because a discovery conversation and a grill-me decision branch are not
#: the same unit. There is deliberately no matching ceiling constant
#: anywhere in this file or in discover.md — the owner was explicit that a
#: cap on how far the conversation can go is exactly the mistake being
#: undone here.
_INSIGHT_FLOOR = 3


def _check_insight_count(record: dict, lang: str) -> List[dict]:
    """`insights_count` records how many distinct facts/branches the free-form
    discovery conversation actually surfaced, the same role grill-me's
    decision-branch count plays: a number a machine can check instead of the
    interviewer's own "I've asked enough" feeling. Optional field — a record
    that predates this (or a test fixture) is simply not checked."""
    name = "00-discovery.md"
    if "insights_count" not in record:
        return []
    count = record.get("insights_count")
    if not _is_number(count) or count < 0:
        return [_finding(name, V.FAIL, _msg(lang, "disc_insights_count_type"))]
    if count < _INSIGHT_FLOOR:
        return [_finding(name, V.WARN, _msg(lang, "disc_insights_count_low", count=count, floor=_INSIGHT_FLOOR))]
    return []


def _check_discovery(text: str, lang: str) -> List[dict]:
    name = "00-discovery.md"
    findings: List[dict] = []
    detailed = _parse_fences_detailed(text, "gatekit-discovery")
    for line_no, _, err in detailed:
        if err is not None:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "fence_malformed", line=line_no, name="gatekit-discovery", err=err))
            )
    records = [parsed for _, parsed, err in detailed if err is None]
    if len(records) != 1:
        if not findings:  # a malformed fence was already reported above
            findings.append(_finding(name, V.FAIL, _msg(lang, "disc_no_fence", count=len(records))))
        return findings
    record = records[0]

    # Free-form discovery (found 2026-09-20, after ADR-0017 decisions 7-11
    # ran against a real project): the six deepening gates used to be filled
    # against the record's own top level, one at a time, in a fixed order,
    # with progress shown to the user ("[gate 3-4] 2/6"). That fixed-slot
    # shape is exactly what the owner rejected as "허접함" next to grill-me
    # and ai-dev-pm — a scripted interrogation instead of a free-ranging
    # conversation that surfaces insight. The gates themselves (who, how
    # today, how often, why, what was tried) are still useful information —
    # only the fixed-slot, one-at-a-time, progress-counted *process* of
    # filling them is gone. So the gate fields now live inside whichever
    # pain the conversation actually deepened (a `chosen: true` entry in
    # `pains`, summarized post-hoc from a free conversation, not filled
    # slot-by-slot during it), not at the top level.
    #
    # A record with no `pains` key, or with `pains` but no gate fields on
    # any pain, is the pre-2026-09-20 shape: gates are still read from the
    # top level so every discovery file written before this change, and
    # `test_spec_discovery.py`'s own `full_record()`, keep validating
    # exactly as before.
    pains = record.get("pains")
    chosen_pain = None
    if isinstance(pains, list):
        for pain in pains:
            if isinstance(pain, dict) and pain.get("chosen"):
                chosen_pain = pain
                break

    gate_source = record
    unpassed_source = record
    if chosen_pain is not None and any(gate in chosen_pain for gate in DISCOVERY_GATES):
        gate_source = chosen_pain
        unpassed_source = chosen_pain

    problem = record.get("problem")
    if chosen_pain is None and not (isinstance(problem, str) and problem.strip()):
        # `problem` is the pre-pains, single-problem shape's required field.
        # Once pains exist, the chosen pain's own `summary` plays this role
        # (checked in `_check_pains`) — nothing new to require here.
        findings.append(_finding(name, V.FAIL, _msg(lang, "disc_no_problem")))

    deadline = record.get("deadline")
    if not (isinstance(deadline, str) and deadline.strip()):
        findings.append(_finding(name, V.WARN, _msg(lang, "disc_deadline")))

    unpassed = unpassed_source.get("unpassed")
    if unpassed is None:
        unpassed = []
    if not isinstance(unpassed, list):
        findings.append(_finding(name, V.FAIL, _msg(lang, "disc_unpassed_type")))
        unpassed = []
    for item in unpassed:
        if item not in DISCOVERY_GATES:
            findings.append(_finding(name, V.FAIL, _msg(lang, "disc_unknown_unpassed", name=item)))

    for gate in DISCOVERY_GATES:
        if _gate_filled(gate, gate_source):
            if gate in unpassed:
                findings.append(_finding(name, V.WARN, _msg(lang, "disc_unpassed_but_filled", gate=gate)))
            continue
        if gate in unpassed:
            findings.append(_finding(name, V.WARN, _msg(lang, "disc_gate_unpassed", gate=gate)))
        else:
            findings.append(
                _finding(name, V.WARN, _msg(lang, "disc_gate_unfilled", gate=gate, why=_msg(lang, "disc_" + gate)))
            )

    findings.extend(_check_pains(record, lang))
    findings.extend(_check_insight_count(record, lang))
    return findings


# --------------------------------------------------------------------------
# tokens.json (ADR-0008 decision 9)
# --------------------------------------------------------------------------

#: Keys every ``patterns`` row must carry.
_PATTERN_KEYS = ("id", "rule", "applies_to", "evidence")


def _check_tokens(root: pathlib.Path, lang: str) -> List[dict]:
    """Validate ``spec/tokens.json`` when it exists.

    Every finding is a ``warn``. The kernel does not depend on this file to
    run: a malformed one costs the worker its design section, not the build.
    Naming the offending key is the whole value of the check.
    """
    from gatekit import design as design_mod

    name = "tokens.json"
    path = design_mod.tokens_file(root)
    if not path.is_file():
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [_finding(name, V.WARN, _msg(lang, "tokens_unparsable", err=exc))]
    if not isinstance(raw, dict):
        return [
            _finding(
                name, V.WARN, _msg(lang, "tokens_unparsable", err="top level is not an object")
            )
        ]

    findings: List[dict] = []
    version = raw.get("version")
    is_v2 = version == 2

    source = raw.get("source")
    if is_v2:
        if source is not None and not isinstance(source, list):
            findings.append(_finding(name, V.WARN, _msg(lang, "tokens_source", expect="a list")))
    elif source is not None and not isinstance(source, (str, list)):
        findings.append(
            _finding(name, V.WARN, _msg(lang, "tokens_source", expect="a string or a list"))
        )

    patterns = raw.get("patterns")
    if patterns is not None:
        if not isinstance(patterns, list):
            findings.append(_finding(name, V.WARN, _msg(lang, "tokens_patterns")))
        else:
            for index, row in enumerate(patterns):
                if not isinstance(row, dict):
                    findings.append(
                        _finding(name, V.WARN, _msg(lang, "tokens_pattern_row", index=index))
                    )
                    continue
                for key in _PATTERN_KEYS:
                    value = row.get(key)
                    if key == "applies_to":
                        continue
                    if not isinstance(value, str) or not value.strip():
                        findings.append(
                            _finding(
                                name, V.WARN, _msg(lang, "tokens_pattern_key", index=index, field=key)
                            )
                        )
                applies_to = row.get("applies_to")
                ok_all = isinstance(applies_to, str) and applies_to.strip().lower() == "all"
                ok_list = isinstance(applies_to, list) and all(
                    isinstance(item, str) for item in applies_to
                )
                if not (ok_all or ok_list):
                    findings.append(
                        _finding(
                            name, V.WARN, _msg(lang, "tokens_pattern_applies_to", index=index)
                        )
                    )

    for group in raw:
        if group in design_mod.RESERVED_KEYS:
            continue
        tokens = raw[group]
        if not isinstance(tokens, dict):
            findings.append(_finding(name, V.WARN, _msg(lang, "tokens_group", group=group)))
            continue
        for token_name, value in tokens.items():
            if not isinstance(value, (str, dict)):
                findings.append(
                    _finding(name, V.WARN, _msg(lang, "tokens_value", group=group, name=token_name))
                )
    return findings


# --------------------------------------------------------------------------
# screen spec required for UI-bearing projects (ADR-0017 decision 3)
# --------------------------------------------------------------------------

#: A PRD carrying this marker in its Non-goals section is declaring itself
#: non-UI (a pure CLI or library) — /gatekit-interview writes it when the
#: project has no screens by design, not as something spec validate infers
#: from feature prose. Matched literally rather than by keyword-scanning
#: feature text: a prose heuristic over feature descriptions would be exactly
#: the kind of guess a code gate must not make (CLAUDE.md: prose is never the
#: enforcement mechanism).
_NON_UI_MARKER_RE = re.compile(r"\[non-ui\]", re.IGNORECASE)


def _prd_implies_ui(prd_text: str) -> bool:
    """True unless the PRD explicitly declares itself non-UI.

    Defaulting to True (UI-bearing) rather than scanning Features for
    screen-shaped keywords: most specs have a UI, and a keyword scan would
    both miss real UIs described in unexpected words and false-positive on
    unrelated prose. The explicit `[non-ui]` marker is the one signal that is
    exactly as reliable as the person who wrote it.
    """
    return not _NON_UI_MARKER_RE.search(prd_text or "")


def _check_screens_required(prd_text: Optional[str], screens_text: Optional[str], lang: str) -> List[dict]:
    """ADR-0017 decision 3: a UI-bearing PRD needs spec/02-screens.md before
    /gatekit-tasks proceeds — the same hard-stop shape 01-prd.md's own
    absence already gets, not the silent `missing_optional` warn every other
    optional file receives.

    Reported against 04-tasks.md (whether or not that file exists yet)
    because the *effect* of this gap is that /gatekit-tasks must not run —
    the same file `_check_tasks` and traceability findings already use for
    "something about proceeding to tasks is wrong."
    """
    if prd_text is None:
        # 01-prd.md's own absence is already a `missing_required` failure;
        # do not also report this and double-count the same root gap.
        return []
    if screens_text is not None:
        return []
    if not _prd_implies_ui(prd_text):
        return []
    return [_finding("04-tasks.md", V.FAIL, _msg(lang, "screens_required"))]


#: ADR-0017 decision 4: the confirmation line /gatekit-mockup's revision loop
#: writes once the user has actually opened, revised, and signed off on the
#: live prototype. Prose, not a hash-anchored approval like 05-gate.md's,
#: because the prototype is revised in-loop until confirmed — there is no
#: single moment to pin a hash to before the loop's last edit. A date is
#: required, not just the word "confirmed", so a stale copy-pasted line from
#: an unrelated project would still need someone to have typed today's date.
_PROTOTYPE_CONFIRMED_RE = re.compile(
    r"(?:프로토타입\s*확정|prototype\s+confirmed)\s+\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)


def _check_prototype_required(prd_text: Optional[str], screens_text: Optional[str], lang: str) -> List[dict]:
    """ADR-0017 decision 4: /gatekit-tasks must not run until the live HTML
    prototype has been opened, revised, and explicitly confirmed.

    Only meaningful once a screen spec exists at all — decision 3's
    `_check_screens_required` already reports the missing-screens gap on its
    own, and a non-UI project (declared via `[non-ui]`) needs no prototype in
    the first place.
    """
    if prd_text is None or screens_text is None:
        return []
    if not _prd_implies_ui(prd_text):
        return []
    if _PROTOTYPE_CONFIRMED_RE.search(screens_text):
        return []
    return [_finding("04-tasks.md", V.FAIL, _msg(lang, "prototype_required"))]


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def validate(root: pathlib.Path, lang: Optional[str] = None) -> dict:
    """Validate the spec set under `root/spec` and return a verdict report."""
    root = pathlib.Path(root)
    sdir = paths.spec_dir(root)
    contents: Dict[str, Optional[str]] = {}
    read_errors: Dict[str, str] = {}
    for name in spec_files():
        path = sdir / name
        if not path.exists():
            contents[name] = None
            continue
        try:
            contents[name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            contents[name] = None
            read_errors[name] = str(exc)

    if lang is None:
        prd = contents.get("01-prd.md")
        lang = lang_mod.detect(prd) if prd else "en"
    if lang not in heading_map():
        lang = "en"

    findings: List[dict] = []
    required = set(required_files())
    silent = set(absent_ok_files())
    for name in spec_files():
        if name in read_errors:
            findings.append(
                _finding(name, V.FAIL, _msg(lang, "unreadable", err=read_errors[name]))
            )
            continue
        if contents[name] is None:
            if name in silent:
                continue
            key = "missing_required" if name in required else "missing_optional"
            level = V.FAIL if name in required else V.WARN
            findings.append(_finding(name, level, _msg(lang, key)))

    for name in spec_files():
        text = contents.get(name)
        if text is None:
            continue
        findings.extend(_check_headings(name, text, lang))

    # ADR-0011 decision 4: the two files whose tables carry design evidence.
    for name in ("02-screens.md", "02-design.md"):
        text = contents.get(name)
        if text is not None:
            findings.extend(_check_preview_citations(name, text, lang))

    discovery = contents.get("00-discovery.md")
    if discovery is not None:
        findings.extend(_check_discovery(discovery, lang))

    findings.extend(_check_progress_freshness(root, lang))
    findings.extend(_check_tokens(root, lang))

    prd = contents.get("01-prd.md")
    if prd is not None:
        findings.extend(_check_ledger(prd, lang))

    screens_text = contents.get("02-screens.md")
    findings.extend(_check_screens_required(prd, screens_text, lang))
    findings.extend(_check_prototype_required(prd, screens_text, lang))

    tasks_text = contents.get("04-tasks.md")
    if tasks_text is not None:
        findings.extend(_check_tasks(tasks_text, lang))

    gate_text = contents.get("05-gate.md")
    if gate_text is not None:
        findings.extend(_check_criteria(gate_text, lang))

    if tasks_text is not None and gate_text is not None:
        findings.extend(_check_traceability(tasks_text, gate_text, lang))

    overall = V.aggregate([f["verdict"] for f in findings]) if findings else V.OK
    return {"verdict": overall, "findings": findings, "lang": lang}


def _render(report: dict) -> str:
    lang = report["lang"]
    lines = ["spec: " + V.render(report["verdict"], lang)]
    for finding in report["findings"]:
        lines.append(
            "  [{v}] {file}: {msg}".format(
                v=finding["verdict"], file=finding["file"], msg=finding["message"]
            )
        )
    if not report["findings"]:
        lines.append("  " + _msg(lang, "ok"))
    return "\n".join(lines)


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="gatekit spec", add_help=True)
    sub = parser.add_subparsers(dest="cmd")
    p_validate = sub.add_parser("validate", help="Validate the spec set.")
    p_validate.add_argument("--json", action="store_true", help="Emit JSON.")
    p_validate.add_argument("--root", default=None, help="Project root.")
    p_validate.add_argument("--lang", default=None, choices=["ko", "en"])
    args = parser.parse_args(argv)

    if args.cmd != "validate":
        parser.print_help()
        return 2

    # An explicit --root names the project root directly; only discover a root
    # by walking up when the caller did not say which one they meant.
    root = pathlib.Path(args.root).expanduser() if args.root else paths.project_root()
    report = validate(root, args.lang)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_render(report))
    return 1 if report["verdict"] == V.FAIL else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
