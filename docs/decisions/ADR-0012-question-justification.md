# ADR-0012: A question past the budget must name what it changes

Status: proposed 2026-09-17.

Origin: this session. The question gate has been reporting `questions=6/2` in
every prompt injection for hours — six asked against a budget of two — and
nothing happened. Two of those six were genuinely wasteful and the user
rejected them outright; the other four each changed the work that followed.
Counting could not tell the difference.

## Context

`policy/questioning.md` is already a good policy. It says to research before
asking, to ask about past behaviour rather than preference, to stop on a stop
signal, and it lists four over-questioning conditions:

- the answer is discoverable in the repo, the mockup, or an earlier message
- you have already asked about this topic in this session
- the question is a preference the user has no strong stake in
- **either possible answer leads you to write the same thing**
- you have asked two `AskUserQuestion` calls already

Only the last of those five is enforced. `gates/question.py` increments
`ledger.questions.asked` and sets `budget_exceeded` when `asked > max_calls`.
The other four are prose, and this repo's own rule says prose in a command or
policy file is never an enforcement mechanism.

The result is a gate that measures the one thing that correlates worst with
waste. In this session:

| # | Question | Changed the work? |
|---|---|---|
| 1 | preview scope: elapsed/watch/activity | yes — picked the scope |
| 2 | commit timing | yes — one commit vs. staged |
| 3 | how to inject approved screens | **no — rejected, handed judgement back** |
| 4 | which direction first, in/out | **no — rejected, handed judgement back** |
| 5 | build visibility scope | yes — picked the scope |
| 6 | commit timing | yes |

The two the user rejected were rejected for the same reason, and the user
named it later by quoting a reference harness: *결정 위임 금지 — 판단 자체를
사용자에게 넘기지 않는다.* Both asked the user to arbitrate an implementation
choice I was better placed to make. Neither exceeded any count; questions 1
and 2 had already spent the budget before either was asked.

Meanwhile a hard ceiling of two would have stopped the session after question
2 — before the screen-injection design, the reference-harness reading, and the
scope correction that produced ADR-0011 at all. The budget was blown from the
third call onward and every subsequent call was worth making.

So the count is wrong in both directions: it permits waste inside the budget
and forbids value outside it.

The standing constraints apply: hooks and code are the enforcement, not prose;
every hook exits 0 on internal error; `unverified` never rounds; stdlib only;
PostToolUse has no block channel, so this gate informs, it does not block.

## Decision

Keep the count. Stop treating it as the verdict. Three of the policy's five
guard conditions turn out to be machine-checkable once the gate looks at the
question text and at what happened after it — the first draft of this ADR gave
up on all of them too early.

### 1. Past the budget, a question must record what it would change

`AskUserQuestion` calls up to `max_calls` are unchanged: asked freely, counted,
nothing required. From `max_calls + 1` onward the asking command must have
written a one-line justification into the ledger **before** the call, naming
what it would write differently depending on the answer.

`ledger.questions` gains two fields:

```json
"questions": {
  "asked": 6, "max_calls": 2, "budget_exceeded": true,
  "justification": "screens block: inject spec text vs. gate the result",
  "unjustified": 2
}
```

The gate's behaviour at `asked > max_calls`:

| Ledger state when the call lands | Gate records |
|---|---|
| `justification` is a non-empty string | consume it (set to `null`), leave `unjustified` alone |
| `justification` is absent or empty | `unjustified += 1` |

`justification` is single-use: consumed by the call it justifies, so a command
cannot write one and then ask five questions behind it.

`budget_exceeded` stays exactly as it is, for the existing consumers. The new
signal is `unjustified`, and it is the one that means something: **an over-budget
question nobody could say the purpose of.**

### 2. A repeated topic is detected, not merely forbidden

The guard's *"you have already asked about this topic in this session"* is
prose today because nobody looked at the question text. The PostToolUse event
carries `tool_input`, so the gate can.

Each call records a normalised fingerprint of every question it asked — the
`header` and `question` string lowercased, stripped of punctuation, reduced to
a sorted set of content words. A later call whose fingerprint overlaps an
earlier one past a fixed threshold records `repeat_of` naming the earlier
call's index, and increments `repeated`.

This session would have caught it: question 2 and question 6 were both about
when to commit.

The threshold is deliberately high (most content words shared). A near miss is
silence, not a warning — the cost of a false "you already asked this" is that
a command stops asking something it should ask, which is worse than the
duplicate.

### 3. A justification that never came true is recorded

This is the one the first draft called impossible, and it is only impossible
at the moment of asking. A justification claims *the answer changes what I
write*. Whether anything was written afterwards is an observable fact.

The ledger already sees every tool call. When a justified over-budget question
is answered and **no `Write` or `Edit` lands before the next
`AskUserQuestion` or the end of the session**, the gate records
`unrealized += 1` against that question.

That catches the commonest shape of an empty justification — asked, answered,
nothing changed — without needing to understand the work. A command can still
write a vague line and then touch a file to satisfy it, but it can no longer
ask a question that changes nothing and leave no trace.

Deliberately coarse: any write counts, not a write to a file the justification
named. Naming the file up front would be more precise and would misfire every
time the real consequence landed somewhere unforeseen, which is most of the
time.

### 4. A question whose options are all implementation gets a warning

The failure this session produced twice — handing the user a choice the
command was better placed to make — is not fully machine-checkable. But it has
a signature. Both rejected questions offered options that were entirely
implementation mechanics:

> "inject into the prompt / attach the HTML too / check with a gate"
> "the inbound side first / the outbound side first / both"

