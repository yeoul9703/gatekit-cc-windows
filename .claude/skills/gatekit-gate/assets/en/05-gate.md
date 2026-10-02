---
title: "{{project_name}} — completion gate"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — completion gate

This file is the definition of "done". Once a human approves it, its hash is
pinned and the Stop hook actually runs the commands below to decide. A spoken
claim of completion is not evidence.

## Completion criteria

Each criterion is one `gatekit-criterion` block. `argv` runs without a shell,
with `cwd` set to the project root. Reference the matching task id in the
criterion `id` to keep traceability.

```gatekit-criterion
{"id": "tests-pass",
 "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0},
 "timeout_s": 30}
```

```gatekit-criterion
{"id": "task-one-works",
 "argv": ["{{a runnable verification command}}"],
 "expect": {"exit": 0},
 "timeout_s": 30,
 "artifacts": ["{{reports/task-one.txt}}"]}
```

Field rules:

| Field | Rule |
|---|---|
| `id` | Unique. Referencing a task id from 04 clears the traceability warning. |
| `argv` | Non-empty list of strings. No shell syntax (`&&`, pipes). |
| `expect.exit` | The exit code that counts as passing. Usually 0. |
| `timeout_s` | Per-criterion ceiling. The run-wide budget defaults to 45 s and can be raised to at most 600 s with the `gatekit-budget` fence below. |
| `artifacts` | Relative paths that must exist afterwards. Missing → `fail`. |

## Not counted as done

Any of the following means the work is not done. Each one yields `fail` or
`unverified`.

- Tests made to pass by skipping or disabling them (`skip`, `only`)
- A criterion command that timed out — that is `unverified`, never rounded up
  to a pass
- A command exiting 0 while its declared artifact file is absent
- TODOs, stubs, or empty function bodies left in place of implementation
- Editing `05-gate.md` to delete a failing criterion — the approval hash breaks
  and the run reports `contract_stale`
- Reporting "it works" without having run it

## How evidence is collected

| Criterion | How it runs | Evidence left behind |
|---|---|---|
| tests-pass | `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract run` | exit code, stdout tail |
| {{task-one-works}} | {{}} | {{sha256 of the artifact file}} |

Approval: once a human has read and agreed to this document, run
`uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve spec/05-gate.md`. Editing the document afterwards
expires the approval and it must be granted again.

## Run budget (optional)

Declare a budget when the criteria together take longer than 45 s. Without it
the run is cut off at 45 s, so a slow-but-passing suite would stay `unverified`
forever.

```gatekit-budget
{"total_budget_s": 180}
```

The ceiling is 600 s. A check that takes longer belongs in a build step, not in
the stop gate.
