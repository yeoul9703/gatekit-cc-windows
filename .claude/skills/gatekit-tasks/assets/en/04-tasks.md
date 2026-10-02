---
title: "{{project_name}} — task list"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — task list

Each task is one `gatekit-task` block. `jobs.py` reads these blocks and hands
them to a worker; the write gate enforces `write_scope` inside that worker.

## Task list

Cut tasks as vertical slices. A task should exercise screen, logic and data
together. Do not create horizontal layers like "build the models only".

```gatekit-task
{"id": "task-one",
 "title": "{{one-line title}}",
 "write_scope": ["{{src/feature-a/**}}"],
 "instruction": "{{Self-contained brief. What to build, which files to write, and what counts as done — readable without any other document.}}",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": [],
 "round": 1}
```

```gatekit-task
{"id": "task-two",
 "title": "{{one-line title}}",
 "write_scope": ["{{src/feature-b/**}}"],
 "instruction": "{{…}}",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": ["task-one"],
 "round": 2}
```

Field rules:

| Field | Rule |
|---|---|
| `id` | Unique across the file. Completion criteria (05) reference it. |
| `write_scope` | Non-empty list of globs, or the string `"read-only"` for investigation tasks. |
| `instruction` | Self-contained; executable without reading other documents. |
| `gates` | At least one. An argv list, run without a shell. Exit 0 is `ok`, exit 3 is `unverified` (it ran but could not judge), any other non-zero is `fail`. |
| `depends_on` | Only ids that exist in this file. |
| `round` | Tasks in the same round run in parallel. |

## Execution order

| Round | Tasks | Why they can run together |
|---|---|---|
| 1 | task-one | {{no file overlap with other tasks}} |
| 2 | task-two | {{depends on task-one's output}} |

## Scope rules

- Two tasks in the same round must not have intersecting `write_scope`.
  `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` fails when they do.
- A worker cannot write outside its own `write_scope`. The write gate blocks it.
- If a task needs a wider scope, split the task instead of widening it silently.
