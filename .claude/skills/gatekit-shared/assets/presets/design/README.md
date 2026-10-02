# Design presets

A preset is one JSON file, `<name>.json`, in this directory. It holds exactly
what a project's `spec/tokens.json` holds at version 2: open token groups plus
`patterns`. `gatekit design merge-preset <name>` merges it into the project's
`spec/tokens.json`.

Presets come in two kinds, told apart by their `source` field:

- **Seed presets** (`"source": ["seed:<origin>"]`) — adopted from an
  established, widely-used design system or component library (shadcn/ui,
  Material, etc.), not invented here. These may be committed immediately,
  without a gatekit build first: the origin's own track record is the
  evidence, and gatekit's greenfield fallback (ADR-0017 decision 3) needs at
  least one real option to offer before any project has ever been built
  with it — a preset directory with nothing in it is not neutral, it is the
  reason a source-less project falls through to unstyled browser defaults.
- **Observed presets** (`"source": ["preset:<name>"]` after a real
  `merge-preset` run, or any preset not adopted from an established source)
  — must be **observed in a real build before being committed**, the
  original rule this README stated. Write it, merge it into a real project,
  run the build, and only then add the file here. A preset that has never
  produced a passing build and is not a seed from elsewhere is a guess with
  a filename.

A seed preset that later gets refined from real build feedback stays a seed
(its origin does not change), but the refinement itself should be checked
against a real build the same way an observed preset would be.

## Shape

```json
{
  "version": 2,
  "patterns": [
    {"id": "P1", "rule": "Destructive actions sit behind a confirm.", "applies_to": "all"}
  ],
  "color": {"primary": "#3366ff", "danger": "#cc2222"},
  "space": {"sm": "8px", "md": "16px"},
  "radius": {"md": "8px"}
}
```

Groups are open. Any top-level key mapping to an object of tokens is a group,
so `radius`, `shadow`, `breakpoint` and `motion` need no code change. Two
top-level keys are reserved and are not groups: `source` (a list) and
`patterns` (a list of rows with `id`, `rule`, `applies_to`, `evidence`).

A token value may be a string (`"#3366ff"`) or an object
(`{"value": "#3366ff", "evidence": "..."}`). Writing the string form in a
preset is enough; the merge fills in the evidence.

## What merging does

Merging never overwrites. Project values win, the preset fills gaps only:

- A token the project already defines is left exactly as it is, string or object.
- A token the preset adds is written as `{"value": <the preset's value>,
  "evidence": "preset:<name>"}`. A scalar in the preset is upgraded to that
  object form, so every token can say where it came from. An object in the
  preset keeps its `value` but gets `evidence: "preset:<name>"`, because for
  this project the preset *is* the origin.
- A pattern whose `id` the project already uses is skipped. A pattern the
  preset adds gets `"evidence": "preset:<name>"`.
- `source` gains `"preset:<name>"` once, however many times the merge runs.
- A version 1 file is upgraded to version 2 in place: its `source` string
  becomes a one-item list and `patterns` starts empty.

The result is that `spec/tokens.json` always distinguishes "from this
project's sources" from "from a preset", which is what the design report and
the assumption ledger rely on.

## Committing a new preset

**Seed preset**: cite the real origin in `source` (e.g. `"seed:shadcn-ui"`),
keep values as that system's own defaults or documented conventions — never
invented values dressed up as someone else's — and commit directly.

**Observed preset**: the same rule gatekit applies to any parity claim —
write it, merge it into a real project, run the build, and only then add
the file here. A preset that has never produced a passing build and is not
a cited seed is a guess with a filename.
