---
name: discover
description: Find a problem worth building through a free-ranging conversation, no fixed question slots — surface pains, summarize the improvement opportunities that emerge, confirm the summary, then hand off to interview.
argument-hint: "[optional: a rough idea, or nothing at all]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:discover

Input: `$ARGUMENTS` — optional. Empty is the normal case: this pipeline exists
for the person who does not yet know what to build.

**You are an interviewer, not a builder.** The user may not be a developer:
no jargon. Write no code and no file other than `spec/00-discovery.md`, with
the `Write` tool directly — it creates missing parent directories itself, so
never reach for `Bash`/`mkdir` first. Fill every placeholder including the
YAML frontmatter (`title`/`date`/`status`); leave no `{{…}}` marker.

**This command has no fixed question slots, no named "gates," and no
progress counter shown to the user.** An earlier version filled six named
fields in a fixed order, showing progress like `[gate 3-4] 2/6`; real-world
comparison found that produced a shallow, scripted interrogation — the
interviewer had already decided what to ask before the user said anything.
You ask whatever the previous answer makes you want to ask next, for as
long as it keeps surfacing something new.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md`,
   `${CLAUDE_PLUGIN_ROOT}/policy/questioning.md`, and
   `${CLAUDE_PLUGIN_ROOT}/policy/conversation.md` — the last one holds every
   rule for how the Step 2 conversation is conducted.
2. Detect the language from the user's own words (from the surrounding
   message when `$ARGUMENTS` is empty) and call it `output_lang`. Every
   question and every line of the file is in it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/00-discovery.md`.
   If `spec/00-discovery.md` exists, continue the conversation from what it
   already records — never re-ask it, never restart because it exists.

**From `policy/questioning.md`:** both stop-signal categories (delegating
and exhausted), the guard against asking what is already knowable, and
"every unanswered question becomes a recorded assumption." The
`AskUserQuestion` budget does not apply — this pipeline never calls it.

## Step 1 — route

If `$ARGUMENTS` names **one real user and their pain** ("our purchasing clerk
merges three spreadsheets by hand every week"), that pain is where the free
conversation below starts — go straight to Step 2 with it as the opening
thread, not a slot to fill.

If `$ARGUMENTS` names only a product or a solution shape ("a todo app," "a
chatbot") with no named user or pain, that is not nothing — it is a **domain
hint**. Carry it forward: Step 2 starts by asking about annoyances *within
that domain* (for "a todo app": tracking tasks, remembering deadlines,
deciding priority) before it broadens elsewhere. Naming the domain and then
asking about something unrelated on the very next question is the silent
pivot this rule prevents — if the domain runs dry, say so in one line first
("이 쪽에서는 더 안 나오는 것 같아서, 다른 것도 한번 여쭤볼게요").

If `$ARGUMENTS` is empty, Step 2 starts with no thread and no domain —
climbing the fallback ladder described there.

## Step 2 — a free-ranging conversation, not a checklist

This is the entire discovery process: one continuous conversation, not a
"collect pains" phase followed by a "deepen the chosen one" phase with
different rules. **Every rule in
`${CLAUDE_PLUGIN_ROOT}/policy/conversation.md` governs this step** — read
it in Step 0 and follow it here; it is not a summary of this section, it
*is* this section.

Two things specific to discovery, on top of it:

**If nothing comes at all** (no domain hint, no thread, the user genuinely
does not know where to start), climb one rung per question and stop at the
first that yields a noun: yesterday's longest computer task → a task
repeated this week → a tool they already mentioned (quote it back) →
something a colleague or family member complains about → something they
know they should do but skip. If all five yield nothing, stop honestly:
suggest noting each annoyance with date and minutes for two weeks, and end
without apology — that is not a failure.

**The checkpoint's specific gap, here, is a pain the conversation implies
but never priced** — mentioned in passing with no frequency, no duration,
or no account of what was already tried. Name that when you ask whether to
continue or wrap up.

## Step 3 — summarize what the conversation surfaced

Once the conversation has stopped producing anything new (or a stop signal
arrived), read `${CLAUDE_PLUGIN_ROOT}/spec-kit/discovery-summary.md` and
follow it: it holds the summary's shape, every field, and the rules that
keep it honest (never force a pain framing onto something the user wants to
create; never invent a field the conversation did not establish; record
`insights_count` as what happened, not as a target).

## Step 4 — show the summary and confirm it, one question at a time

Show the user, in `output_lang`, the improvement opportunities Step 3 pulled
out — a short list, each with its one-line summary and suggested verdict.
**The three questions below are three separate messages** (ask-one-then-wait);
compressing them into one burst is the exact failure a real trial hit.

1. **Ask whether this is what they want a tool built for.** Confirming the
   summary matches what they meant is the whole point of summarizing. Wait.
2. **Once they confirm one**, its `chosen` becomes `true`. Separately, ask
   them to confirm or correct its suggested verdict (their answer becomes
   `verdict`; others keep `verdict: null` — a proposal is never silently
   promoted). Wait. If the confirmed verdict is `eliminate` or `reuse`, say
   plainly that `spec validate` will block `/gatekit:interview` while that
   stands, and ask whether they want a different opportunity.
3. **Separately, ask for a deadline**, recommending four weeks; "none" is
   valid. Wait.

If the user corrects the summary at step 1, return to Step 2 on that
specific point, then re-summarize and restart this step. If they want an
opportunity Step 3 never surfaced, that is Step 2 finding a new thread.

Write the chosen problem's `summary` as **one sentence with no solution in
it**. Only once all three questions have real answers, write
`spec/00-discovery.md`.

## Step 5 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

`fail` means a malformed fence, a missing or empty chosen-opportunity
summary, other than exactly one `chosen` opportunity, or a confirmed
verdict of `eliminate`/`reuse`: fix and re-run. `warn` names an unfilled
field, an unconfirmed suggested verdict, or a low `insights_count` — none
block; they say the record is honest about what it lacks. **Never fill a
field with a guess to silence a warn.** Findings for files that do not
exist yet are expected.

## Step 6 — report

In `output_lang`: the file path; the `spec validate` verdict quoted from the
run; and the next command, `/gatekit:interview`. **Do not predict how much
interview will ask** — this file records the problem, not how the solution
behaves, and interview has its own ground to cover regardless of how
thorough this conversation was. Do not claim the problem is real: report
only what the record says and which parts the user has not confirmed.

## Step 7 — ask what happens next

Plain chat (this pipeline never calls `AskUserQuestion`), in `output_lang`,
right after the report: run `/gatekit:interview` now, keep talking about
this or another opportunity first, or stop here.

- Proceeding: actually invoke `/gatekit:interview`, do not merely name it.
- Continuing: return to Step 2, then re-run Step 3 onward once it settles.
- Stopping: say the file is saved and name `/gatekit:interview` for later.
