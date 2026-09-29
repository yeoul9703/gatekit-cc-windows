---
title: "{{project_name}} — progress"
date: "{{date}}"
status: "{{not-started | in-progress | blocked | done}}"
---

# {{project_name}} — progress

Read by both humans and machines. Do not change the format of the body's
`STATUS:` line below — the frontmatter's `status` is a summary for someone
who has not opened the file; the body's `STATUS:` line remains the source
of truth.

STATUS: {{not-started | in-progress | blocked | done}} · {{iso timestamp}}

## Status

One paragraph on what works and what does not right now. Observations, not
plans.

| Item | Value |
|---|---|
| Active pipeline | {{interview / mockup / tasks / gate / build / verify}} |
| Criteria passing | {{n}} / {{total}} |
| Last verdict | {{ok / warn / fail / unverified}} |
| Open assumptions | {{n}} |

## Milestones

| Milestone | State | Timestamp | Evidence |
|---|---|---|---|
| Spec approved | {{done/not done}} | {{iso}} | `gatekit approve check spec/05-gate.md` |
| {{task-one}} | {{}} | {{iso}} | {{gate name and exit code}} |

Use ISO 8601 timestamps, never relative wording like "yesterday" or "just now".

## Failed attempts

Record what was tried and why it failed. If retries happened and this table is
empty, the record is incomplete.

| # | Attempt | Result | Cause | Do not repeat |
|---|---|---|---|---|
| 1 | {{what was tried}} | {{fail / unverified}} | {{observed cause}} | {{the approach not to try again}} |

## Last verification

| Item | Value |
|---|---|
| Command | `python3 -m gatekit contract run --json` |
| Run at | {{iso}} |
| Verdict | {{ok / warn / fail / unverified}} |
| Failing or unverified criteria | {{list of ids, or "none"}} |
| Evidence location | {{.gatekit/runs/ or artifact paths}} |

`unverified` is not a failure, but it is not a pass either. Say exactly what
could not be checked and do not round it toward passing.
