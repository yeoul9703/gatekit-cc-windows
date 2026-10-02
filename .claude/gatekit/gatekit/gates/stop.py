"""Stop gate — the session does not end while the contract is unmet.

When a build or verify pipeline is active and ``.gatekit/contract.json`` exists,
this gate runs the completion contract (:mod:`gatekit.contract`) and blocks the
stop if any criterion is ``fail`` or ``unverified``, naming the offending ids.

The criteria it runs are the ones the user approved, or none. Before a
criterion runs, and before a recorded run is reused, the gate asks
:func:`gatekit.contract.refusal` two things: does the approval of
``spec/05-gate.md`` still hold, and are the criteria in ``contract.json`` the
ones that file states. If not, the stop is blocked without running anything:
criteria loosened after the sign-off, in the gate file or in ``contract.json``,
do not get to say the work is done. The way out is the one the message names:
fix the code, or go back to ``/gatekit-gate`` and have the criteria approved
again.

Three safety valves keep the block from becoming a trap:

* **``stop_hook_active``** — Claude Code sets this when it is already inside a
  stop-hook continuation. Blocking again would loop, so this gate always allows.
* **``block_count < 3``** — after three blocks the gate steps aside and lets the
  session end. A gate that can never be satisfied must not hold a user hostage.
* **Any internal error allows.** The wrapper in :mod:`gatekit.hookio` catches
  everything and exits 0.

The contract is not run again when its answer is already known: a run recorded
within the last ten minutes is reused while the contract file and every file
in the tree are unchanged (:func:`gatekit.contract.execute_reusing`, ADR-0024).
A turn that changed nothing, or a ``/gatekit-verify`` that has just run the
contract, costs a directory walk instead of the whole suite. The two questions
above are asked on every stop, reused run or not: they cost one hash and one
small parse.

Whenever the gate lets the session stop it records ``stop.final_verdict``, and
that value is **never blank**: an unrun contract is recorded as ``unverified``,
not silently as success.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import contract, hookio, ledger, paths, verdict  # noqa: E402

#: Pipelines whose completion is contract-enforced.
ENFORCED_PIPELINES = ("build", "verify")

#: How many times this gate may block one session before standing down.
MAX_BLOCKS = 3

#: The Stop hook's ``timeout`` in ``.claude/settings.json``. 600 s is the largest
#: value the Claude Code hook documentation shows; no higher value is
#: documented as supported, so gatekit does not rely on one.
STOP_HOOK_TIMEOUT_S = 600.0

#: The contract run inside this gate is capped below the hook timeout so the
#: interpreter start-up, the ledger write and the subprocess teardown fit. A
#: declared ``gatekit-budget`` above this runs in full under ``contract run``
#: but is cut here — and a cut run is ``unverified``, which is honest, where a
#: hook killed by Claude Code would record no verdict and no log line at all.
STOP_BUDGET_CAP_S = 570.0

_MESSAGES = {
    "en": {
        "blocked": (
            "gatekit: the completion contract is not met, so this work is not done "
            "({count} of {total} criteria failing or unverified):\n{reasons}\n"
            "If the code does not meet a criterion, fix the code and let the "
            "contract run again. If the criteria themselves have to change, go "
            "back to /gatekit-gate and have the user approve them again. "
            "'unverified' means it was never checked — that is not a pass."
        ),
        "stale": (
            "gatekit: .gatekit/contract.json no longer matches spec/05-gate.md, so "
            "completion cannot be judged (contract_stale). "
            "Run `" + paths.cli_invocation() + " contract derive`, then finish the work."
        ),
        "unapproved": (
            "gatekit: the approval of spec/05-gate.md does not hold, so completion "
            "cannot be judged (approval: {status}). 'fail' means the file changed "
            "after it was approved; 'unverified' means it was never approved. "
            "If the criteria were changed because the code does not meet them, "
            "put the approved criteria back and fix the code. If the criteria "
            "themselves have to change, go back to /gatekit-gate and have the "
            "user approve them again."
        ),
        "mismatch": (
            "gatekit: the criteria in .gatekit/contract.json are not the ones "
            "spec/05-gate.md states, so completion cannot be judged "
            "(contract_mismatch). contract.json is not edited by hand. "
            "Run `" + paths.cli_invocation() + " contract derive` to rebuild it; "
            "if the code then does not meet a criterion, fix the code. If the "
            "criteria themselves have to change, go back to /gatekit-gate and "
            "have the user approve them again."
        ),
    },
    "ko": {
        "blocked": (
            "gatekit: 완료 계약을 충족하지 못했으므로 아직 끝난 것이 아닙니다 "
            "(기준 {total}개 중 {count}개 실패 또는 미검증):\n{reasons}\n"
            "코드가 기준을 넘지 못한 것이면 코드를 고친 뒤 계약을 다시 실행하세요. "
            "기준 자체를 바꿔야 한다면 /gatekit-gate 로 돌아가 사용자에게 다시 "
            "승인받으세요. "
            "'unverified' 는 검증하지 않았다는 뜻이며 통과가 아닙니다."
        ),
        "stale": (
            "gatekit: .gatekit/contract.json 이 spec/05-gate.md 와 더 이상 일치하지 "
            "않아 완료 여부를 판정할 수 없습니다 (contract_stale). "
            "`" + paths.cli_invocation() + " contract derive` 를 실행한 뒤 작업을 마치세요."
        ),
        "unapproved": (
            "gatekit: spec/05-gate.md 의 승인이 유효하지 않아 완료 여부를 판정할 수 "
            "없습니다 (승인 상태: {status}). fail 은 승인 뒤에 파일이 바뀌었다는 "
            "뜻이고, unverified 는 승인한 적이 없다는 뜻입니다. "
            "코드가 기준을 넘지 못해 기준을 고쳤다면 승인받은 기준으로 되돌리고 "
            "코드를 고치세요. 기준 자체를 바꿔야 한다면 /gatekit-gate 로 돌아가 "
            "사용자에게 다시 승인받으세요."
        ),
        "mismatch": (
            "gatekit: .gatekit/contract.json 의 기준이 spec/05-gate.md 에 적힌 기준과 "
            "달라 완료 여부를 판정할 수 없습니다 (contract_mismatch). "
            "contract.json 은 손으로 고치는 파일이 아닙니다. "
            "`" + paths.cli_invocation() + " contract derive` 로 다시 만드세요. "
            "그 뒤에 코드가 기준을 넘지 못하면 코드를 고치세요. 기준 자체를 바꿔야 "
            "한다면 /gatekit-gate 로 돌아가 사용자에게 다시 승인받으세요."
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


def _finish(led: "ledger.Ledger", final: str, reasons: Optional[List[str]] = None) -> None:
    """Record the outcome and allow the stop. ``final`` is never blank."""
    stop_state = led.data.setdefault(
        "stop", {"block_count": 0, "final_verdict": None, "last_reasons": []}
    )
    stop_state["final_verdict"] = final or verdict.UNVERIFIED
    if reasons is not None:
        stop_state["last_reasons"] = reasons
    led.append_event("stop_allowed", {"final_verdict": stop_state["final_verdict"]})
    led.save()


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the contract when a build/verify pipeline is active and judge it."""
    root = hookio.event_root(event)
    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without creating state there.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    led = ledger.Ledger.load(root, hookio.session_id(event))
    lang = led.output_lang

    pipeline = led.data.get("active_pipeline")
    contract_present = paths.contract_file(root).is_file()

    # Nothing to enforce: allow, but still record a non-blank verdict.
    if pipeline not in ENFORCED_PIPELINES or not contract_present:
        _finish(led, verdict.UNVERIFIED)
        return hookio.allow()

    # Only approved criteria are run or reused. When the approval does not
    # hold, or contract.json states other criteria than the gate file, there
    # is nothing honest to run: the answer is `unverified` and it takes the
    # same road below as a run that failed.
    result = contract.refusal(root)
    if result is None:
        result = contract.execute_reusing(root, cap_s=STOP_BUDGET_CAP_S)
    outcome = result["verdict"]
    reasons = result["reasons"]

    # Already inside a stop-hook continuation: never block again.
    if bool(event.get("stop_hook_active")):
        _finish(led, outcome, reasons)
        return hookio.allow()

    stop_state = led.data.setdefault(
        "stop", {"block_count": 0, "final_verdict": None, "last_reasons": []}
    )
    try:
        block_count = int(stop_state.get("block_count", 0))
    except (TypeError, ValueError):
        block_count = 0

    if outcome == verdict.OK:
        _finish(led, outcome, reasons)
        return hookio.allow()

    # Out of blocks: stand down rather than trap the session, but say plainly
    # that the work did not pass.
    if block_count >= MAX_BLOCKS:
        _finish(led, outcome, reasons)
        return hookio.allow()

    stop_state["block_count"] = block_count + 1
    stop_state["last_reasons"] = reasons
    led.append_event(
        "stop_blocked",
        {"verdict": outcome, "block_count": stop_state["block_count"]},
    )
    led.save()

    if contract.UNAPPROVED_REASON in reasons:
        return hookio.block_stop(
            _message(lang, "unapproved", status=result.get("approval") or verdict.UNVERIFIED)
        )
    if contract.MISMATCH_REASON in reasons:
        return hookio.block_stop(_message(lang, "mismatch"))
    if contract.STALE_REASON in reasons:
        return hookio.block_stop(_message(lang, "stale"))

    unmet = [
        item
        for item in result["criteria"]
        if item.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)
    ]
    reasons_text = "\n".join(f"  - {line}" for line in reasons) or "  - (no detail)"
    return hookio.block_stop(
        _message(
            lang,
            "blocked",
            count=len(unmet) or len(reasons),
            total=len(result["criteria"]) or len(reasons),
            reasons=reasons_text,
        )
    )


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
