# The preview and the live prototype

Read by `/gatekit:mockup` at Step 7, after `spec/02-screens.md` and
`spec/tokens.json` validate. It covers the optional static preview and
the non-skippable prototype confirmation gate.

## Step 7 — one question: the static preview, or straight to the gap

**One** `AskUserQuestion` call, skipped after a stop signal ("알아서 해줘").
This is independent of the live prototype gate in Step 7b below, which is
never skippable for a UI-bearing project — this question only decides
whether to *also* draw the quick static picture first.

**`$ARGUMENTS` empty, or the new-design branch from Step 1.5 ran** — the
screens were designed, not observed — spend it on the preview (ADR-0011): see
a preview of the screens, or go straight to the live prototype. On a yes, run
Step 7a. **A design source was read** — the screens were observed, so a
drawing adds nothing: spend the call on the single gap where guessing wrong
costs most, usually an error or empty state with a real branch behind it, and
go straight to Step 7b.

## Step 7a — draw, show, correct (only on a yes in Step 7)

Write `spec/design/preview-<project>.html` — one section per `S<n>`, built
from `spec/02-screens.md` (layout, components, the four states) and
`spec/tokens.json` (every value) — and publish it so the user can open it.

- **First visible element is the banner**, in `output_lang`: an approximate
  pattern only, the real build may differ, drawn from the spec rather than
  observed. This is the responsibility boundary, not politeness — the user is
  looking at the *screen spec*, not the product.
- **Static.** A screen's four states are four panels to read, not to click.
- **Tokens only.** Every value comes from `tokens.json` by name; one the
  tokens do not carry is **not invented** but drawn as a labelled placeholder
  naming what is missing. One file, no external requests, no build step.

Then loop until the user is done: show it → they say what to change → **edit
`spec/02-screens.md`**, never only the HTML, since that file is what reaches
the workers → redraw and show again. Nothing is recorded as approved and no
assumption closes; the corrections are the point and they travel in the spec.
Re-run `spec validate` after any edit, and **never cite the preview in an
evidence cell** — it is drawn from this spec, so it cannot be evidence for it
(ADR-0011). When the user is satisfied here, continue to Step 7b — the static
preview does not substitute for it.

## Step 7b — the live prototype gate (ADR-0017 decision 4, not skippable for a UI-bearing project)

`spec validate` refuses `/gatekit:tasks` while this step's confirmation is
missing (the `prototype_required` finding) — this is the direct fix for "기다림
끝에 보여지는 결과는 엉망": the user must see and touch the real shape of the
thing before `/gatekit:build` starts, not after. Skipped entirely when
`spec/01-prd.md` carries the `[non-ui]` marker (a pure CLI or library spec has
nothing to prototype).

1. Build `spec/design/prototype-<project>.html` as **real, clickable HTML and
   CSS** — every named screen `S<n>` reachable through the flow
   `02-screens.md` records, styled from `spec/tokens.json`, all four states
   for each screen present as actually-navigable views (not four static
   panels side by side as in Step 7a — clicking "empty the list" or
   triggering an error must show that state). This is still frontend-only,
   disconnected from any backend: no build has started, the same boundary
   Step 7a's static preview already drew, now expressed as working markup
   instead of a picture. **Fill every screen with realistic sample content,
   not empty inputs or lorem ipsum** — every feature `01-prd.md` lists as an
   `F<n>` should be visibly present and populated with plausible data (a
   character list showing real-looking character names and a last-message
   preview, not three blank cards), so the prototype reads as a finished
   product's actual screen, not a wireframe waiting for content. This is
   the whole point of the prototype gate: the user judges completeness
   against what the finished thing would look like, not against an
   abstraction.
2. Hand it to the user to actually open (a file path today; a
   Claude-in-Chrome-driven walkthrough where that tool is available and the
   user wants it — never the required path, since it adds real per-round
   latency a static file does not have). Ask for feedback as concrete change
   requests against a specific screen and element, not free-form prose about
   the whole app.
3. Apply each revision directly to the HTML/CSS **and** to `02-screens.md`
   (the file `/gatekit:tasks` actually reads — nothing new needed here, this
   is the same write-back path Step 7a's loop already uses), then hand the
   prototype back. Repeat until the user confirms explicitly.
4. **Before asking for final confirmation, ask one explicit question: does
   this prototype fully cover what you want built, or is something still
   missing?** This is not the same question as "does this look right" —
   the prototype is the first time the whole feature set is visible as
   actual screens rather than a list, and a gap that a `01-prd.md` bullet
   list hid can become obvious once it is something to click through. If
   the answer names something missing, treat it as new ground for
   `/gatekit:interview`'s Step 2 conversation: route back there, let the
   feature get defined properly (page, behavior, data — not invented here),
   then return to regenerate this prototype once `01-prd.md` and
   `02-screens.md` reflect it. Do not silently invent the missing feature
   in the HTML to avoid the round trip.
5. On confirmation, append a line to `spec/02-screens.md`, after the
   Negative space section, in the exact form `spec validate` scans for:
   `Prototype confirmed <date>` (or `프로토타입 확정 <date>` in Korean). This
   is prose, not a hash-anchored approval like `05-gate.md`'s — the
   prototype is revised in-loop until confirmed, so there is no single
   moment before that to pin a hash to.

Never treat "the prototype looks finished to me" as confirmation — only the
user's explicit yes, via a closing `AskUserQuestion` ("이대로 확정할까요?" /
"더 수정할 부분이 있어요"), writes the confirmation line.

