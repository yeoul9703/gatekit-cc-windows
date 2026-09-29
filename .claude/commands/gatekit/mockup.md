---
name: mockup
description: Read a Figma file, HTML, or screenshots and derive spec/02-screens.md plus spec/tokens.json, recording every screen state the mockup does not evidence as an assumption.
argument-hint: "[Figma URL | path to HTML | path to screenshots]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__figma__get_design_context, mcp__figma__get_variable_defs, mcp__figma__get_screenshot, mcp__figma__get_metadata
---

# /gatekit:mockup

Input: `$ARGUMENTS` — a Figma URL, HTML files, or screenshot paths.
`spec/tokens.json` is shared with `/gatekit:design`: either may create it,
and both merge rather than overwrite.

## Step 0 — load policy and language

1. Read these under `.claude/gatekit/policy/`: `language.md`,
   `questioning.md`, `assumptions.md`, `verification.md`.
2. Detect the language:

```
".claude/gatekit/bin/gatekit" lang "$ARGUMENTS"
```

If `$ARGUMENTS` is only a URL or path, detect from the user's surrounding
message instead. Call the result `output_lang`.

3. Read `.claude/gatekit/spec-kit/heading-map.json` and
   `.claude/gatekit/spec-kit/templates/<output_lang>/02-screens.md`.

## Step 1 — re-entry check

If `spec/02-screens.md` or `spec/tokens.json` already exists you are
**revising**: keep every `S<n>` id stable, add rows rather than overwrite,
handle contradictions by supersession (`policy/assumptions.md`).

## Step 1.5 — force the source-or-new choice, every run

**Never infer "no design source" from `$ARGUMENTS` being empty.** Ask
explicitly, every run:

- **A source is already named** — confirm briefly in plain text ("이 소스로
  진행할까요, 아니면 새로 디자인을 받을까요?"); someone who pasted a stale
  link still gets to say "design something new." No `AskUserQuestion` here.
- **`$ARGUMENTS` is empty** — one `AskUserQuestion`: does a source exist
  that was just not attached, or should gatekit propose something new?
  Deliberately one question every run, so "no source" is something the user
  said rather than something assumed from silence.

Answering "I have a source" without providing one: ask once more for the
path, then fall through only if there truly is none.

**New-design branch.** List
`.claude/gatekit/spec-kit/presets/design/*.json` and offer them as
one `AskUserQuestion`, describing each from its own `patterns` (density,
palette warmth, feel) rather than its filename. Run `python3
".claude/gatekit/bin/gatekit" design merge-preset <name>` on the
pick. If the catalog is somehow empty, ask for a style direction in the
user's own terms and write it into `spec/tokens.json` instead. Either way
that direction becomes Step 2's input: go to Step 3 with placeholder
screens from `01-prd.md`'s features, every layout decision assumed.

## Step 2 — read the source deterministically

Pick the branch that matches the input. Extract; do not imagine. **Every
extracted item carries its evidence** — the frame name, file path, or
selector it came from.

**Figma URL** — with the Figma MCP tools: `get_metadata` for the frame
tree, `get_design_context` for structure and component names,
`get_variable_defs` for tokens, `get_screenshot` for a visual check. If
those tools are unavailable, say so, ask for an export or screenshots, and
stop. **Never guess a design from a URL.**

**HTML files** — routes or page boundaries, repeated class or component
patterns, CSS custom properties for tokens.

**Screenshots** — name each screen after what it shows.

## Step 3 — write spec/02-screens.md

Fill the template including its YAML frontmatter (`title`/`date`/`status`).
Headings verbatim from `heading-map.json[<output_lang>]`.

- **Screen list** — one row per screen, `S<n>` id plus evidence.
- **Screen flow** — transitions the mockup actually shows; an inferred one
  is an assumption, marked as such in the evidence column.
- **Per-screen states** — normal, empty, error, loading for every screen.
  Mockups almost never show all four: design the missing ones, mark each
  assumed.
- **Components** — name, screens used on, variants, source component name.
- **Design tokens** — a summary table only.
- **Negative space** — what the mockup does **not** cover. An empty list
  means you did not read closely enough: offline, permissions, long lists
  and strings, error recovery, first-run.

## Step 4 — write spec/tokens.json

Machine-readable values grouped by kind. If the file exists already (a
prior run, or `/gatekit:design`), **merge** rather than overwrite — add
token names and append to `source`:

```json
{"version": 1, "source": "<figma url or file path>",
 "color": {"primary": "#000000"}, "space": {"md": "16px"}}
```

Token names are identifiers: keep the design system's own spelling. Omit a
group rather than inventing values for it.

## Step 5 — push gaps into the assumption ledger

Every state, flow, or component **not** evidenced by the mockup becomes a
row in `spec/01-prd.md`'s ledger plus an inline marker in `02-screens.md`
where it is used, per `.claude/gatekit/policy/assumptions.md`. If
`01-prd.md` exists, continue its numbering; if not, create it from the
template in draft mode — headings filled, unknown sections marked "not yet
interviewed" — and tell the user to run `/gatekit:interview`.

## Step 6 — validate

```
".claude/gatekit/bin/gatekit" spec validate --json
```

On `fail`, rewrite the offending file from the template rather than
patching. Never deliver a failing file. Missing 03, 04, 05 are expected.

## Step 7 — the preview and the prototype gate

**Read `.claude/gatekit/spec-kit/prototype-gate.md` and follow it.**
Both halves live there: the **optional static preview** (offered only when
the screens were designed rather than observed), and the **live prototype
gate**, *not* skippable for a UI-bearing project — real clickable HTML for
every screen and state, realistic sample content, revised until the user
confirms, then the explicit "does this cover everything?" question and the
`Prototype confirmed <date>` line. Without that line, `/gatekit:tasks`
refuses to run. Skipped when `01-prd.md` carries the `[non-ui]` marker.

## Step 8 — report

In `output_lang`: (1) files written with paths, preview and prototype
included; (2) screens and states extracted, as counts on their own line;
(3) the `spec validate` verdict quoted from the run; (4) the negative-space
list, then new assumption rows by number; (5) whether the prototype is
confirmed and if not what is open; (6) the next command —
`/gatekit:interview` if 01 is still a draft, else `/gatekit:tasks`, but
only once the prototype is confirmed. Say plainly when it is not.

State what the mockup showed and what you filled in. **Never present a designed state as observed.**

## Step 9 — ask what happens next

One closing `AskUserQuestion` after the report. While the prototype is
unconfirmed, "more work here" means continuing that revision loop, not a
fresh run of Step 1. Options: keep revising (while unconfirmed), proceed to
the command Step 8 named (once confirmed), or stop.

- Proceeding: actually invoke the named command.
- Revising: return to the prototype loop.
- Stopping: confirm what is saved and what remains open.
