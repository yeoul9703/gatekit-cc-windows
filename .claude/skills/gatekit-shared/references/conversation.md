# Policy: the free-ranging interview conversation

This is the shared conversation contract for `/gatekit-discover` and
`/gatekit-interview`. Both run one continuous conversation in `output_lang`,
one question at a time, with no fixed slots and no question ceiling. Each
command file names the *subject* its conversation pursues; the rules for
*how* to conduct it live here, so the two cannot drift apart.

`.claude/skills/gatekit-shared/references/questioning.md` still applies in full: it holds the stop signals,
the rule against asking what is already knowable, and the question-window
budget, and this file does not repeat them. That budget is
`/gatekit-interview`'s alone and counts `AskUserQuestion` calls; "no question
ceiling" here is about the plain-chat questions of the conversation, which
are not calls and are not counted. This file is the only place
that says what a free-ranging conversation looks like in practice, written
after real trials found specific ways it goes wrong.

## Rules for every question

**Ask one question, then stop and wait for the actual reply.** Sending a
question ends your turn. Never invent or imagine what the user would say
and continue on your own to a second or third question in the same turn —
every next question is written only after a real reply arrives. Producing
a run of questions with no actual answer in between is the exact failure a
real trial hit and asked to have fixed: the conversation stops being an
interview the moment this happens.

**Every message the user sees is either a question or a plain statement in
`output_lang` — nothing else.** No narration of your own process ("Let me
record this," "I'll follow this thread," "This is an important answer"), no
meta-commentary on the answer just given, no thinking out loud between the
user's answer and your next question. This applies even when a language
other than `output_lang` would be the "natural" one to narrate in — there
is no narration to slip into in the first place. Read the answer, decide
the next question, ask it. Nothing goes in between.

**One question per message**, each with a **recommended answer** drawn from
what you have heard so far. People correct a wrong guess faster than they
fill a blank. When more than one plausible scenario exists, do not spell
them out as prose sentences ("아니면... 그런데... 아니면...") — that reads
as rambling, not a recommendation. List them as a short numbered set
instead (1/2/3/4, one short phrase each), still as plain chat text, never
`AskUserQuestion` — neither pipeline calls it during the conversation. A
single clear guess stays a single sentence; only branch into a numbered
list when there genuinely are multiple real possibilities worth
distinguishing. **Whenever you list numbered branches, always add one final
option for "none of these — tell me directly"** (e.g. "5. 다른 이유가
있다면 직접 말씀해주세요"), so the guessed scenarios never become the only
paths the user can answer with.

**Never precede the question with a sentence that previews it** ("~이
궁금합니다," "~을 여쭤보고 싶어요") and then ask the same thing again as the
actual question. That is the question stated twice — say it once. Go
straight from the last answer to the next question itself.

**Follow whatever thread is actually live.** If the last answer opened a
new angle — a person you had not asked about yet, a step that turned out to
be two steps, a reason something failed before — follow that thread before
returning to any other.

**A question only stops being worth asking when it stops producing anything
new**: the next likely answer already appeared, in substance, in the last
exchange or two (a reworded repeat is not a new answer), or a stop signal
arrives, which always wins immediately regardless of how little has been
asked.

**There is no maximum and no number to aim for.** Nothing caps how long the
conversation runs, how many plain-chat questions it asks, or how many
distinct facts it surfaces. Any count a
command records afterwards is a floor for catching a rushed conversation
after the fact, never a target to reach and stop at. If a topic keeps
yielding new, concrete, checkable facts, keep asking about it regardless of
how much has already been gathered.

## Getting concrete answers

**Past events only.** "Usually" is not an event; ask for the last date it
actually happened.

**A solution is not an answer.** When the user names a tool, feature, or
app, ask what they do today without it — every time, at most three times
per topic — then record it as their preferred solution and move on.

**An abstraction is not an answer.** "Manage," "automate," "dashboard": ask
for the last concrete occurrence, step by step.

**Unconfirmed answers** — the user's guess about someone else's situation —
get recorded as unconfirmed, naming who could confirm. `interview` turns
those into assumption rows.

## The checkpoint before summarizing

**When the conversation seems to have stopped producing anything new, say
so and ask directly before moving on — never decide this alone.** This is
not optional and not implied by the questions simply trailing off.

**Do not reuse a fixed sentence for this.** ("지금까지 나온 이야기를
정리해볼까 하는데..." is an example of the shape, not a script to paste —
writing it verbatim regardless of what the conversation actually covered is
exactly the scripted-feeling behavior this design exists to remove.)
Compose it from what actually happened in this conversation, and where you
can see a specific area the conversation has not touched yet (a screen it
implies but never described, a scenario it never asked about), name that
specific gap as part of the question rather than asking generically — e.g.
"캐릭터를 만드는 화면이 어땠으면 좋겠는지나, 이전 대화를 다시 찾아보는
일이 있을지는 아직 안 여쭤봤는데, 이것도 다뤄볼까요, 아니면 지금까지로
정리해도 될까요?"

**The reply must actually address this question before the command moves
on.** A reply that answers the *content* question asked earlier (a new
fact, a new requirement) but says nothing about whether to continue or wrap
up is not an answer to the checkpoint — even if it happens to contain a
phrase that sounds like permission ("정리해도 좋아" tacked onto an answer
about something else). If the reply is ambiguous about which question it is
answering, treat the checkpoint as still unanswered and ask it again,
explicitly, on its own. Only proceed once the user has given an answer that
is unambiguously about continuing or wrapping up — and once that answer
arrives, still stop there: the summary and its confirmation are their own
turn, never bundled into the same message as the checkpoint answer.

**On a stop signal**, skip the checkpoint entirely and summarize what is
already there — the user has answered it by stopping.

## Never name the machinery to the user

Never say "ADR-0017," "the branch floor," "insights_count," "Step 2.5," or
any other internal rule name to the user. Those are comments in the command
files, not vocabulary for the person being interviewed. If you need to
explain why you are asking again, say it in plain terms about the problem
itself ("한두 개만으로는 뭐가 진짜 문제인지 판단하기 어려워서요, 하나만 더
들어볼 수 있을까요?"), never by citing a rule number.
