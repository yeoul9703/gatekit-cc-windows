# Researching the product category, then proposing what the conversation missed

Read by `/gatekit-interview` Step 2.5, after the free conversation settles
and before the draft is written.

## Why this step exists

**A free-ranging conversation only ever produces what the user thought to
say.** For a known product category, some features are expected by anyone
familiar with it but are infrastructure to the user's actual goal rather
than the goal itself — so they rarely come up unprompted.

Found on `gk-todo4`: a character-chat interview covered memory, intimacy,
and persona in real depth, but never touched context-window management for
long conversations, content-safety limits, or persona drift over a long
session — all standard concerns for that category, none raised because the
user was thinking about the relationship feature, not the category's usual
pitfalls. The owner's framing after reading that PRD: "기본적으로 챗봇
기능으로 들어가야 할 내용들이 빠져있고, 완성도가 상당히 낮아."

The fix is not one or two more questions. It is a shift from "only what the
user thought to say" toward a propose-then-prune shape: surface a fuller
feature set drawn from real knowledge of the category, and let the user cut
or adjust rather than build from a blank slate.

## a. Freeze what the conversation already established

Before doing anything else, list every feature the conversation actually
produced as a **locked set**. This is the differentiator ledger — the
reason this specific product exists, in the user's own terms (for a
character-chat product: intimacy scoring, memory accumulation, persona).

**Nothing in the steps below may alter, replace, or "improve" an item in
this set.** Research only ever fills gaps beside it, never edits it. This
is the single guard against research smoothing a product toward a category
average and diluting the reason it is being built.

## b. Research the category

Identify the product category from the frozen set and the discovery record.
Run `WebSearch` with **four distinct angles**, not one generic query:

1. **Standard/essential features** for this category — what a spec sheet or
   comparison article says every product in it has.
2. **User complaints and reviews** naming what such products commonly get
   wrong or lack. This is the closest available proxy to what actually made
   `gk-todo4`'s reference product get deleted — a real failure mode, not a
   feature-list guess.
3. **Recent/leading examples** and what differentiates them (trend pieces,
   "best of" roundups) — kept and labeled separately, never blended into
   "standard."
4. **Technical pitfalls or postmortems** specific to the category
   (engineering blog posts, "what we got wrong building X").

**Cross-check before accepting anything as a candidate: an item only
becomes a "standard" candidate when two or more independent sources
corroborate it.** A single blog's opinion is not evidence of a category
norm. An item from only one source, or from angle 3 alone, is never
labeled standard — carry it as a separately-labeled reference idea,
explicitly marked as not typical.

## c. Diff against the frozen set, then present

Drop every research candidate that already overlaps (even loosely) with an
item in the frozen set — research fills gaps beside the differentiator
ledger, never second-guesses or restates it.

Present what remains to the user as plain statements, in `output_lang`, in
two clearly separated groups:

- **기본기 후보 (hygiene candidates)** — cross-checked as standard for this
  category, each showing which research angle it came from, so a "2건
  이상의 실제 서비스/리뷰에서 반복적으로 언급됨" style citation is visible
  rather than merely asserted.
- **참고 아이디어 (reference ideas)** — single-source or trend-only, marked
  as optional inspiration, never framed as something expected.

If `spec/00-discovery.md` contains an experience that confirms or
contradicts a candidate (the user's own account of what a prior tool got
wrong), say so alongside it — **that is the strongest available evidence
and outranks the research.**

## d. Prune, not fill in a blank

Ask the user to react to the whole presented set as ordinary conversation
questions (`.claude/skills/gatekit-shared/references/conversation.md`: ask one, then stop and wait; no fixed
count, no ceiling). The starting posture is a proposed, fuller feature set
the user cuts or edits — not an empty form the user fills.

"빼주세요," "이건 나중에요," "이렇게 바꿔주세요" are all valid, complete
answers. **Do not push for a reason beyond what the user volunteers.**

Every item the user keeps (from either group) becomes an `F<n>` with a
one-line evidence note — `출처: 리서치 (2건 이상 교차확인)`, `출처: 리서치
(참고 아이디어)`, or `출처: 사용자 경험` — so a later reader can audit why
an item the user never explicitly requested ended up in the PRD.

Once the user's reaction to the full set is settled (or a stop signal
arrives), the draft is written from the conversation **plus** whatever of
this proposal the user kept.