while every accepted question asked what to prioritise. When every option label
and description in a call is dominated by code tokens — file paths, function
names, command names, `snake_case` or `camelCase` identifiers — the gate
records `implementation_choice` for that call.

This is a `warn`-grade signal and never `fail`: a legitimate question can be
about implementation when the user genuinely owns the trade-off, and the gate
cannot tell the difference. It is recorded so the pattern is visible in the run
record, not to stop the call.

### 5. The prompt injection reports both numbers

The `prompt` hook's `additionalContext` today carries `questions=6/2`. It gains
the counts that mean something, when any is non-zero:
`questions=6/2 (2 unjustified, 1 repeat)`. A command reading its own context
sees the distinction the count alone hides. The field stays inside the 600-char
`additionalContext` budget by printing only non-zero counts.

### 6. `policy/questioning.md` states the rule the gate now measures

The budget section is rewritten from a ceiling into a threshold:

> Two calls are free. Past that, before each call, write one line into the
> ledger saying what you would write differently depending on the answer. If
> you cannot write that line, the question is not worth asking — draft the
> assumption instead.
>
> The line is the test, not the number. A question inside the budget that
> fails it is still waste; a question outside the budget that passes it is
> still worth asking.

And the over-questioning guard gains the failure this session actually
produced, which none of its five conditions names:

> - The question asks the user to arbitrate a choice you are better placed to
>   make. Decide, act, and show them the result to correct. Asking "which of
>   these three implementations?" spends their attention on your judgement.

Decision 4 gives that condition a machine-visible signature, but the rule
itself stays prose: the signature is a warning, not a verdict, because a
question about implementation is sometimes exactly right.

### 7. `spec validate` is not involved

Deliberately. Whether a question was worth asking is not a property of the
delivered spec, and adding it to `spec validate` would make an interview's
process a condition of its output passing. The ledger records; the operator
and the command read.

## Consequences

**What changes in practice.** A command that keeps asking must keep saying
why, in one line, each time. The cost of a seventh question is one sentence.
The cost of a seventh *pointless* question is a permanent `unjustified` count
in the run record, which is exactly the trace missing today.

**What does not change.** Nothing blocks. PostToolUse cannot block, and making
the interview refuse to ask would be worse than the disease: the four useful
questions in this session all came after the budget.

**What is actually enforced, and what is not.** The first draft of this ADR
conceded the whole thing to "the gate cannot judge the line's content." That
was too quick. Three of the five guard conditions are checkable:

| Guard condition | Enforcement |
|---|---|
| already asked this topic | **checked** — question-text fingerprint (decision 2) |
| either answer writes the same thing | **checked after the fact** — `unrealized` when no write follows (decision 3) |
| asks the user to arbitrate your choice | **warned** — options that are all code tokens (decision 4) |
| answer is discoverable in the repo | not checkable — would require knowing what the repo says about this question |
| a preference the user has no stake in | not checkable — the stake is in the user's head |

The residue is real but smaller than it looked. Two conditions stay prose, and
the honest reason is the same for both: they are claims about knowledge the
gate does not have — what the repository would have answered, and what the user
cares about.

Within what *is* checked, one weakness remains by design: a command can write a
vague justification and then touch any file to satisfy `unrealized`. That is a
deliberate trade. Requiring the justification to name the file it would change
would catch the dodge and would misfire whenever the real consequence landed
somewhere unforeseen — which is most of the time, and is how the useful
questions in this session played out. A check that fires on honest work is
worse than one that a determined command can step around, because the first
gets disabled and the second only gets gamed.

**Contract changes** (`docs/ARCHITECTURE.md`): §3's `question` bullet gains
justification consumption, `unjustified`, the topic fingerprint and
`repeated`, the `implementation_choice` warning, and the `unrealized` deferral;
§3's `prompt` bullet gains the non-zero counts in `additionalContext`; §4's
ledger schema gains the new `questions` fields and the per-call `asked_topics`
list. §13 lists the new tests: a justified over-budget call consumes the line
and does not raise `unjustified`; an unjustified one increments it; the line is
single-use across two calls; calls within budget need none; a malformed or
non-string justification counts as absent; a repeated topic is fingerprinted
and a merely-similar one is not; an all-implementation option set warns and a
priority question does not; `unrealized` fires when no write follows and not
when one does; `budget_exceeded` keeps its current meaning; exit 0 on internal
error for every new path.

## Rejected alternatives

- **Raise the budget to four or six.** Moves the wrong line rather than
  replacing it. Nothing about the fourth question is different in kind from
  the third.
- **Remove the budget entirely.** The count is the only cheap brake there is,
  and an interview with no brake is the failure the policy was written for.
  Two free calls also keep the common case silent.
- **Block the call.** PostToolUse has no block channel; a PreToolUse gate that
  refused a question would make an un-asked question indistinguishable from an
  unanswered one, and would have stopped this session at question 3.
- **Have the gate judge the justification's quality.** It would have to
  understand the work. A counter can check presence; that is all.
- **Count only questions the user actually answered.** Rejected questions are
  the signal, not the noise: both of this session's wasteful questions were
  rejected, and discounting them would have made the record look clean.
- **Put the rule in `spec validate`.** See decision 4.

## Open questions

- Whether `unjustified` should also appear in `/gatekit:verify`'s report as a
  process note. It is not a verdict on the product, so it is left out for now.
- Whether the discover pipeline should be budgeted too. It asks in plain chat
  rather than through `AskUserQuestion`, so the gate never sees its questions;
  that asymmetry predates this ADR.
