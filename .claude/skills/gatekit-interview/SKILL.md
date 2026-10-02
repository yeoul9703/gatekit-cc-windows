---
name: gatekit-interview
description: Turn a chosen problem into spec/01-prd.md and spec/03-architecture.md through a deep, free-ranging interview on implementation shape — pages, what each page does, what data it needs — laying the groundwork for design and tasks. Korean triggers — "~ 앱 만들고 싶어", "이런 거 만들어보자", "기획해줘", "PRD 써줘", "요구사항 정리해줘", "뭘 만들지 정리하자", "스펙 만들어줘". English triggers — "I want to build a ... app", "write a PRD", "spec this out", "turn this idea into requirements", "plan what to build". When the user names something to build, call this before any code is written. NOT for writing code, and NOT for reading an existing Figma file, HTML or screenshots — that is /gatekit-mockup.
argument-hint: "[what you want to build, in your own words]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell, WebSearch
---

# /gatekit-interview

Input: `$ARGUMENTS` — the user's description of what they want to build. If
it is empty, or names a product without a real user and their pain ("a
chatbot", "a productivity app"), stop and route the user to
`/gatekit-discover`. This pipeline assumes the problem is already known.

**The point is not writing a PRD quickly — it is a deep interview that
turns a chosen problem into implementation shape**: how many pages the
thing needs, what each does, what a user sees and can act on, what
information it needs. Design direction (palette, typography, mood) is out
of scope — that is `/gatekit-mockup`'s job, once this command gives it
something concrete to design for.

## Step 0 — load policy and language

1. Read `.claude/skills/gatekit-shared/references/preamble.md` and follow it, detecting
   `output_lang` **from the input** (`$ARGUMENTS`).
2. Read these under `.claude/skills/gatekit-shared/references/`: `questioning.md`,
   `conversation.md` (how Step 2 is conducted), `assumptions.md` (the
   ledger Step 3 writes), `verification.md`.
3. Read `.claude/skills/gatekit-shared/assets/heading-map.json` and the templates
   `.claude/skills/gatekit-interview/assets/01-prd.md` and
   `.claude/skills/gatekit-interview/assets/03-architecture.md`.

**From `.claude/skills/gatekit-shared/references/questioning.md`:** both stop-signal categories and the guard
against asking what is already knowable. Its two-call `AskUserQuestion`
budget does **not** apply to Step 2's conversation.

## Step 1 — bring discovery in as given, do not re-ask it

Look at what is already knowable. Do not ask the user for any of it.

**If `spec/00-discovery.md` exists, its entry marked `chosen: true` is this
interview's starting point, taken as settled fact — not re-verified, not
re-asked.** Read every field it filled, and **read `notes` too**: it holds
what the named fields have no slot for (success criteria, requirements like
"여러 캐릭터를 만들 수 있어야 한다") at the same weight, not as a footnote.
What the record never established is an open gap Step 2 can pick up; the
problem itself is not re-litigated here.

**Check the verdict gate first.** Run `spec validate` before the interview
starts. A `pain_verdict_blocks` finding means the confirmed verdict is
`eliminate` or `reuse` — **stop**, tell the user which verdict blocked it
and why (quoting `verdict_suggested.why`), and ask whether they want a
different pain. `pain_verdict_unconfirmed` is not blocking — resolve it
early in Step 2 rather than carrying a proposal forward as fact.

Also look at `spec/` (do 01 or 03 exist? then you are revising), the
repository's languages, frameworks and test runner, and `README*`,
`package.json`, lockfiles, CI config. **These are facts, not assumptions.**

## Step 2 — the interview: one continuous conversation toward implementation shape

Two files govern this step, both read in Step 0:

- **`.claude/skills/gatekit-shared/references/conversation.md` — *how* to ask.** Every
  rule there applies here exactly as it does in `discover.md`.
- **`.claude/skills/gatekit-interview/references/interview-subjects.md` — *what* to ask
  about**: how many pages, what a user can do on each, what each feature
  needs to work, the unglamorous branches, and confirming each feature's
  mapping to behavior in the turn it comes up.

The conversation keeps going as long as it still turns up something
concrete that the design and task-cutting stages will need and do not have.

## Step 2.5 — research the domain, then propose what the conversation never raised

**A free-ranging conversation only ever produces what the user thought to
say** — `gk-todo4`'s character-chat PRD covered memory and persona in depth
and never touched context-window management, content safety, or persona
drift, all standard for that category.

**Read `.claude/skills/gatekit-interview/references/domain-research.md` and follow it**:
freeze what the conversation established (never edited by what follows),
research the category across four angles with two-source corroboration,
diff against the frozen set, present what remains in two labeled groups,
and let the user prune rather than fill a blank. Once that settles (or a
stop signal arrives), continue to Step 3, drafting from Step 2 **plus**
whatever of this proposal the user kept.

## Step 3 — draft

Once the interview settles, write both files from the templates, filling
every placeholder including each file's YAML frontmatter
(`title`/`date`/`status`). Leave no `{{…}}` markers anywhere. Headings come
verbatim from `headings` in `heading-map.json`; never mix two languages'
headings in one file.

- `spec/01-prd.md` — problem, measured current state, goals, non-goals,
  users, features with `F<n>` ids (each one's page and behavior fixed by
  Step 2, not decided here), acceptance criteria, assumption ledger.
- `spec/03-architecture.md` — stack, data model, identifiers and tokens,
  external integrations, constraints.

**Every judgement made without confirmation becomes a ledger row plus an
inline marker, per `.claude/skills/gatekit-shared/references/assumptions.md`** (read in
Step 0) — including the `Blocking` bar and why a `Blocking: y` row left
`Confirmed: n` fails validation. Name those rows plainly in Step 6 rather
than letting the user hit the block later at `/gatekit-gate`.

## Step 4 — validate

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate --json
```

On `fail`: read the findings, **discard the failing file and rewrite it**
from the template. Never hand the user a file that fails validation, never
patch around a finding you do not understand. Re-run until `ok` or `warn`,
or until three rewrites failed — then stop and report what remains.
Findings for files that do not exist yet are expected `warn`.

## Step 5 — confirm the draft

Show the full `F<n>` list as one list — Step 2's features and whatever of
Step 2.5's proposal the user kept, without separating "what you said" from
"what research added." One explicit confirmation that this whole set is
what gets built.

One `AskUserQuestion`: does this match what should actually be built? Offer
approve, revise a named section (returns to Step 2), or start over.

## Step 6 — report

In `output_lang`, in this order: (1) the two file paths; (2) the `spec
validate` verdict quoted from the run; (3) residual assumptions as a
numbered list matching the ledger, each with its impact if wrong, blocking
rows named plainly; (4) the pages settled on and what each does — the
concrete output the next command needs; (5) what Step 2.5 proposed, by
group (기본기 후보 / 참고 아이디어), and for each whether the user kept it
(as which `F<n>`), made it a non-goal, or left it in `notes`.

Do not claim the spec is correct. Claim only that it validates and that
these assumptions are open.

## Step 7 — hand off

Read `.claude/skills/gatekit-shared/references/handoff.md` and follow it.

- Form: one closing `AskUserQuestion`.
- Next: `/gatekit-mockup`; `/gatekit-tasks` instead when the PRD's
  non-goals carry the `[non-ui]` marker (a project with no screens).
- More work here: revise a named section, then re-run Step 4.
