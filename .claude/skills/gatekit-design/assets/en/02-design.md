---
title: "{{project_name}} — design specification"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — design specification

Optional. Written by `/gatekit-design` from a reference site, a preset, a
pattern file, or the same mockup `02-screens.md` came from. `02-screens.md`
says which screens exist; this file says what they look like.

## Sources

One row per input. A URL is captured into `spec/design/` first, so every
evidence cell below points at a file in this repository.

| Kind | Path or URL | Captured |
|---|---|---|
| {{screenshot · html · figma · preset · pattern-file}} | {{spec/design/home.png}} | {{YYYY-MM-DD}} |

## Design patterns

Rules that hold across screens. `applies_to` is a list of screen IDs or `all`.
These rows are mirrored in `spec/tokens.json` under `patterns`, which is what
the worker prompt and the token gate read.

| ID | Name | Rule | Applies to | Evidence |
|---|---|---|---|---|
| P1 | {{list density}} | {{One sentence a worker can follow without asking.}} | {{S1, S2}} or `all` | {{spec/design/home.png, preset:<name>, or assumption N}} |

## Components

What a component looks like, in token names rather than raw values. Which
screens use it stays in `02-screens.md`.

| Component | Variants | Visual spec (token names) | Evidence |
|---|---|---|---|
| {{PrimaryButton}} | {{default / disabled / loading}} | {{color.primary bg, space.sm padding, radius.md}} | {{spec/design/home.png, or assumption N}} |

## Design tokens

Values live in `spec/tokens.json` (version 2). Groups are open: any top-level
key mapping to an object of tokens is a group, so `radius`, `shadow`,
`breakpoint` and `motion` need no schema change. `source` and `patterns` are
reserved. Keep only a summary here.

| Group | Token | Value | Evidence |
|---|---|---|---|
| color | {{color.primary}} | {{#000000}} | {{spec/design/home.png}} |
| space | {{space.md}} | {{16px}} | {{preset:<name>}} |

## Not covered

What the sources do **not** evidence. Every line here should also be an
assumption-ledger row in `01-prd.md`. An empty list means the sources were not
read closely enough.

- {{e.g. no source shows the dark theme}}
- {{e.g. no source shows the error state of a form}}
- {{e.g. no source shows any screen below 768px}}
