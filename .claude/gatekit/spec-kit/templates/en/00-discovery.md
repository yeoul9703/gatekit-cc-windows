---
title: "{{project_name}} — discovery record"
date: "{{date}}"
status: "{{in progress | conversation settled}}"
---

# {{project_name}} — discovery record

`/gatekit:discover` writes this file and `/gatekit:interview` reads it. The prose
is for people; the `gatekit-discovery` fence below is what the validator reads.
When they disagree, the fence wins.

This file is the post-hoc summary of a free-ranging conversation, not a
filled-in form — the conversation followed whatever thread was actually
live, not a fixed list of questions, and this page pulls out of it whatever
it actually established. What one opportunity below has plenty of detail on,
another may have little — that unevenness is honest, not a gap to force-fill.

## Pain list

Only events that actually happened in the last two weeks. "It's usually like
that" is not an event. Every opportunity the conversation surfaced, not only
the chosen one.

| # | Pain | Last happened | Frequency | Minutes per run | Waiting / blocked |
|---|---|---|---|---|---|
| 1 | {{one line}} | {{date}} | {{N per month}} | {{N min}} | {{none or detail}} |

## Chosen problem

{{One sentence with no solution in it. If it contains "tool", "system" or "feature", it is not a problem yet.}}

Candidates not chosen: {{numbered list or "none"}}

## Deadline

{{e.g. 4 weeks | none}} — with none, scope is cut by release order, never by time.

## Deepening gates

What the conversation established about the chosen opportunity — in
whatever order the conversation actually surfaced it, not a fixed sequence:
who has the pain, what they do today (step by step), how often and how
long, the causal chain behind it (not the first symptom named), and what
was already tried. Write it as prose reflecting what was actually said, not
a form filled in after the fact.

{{One paragraph or a few short paragraphs, in the conversation's own terms:
who, current way, frequency and time, the why-chain, what was tried and
why it did not work. Whatever the conversation did not cover, say so rather
than inventing it.}}

```gatekit-discovery
{
  "pains": [
    {"summary": "{{pain 1, one line}}", "chosen": true,
     "verdict_suggested": {"verdict": "build", "why": "{{one sentence}}"},
     "verdict": "build",
     "user": "{{name · role}}",
     "current_way": ["{{step 1}}", "{{step 2}}", "{{step 3}}"],
     "frequency_per_month": 0,
     "minutes_per_run": 0,
     "wait": "{{none | N days per case · what is blocked meanwhile}}",
     "why_chain": ["{{symptom}}", "{{why 1}}", "{{why 2}}", "{{why 3}}", "{{cause}}"],
     "failed_attempts": [
       {"tried": "{{what was tried}}", "result": "failed", "why": "{{why it did not work}}"}
     ],
     "notes": "{{anything real the conversation established that has no field above — success criteria the user stated, concrete requirements. Omit this key entirely when there is nothing left over.}}"},
    {"summary": "{{pain 2, one line}}", "chosen": false,
     "verdict_suggested": {"verdict": "reuse", "why": "{{one sentence}}"},
     "verdict": null},
    {"summary": "{{pain 3, one line}}", "chosen": false,
     "verdict_suggested": {"verdict": "unknown", "why": "{{one sentence}}"},
     "verdict": null}
  ],
  "insights_count": 0,
  "deadline": "{{4 weeks | none}}",
  "unpassed": []
}
```

`deadline` is `none` when there is none. On the chosen pain, `wait` is
`none` when there is none, and `failed_attempts` is the string
`"not-applicable"` when there was nothing to try. `unpassed` lists the gate
field names (`user`, `current_way`, `frequency_per_month`, `minutes_per_run`,
`why_chain`, `failed_attempts`) the conversation genuinely could not
establish for the chosen pain — not fields you chose not to ask about, only
ones that turned up nothing. The validator marks each as `warn`, and
interview carries it into the PRD as an assumption, not a fact.

`insights_count` is how many distinct facts and branches the conversation
actually surfaced (a why-link, a named failed attempt, a concrete step — not
a restatement), across every opportunity, counted honestly after the fact.
There is no target to hit and no ceiling — the validator only warns if it
looks implausibly thin.

`pains` needs at least three entries before one is chosen, unless the user
gave a stop signal — then add `"pain_floor_waived": true` at the top level.
Exactly one pain has `"chosen": true`; that pain's `verdict` (user-confirmed:
`build | reuse | eliminate | unknown`) must not be `eliminate` or `reuse`, or
`spec validate` refuses to let `/gatekit:interview` proceed. Every pain's
`verdict_suggested` is the interviewer's proposal — kept separate from the
user-confirmed `verdict` so the record can always show which is which.

## Open items

- [unconfirmed] {{answered, but not confirmed by the real user · who can confirm}}
- [user's preferred solution] {{a solution the user kept returning to. Kept for reference only}}

Write "none" here when there is neither. Do not leave the heading empty.
