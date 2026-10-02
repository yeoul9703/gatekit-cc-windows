---
title: "{{project_name}} — product requirements"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — product requirements

## Problem

{{Who is blocked, when, trying to do what. One paragraph. Describe the problem, not the solution.}}

## Current state (measured)

Write what is true today, in numbers. If you do not know, write "not measured"
and add a row to the assumption ledger.

| Metric | Current value | Source | Measured on |
|---|---|---|---|
| {{e.g. time to complete an order}} | {{value or not measured}} | {{logs / interview / estimate}} | {{date}} |

## Goals

- {{A verifiable outcome. Not "faster" but "3 min → under 60 s".}}
- {{Keep this to three or fewer.}}

## Non-goals

- {{Explicitly out of scope for this round. This is what stops scope creep later.}}
- {{For a project with no screens at all (a pure CLI or library): add a line here reading exactly "[non-ui] {{why}}" — this exempts the project from ADR-0017's screen-spec and prototype-confirmation gates.}}

## Users

| User | Situation | What they do today | What they need |
|---|---|---|---|
| {{role}} | {{when they reach for this}} | {{current workaround}} | {{unmet need}} |

## Features

Each feature carries an `F<n>` identifier. Tasks (04) and completion criteria
(05) reference these identifiers.

### F1 — {{feature name}}

{{What the user can now do. Describe behaviour, not implementation.}}

### F2 — {{feature name}}

{{…}}

## Acceptance criteria

Every item must be observable. "Works well" is not an acceptance criterion.

- **F1** — Given {{context}}, when {{action}}, then {{observable result}}.
- **F2** — {{…}}

## Assumption ledger

Record every unconfirmed judgement here. Wherever the body of this document
leans on an assumption, leave the blockquote marker below and keep its number
matching a row in this table.

> ⚠️ Assumption 1: {{what you assumed}}

| # | Assumption | Basis | Impact if wrong | How to confirm | Blocking | Confirmed |
|---|---|---|---|---|---|---|
| 1 | {{what you assumed}} | {{why you believed it}} | {{what breaks}} | {{who to ask, how}} | {{y \| n}} | {{y \| n}} |

Rule: inline markers and table rows correspond one-to-one by number. If only
one side exists, `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate` reports it. When an
assumption is confirmed, do not delete the row — replace the basis with the
confirmed fact, and flip `Confirmed` to `y`.

`Blocking` (ADR-0017) marks a row load-bearing enough that being wrong sinks
the plan — a wrong guess about who the real user is, not a wrong guess about
button color. A row marked `Blocking: y` with `Confirmed: n` makes
`spec validate` fail, not merely warn: `/gatekit-gate` refuses to proceed
while any such row stands. Mark a row `Blocking: n` when it is a reasonable
default that costs little to be wrong about.
