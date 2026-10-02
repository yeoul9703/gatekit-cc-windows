# How to summarize a discovery conversation

Read by `/gatekit-discover` Step 3. This is the shape of the post-hoc
summary written into `spec/00-discovery.md` once the conversation ends.

## The move

Do not draft into the record turn by turn during the conversation. When it
ends, go back over the whole thing and pull **improvement opportunities**
out of it as a post-hoc summary — the same move a use-case extraction makes
over a raw interview transcript, not a slot filled live.

## Not every conversation is about a pain

Some are about building something that does not exist yet at all (a
character-chat feature, a tool nobody has today, not a workaround to an
annoyance). **Do not force a "problem the user suffers from" framing onto a
conversation that was actually about wanting to create something new.**
Write the summary in whatever terms the conversation actually used — if it
was about relieving an annoyance, summarize it as a pain; if it was about
wanting a capability that does not exist, summarize it as that, plainly,
without inventing a suffered problem to justify it. The `summary` field and
the `verdict_suggested` question still apply either way (something new can
still be `reuse` if an existing tool already does it), but the prose must
match what was actually discussed, not a template.

## Write a real summary, not a form filled to the field names

This summary is the raw material `/gatekit-interview` builds the PRD from.
Capture what was actually said, in enough concrete detail that someone
reading only this summary could start drafting a PRD from it, rather than
checking boxes to satisfy a schema.

For each opportunity, summarized from whatever the conversation actually
contains about it:

- **`summary`** — one line, with no solution baked into it: the problem or
  the desired new capability, in the conversation's own terms.
- **`notes`** — free text for anything real the conversation established
  that the named fields below have no slot for: success criteria the user
  stated ("계속 쓰고 있는지, 캐릭터가 지난 얘기를 기억하는지"), concrete
  requirements ("캐릭터를 여러 개 만들 수 있어야 한다"), anything the user
  confirmed that the schema does not anticipate. This is not a dumping
  ground for restating the other fields — it exists because a real
  conversation surfaces things a fixed schema cannot foresee, and those
  must not be silently dropped for lack of a named field. Leave it out
  entirely when there is genuinely nothing left over.
- **Whatever of these the conversation actually established**: `user` (real
  person + role), `current_way` (the steps in order, when an existing way
  exists — absent entirely for something that does not exist yet),
  `frequency_per_month` / `minutes_per_run`, `why_chain` (symptom plus
  distinct, non-reworded whys — or, for something new, the reasoning that
  came up for wanting it), `failed_attempts`. **Never invented to fill a
  gap**: what the conversation did not cover for a given opportunity is
  simply absent, not guessed at.
- **`verdict_suggested`** — your own proposal, one of `build` / `reuse` /
  `eliminate` / `unknown`, with one sentence of why. Weigh: does a real
  recipient already use what solving this would produce; does the input
  already exist somewhere instead of being retyped by hand; does an
  existing tool already do this; does it need human judgement this pipeline
  cannot automate away.

## `insights_count`

Count the distinct facts and branches the conversation actually surfaced
across every opportunity — a why-link, a named failed attempt, a concrete
step in a current-way replay, anything that added real information rather
than a restatement — and record that count.

There is no target to hit and no reason to inflate it. It is a record of
what happened. `spec validate` only warns when it looks implausibly thin;
it never fails on it and never caps it from above.
