# Policy: questioning

This file says when and how often the question window (`AskUserQuestion`)
is used, and what counts as a stop signal. How a free-ranging interview
conversation is conducted — one question per message, nothing but the
question, no narration — is in
`.claude/skills/gatekit-shared/references/conversation.md`, and only there.

## Asking ends your turn

Asking a question ends your turn, in the question window or in plain chat.
Send exactly one question, then stop — do not imagine or invent the user's
answer and continue on your own. This applies with no exception: not when
the likely answer seems obvious, not when several questions feel related
enough to ask together, not when the conversation is "almost done."

## Draft first

Write the draft before asking anything beyond the opening probe. A draft with
labelled assumptions is easier to correct than an empty form is to fill. People
react well to a concrete wrong answer and badly to an interrogation.

Order: one open probe → draft → at most two `AskUserQuestion` calls → confirm.

## The one open probe

Ask exactly one open question, and make it about **past behaviour**, not
preference. Past behaviour is observable; preference is invented on the spot.

| Ask this | Not this |
|---|---|
| "Last time you had to do this, what did you actually do?" | "What features would you like?" |
| "What did you try before deciding it was a problem?" | "How important is speed to you?" |
| "Who else touched this, and what did they change?" | "Would you prefer A or B?" |

## Research the facts; ask only the decisions

Before asking anything, find out what is already knowable. Read the repository,
the existing files, the mockup, the config. A question whose answer is in the
codebase spends the user's attention on something you could have looked up.

Ask only about things the user alone can decide: priorities, trade-offs they
own, external constraints, and what "done" means to them.

## AskUserQuestion budget

- **2** calls per interview are free. The question gate counts them.
- At most **4** options per question.
- Each option needs a label and a description in the detected output language.
- Never list `AskUserQuestion` in a command's `allowed-tools`. Doing so
  auto-approves it and the picker never renders for the user.

Past the two free calls, before each call, write one line into
`ledger.questions.justification` saying **what you would write differently
depending on the answer**. If you cannot write that line, the question is not
worth asking — draft the assumption instead. The line is single-use: it is
consumed by the call it justifies.

**The line is the test, not the number.** A question inside the budget that
fails it is still waste; a question outside it that passes is still worth
asking. The gate records what the count cannot see (ADR-0012):

| Signal | What it means |
|---|---|
| `unjustified` | an over-budget call with no line — nobody could say its purpose |
| `repeated` / `repeat_of` | this question fingerprints onto an earlier one |
| `unrealized` | a justified call after which nothing was written |
| `implementation_choice` | every option read as code — see the guard below |

None of them blocks. They are the trace that tells an over-budget interview
that kept earning its questions apart from one that just kept asking.

## Assumption ledger

Every answer you did not get becomes a ledger row in `spec/01-prd.md`, and
every place in the document that leans on it gets the inline marker:

```
> ⚠️ Assumption 3: the team deploys manually, so no CI step is specified.
```

The inline number and the table row number must match. `spec validate` fails on
a mismatch, in either direction.

## Stop signals

Stop questioning immediately and move to the draft when the user says any of
these. There are two shapes, and both count — do not wait for the delegating
shape when the question already asked "is there more?" and the answer is no:

**Delegating** — the user hands you the judgement:
- "알아서 해줘", "너가 정해", "그냥 해줘", "빨리"
- "you decide", "your call", "just do it", "whatever you think", "skip the questions"

**Exhausted** — the user answers the specific question with "there is no
more," which is not the same speech act as "I don't know" or silence:
- "없어", "딱히 없어", "그게 다야", "더 없어", "이제 없어"
- "no", "none", "that's it", "nothing else", "no more", "that's all"

A direct "no" to "anything else?" is exhausted, not merely an unhelpful
answer to keep probing past — a per-topic budget (like the three-question
cap on a solution-named answer) exists for when the user has *not* said
stop; once they have, the budget is moot. Do not read a plain negative
answer as evasion, and do not counter it with "just one more angle" or a
second phrasing of the same question — that turns a stop signal into an
interrogation, exactly what this policy exists to prevent.

After a stop signal: no more `AskUserQuestion` calls in this pipeline (or, in
a pipeline that never uses `AskUserQuestion`, no more plain-chat questions
either). Fill every remaining unknown with a documented assumption — or, for
a command with its own explicit floor-waiver field (e.g. `/gatekit-discover`'s
`pain_floor_waived`), record that field — deliver the draft, and list the
assumptions at the end so the user can correct any of them in one pass.

## Over-questioning guard

You are over-questioning if any of these is true. Stop and draft.

- The answer is discoverable in the repo, the mockup, or an earlier message.
- You have already asked about this topic in this session.
- The question is a preference the user has no strong stake in.
- Either possible answer leads you to write the same thing.
- You have asked two `AskUserQuestion` calls and cannot justify a third.
- **The question asks the user to arbitrate a choice you are better placed to
  make.** Decide, act, and show them the result to correct. "Which of these
  three implementations?" spends their attention on your judgement. The
  giveaway is that every option is a mechanism — a file, a function, a command
  — rather than an outcome they care about.
