# ADR-0008: Design enters as data, at any stage, reaches the worker by prompt, and stale design is stale

Status: accepted 2026-09-13.

Token gate scope at acceptance: colours only; lengths remain an open question.

## Context

The only design input today is `/gatekit:mockup`. It reads a Figma file,
HTML files, or screenshots, writes `spec/02-screens.md` and
`spec/tokens.json`, and pushes what the mockup does not evidence into the
assumption ledger. That covers a mockup: screens, flows, four states per
screen, a component table, and three token groups (`color`, `space`,
`font`).

Four things it does not cover came up in use:

1. **A design pattern is not a mockup.** "Cards in a list, bottom sheet on
   mobile, destructive actions behind a confirm" is a rule that applies
   across screens. `02-screens.md` has no section for it and `tokens.json`
   has no group for it.
2. **A reference site is not a mockup either.** The most common design
   input a solo builder has is "make it look like this site" plus a few
   screen captures. `mockup.md` accepts HTML *files* and screenshot
   *files*; its allowed tools include neither `WebFetch` nor the Chrome
   tools, so a URL to a live site cannot be read at all.
3. **Design arrives mid-pipeline.** A team often has a PRD and tasks before
   the design system is chosen, or swaps one during the build. `mockup.md`
   has no re-entry rule (compare `interview.md`, which says "if 01 exists
   you are revising", and `discover.md`, which resumes at the first empty
   gate). Re-running it overwrites 02 and `tokens.json` silently. Nothing
   downstream notices: `contract.derive` hashes `spec/05-gate.md` alone,
   `approval.check` is only ever called on that file, and `spec.validate`
   checks 02 for heading presence only. A build keeps running against
   screens that no longer exist.
4. **A worker never sees the design.** `jobs.build_prompt` hands the worker
   its task instruction, write scope, and gate list, and nothing else. No
   spec file is included or even named. A design file is used during the
   build only if the task author remembered to write "read
   `spec/02-screens.md`" into the instruction, and no gate checks that the
   result honoured it.

Also: `docs/ARCHITECTURE.md`, `CLAUDE.md`, and `CONTRIBUTING.md` all say
templates, heading maps, and presets live as data under
`plugin/spec-kit/`. The directory holds a heading map and templates. There
is no preset, no `tokens.json` schema, and no loader.

The constraints that shape the answer are the standing ones: gates live in
hooks, prose is never enforcement, data files not prompt prose, standard
library only in the kernel, and the verdict words are
`ok / warn / fail / unverified`.

## Decision

1. **A new command, `/gatekit:design`, is the re-entrant design input.**
   It is an *extraction* command in the mould of `mockup.md`, not an
   interview: read the source deterministically, write what was observed,
   push every gap into the assumption ledger, and ask at most one
   `AskUserQuestion` about the single gap where a wrong guess costs most.
   It accepts one of:
   - a Figma URL (the four Figma MCP tools `mockup.md` already lists);
   - one or more screenshot files;
   - one or more HTML files;
   - **a URL to a live site** — new. `WebFetch` reads the HTML and any
     linked CSS for routes, repeated class or component patterns, and CSS
     custom properties; the Chrome tools (`navigate`, `get_page_text`,
     screenshot via `computer`) capture the rendered page when the fetched
     HTML is a client-rendered shell. Each capture is saved under
     `spec/design/` and then treated as a screenshot input, so every
     extracted row cites a file that is in the repo, not a URL that may
     change;
   - a preset name (decision 3);
   - a pattern file the user wrote (Markdown or JSON).
   It may run at any stage, including `build`. `/gatekit:mockup` stays as
   the mockup-reading front end for screens and gains the same re-entry
   rule; the two share one writer for `tokens.json`.

2. **Design lives in its own optional file, `spec/02-design.md`.**
   Screens stay in `02-screens.md`. A project with a reference site but no
   mockup gets a full design file and no half-empty screens file. Canonical
   H2s, added to `heading-map.json` for both languages and to `absent_ok`:
   - `## Sources` / `## 출처` — one row per input: kind, path or URL,
     capture date.
   - `## Design patterns` / `## 디자인 패턴` — one row per pattern: `P<n>`,
     name, rule in one sentence, screens it applies to (`S<n>` or `all`),
     evidence (preset name, file, frame, or assumption number).
   - `## Components` / `## 컴포넌트` — name, variants, visual spec in
     token names (not raw values), evidence. `02-screens.md` keeps its own
     component table for *which screens use it*; this one says *what it
     looks like*.
   - `## Design tokens` / `## 디자인 토큰` — summary table; values live in
     `tokens.json`.
   - `## Not covered` / `## 근거 없는 영역` — what the sources do not show.

   `tokens.json` moves to `version: 2`. Groups are open: any top-level key
   that maps to an object of tokens is a group, so `radius`, `shadow`,
   `breakpoint`, `motion` need no code change. Two keys are reserved:
   `source` (a list, because a design now has several origins) and
   `patterns` (the `P<n>` rows as machine data, so `build_prompt` and a
   gate can read them without parsing Markdown).

3. **Presets are JSON files under `plugin/spec-kit/presets/design/`.**
   One file per preset, `<name>.json`, holding exactly what a
   `tokens.json` v2 holds: token groups plus `patterns`. A preset is
   *merged* into the project's `tokens.json`, never copied over it:
   project values win, preset fills gaps, and every row the preset added
   carries `"evidence": "preset:<name>"`. The plugin ships with no
   opinionated preset; the first ones are the ones this repo's owner has
   actually used, and each must be observed in a real build before it is
   committed.

4. **The worker prompt carries the design that its task touches.**
   `jobs.build_prompt` gains a `## Design` section, generated from
   `tokens.json` by code, not by the task author:
   - the `P<n>` rows whose `applies_to` is `all` or names an `S<n>` that
     the task instruction mentions;
   - every token group, as `name: value` lines, so the worker can use
     `color.primary` instead of inventing `#3366ff`;
   - one line naming `spec/02-design.md` and `spec/02-screens.md` as the
     files to read for anything the section does not carry.
   When `tokens.json` is absent the section is omitted, and the prompt is
   byte-identical to today's. This is the point of the ADR: a pattern
   reaches the worker through the same self-contained brief as its
   instruction, and no prose rule has to be remembered.

5. **A token gate makes the design enforceable, task by task.**
   New gate script `plugin/gatekit/gates/tokens.py`, runnable as a task
   gate from `04-tasks.md` like any other (`tasks.md` Step 3 lists it as an
   option; `/gatekit:tasks` adds it by default to every task whose
   `write_scope` includes a stylesheet, component, or template path when
   `tokens.json` exists). It scans the files the task wrote for literal
   values that belong to a token group — hex and `rgb()` colours, `px`
   lengths in `space` or `radius` ranges, font-family strings — and:
   - `ok` when every literal it finds equals a value in `tokens.json`;
   - `fail` when a literal matches no token, naming the file, line, and
     the nearest token by value;
   - `unverified` when `tokens.json` is absent or unparsable, or the task
     wrote no file the gate knows how to scan.
   It is a gate in the ADR-0004 sense: hook-driven, exits 0 on internal
   error, reason printed in `output_lang`. It never edits a file.

6. **Design files are contract inputs, and a changed input makes the
   contract stale.** `contract.derive` stores, next to `source_sha256`, an
   `inputs` map: the sha256 of `spec/02-screens.md`, `spec/02-design.md`,
   and `spec/tokens.json` at derive time (absent files hash to `""`).
   `contract status` compares all of them: `ok` only when the gate file
   and every input match, `fail` when any of them differs. There is no
   new verdict and no new rule. The existing stale-contract path applies
   unchanged: `build` refuses to start, `verify` refuses to grade, and
   `doctor` prints the fix, which is now `/gatekit:tasks` then
   `/gatekit:gate` (re-derive and re-approve).

   A running build is not stopped. The Stop hook and the write gate do not
   read `contract.json` for this, and this ADR does not make them; the
   task workers already spawned finish against the brief they were given.
   The cost accepted here is that a token rename forces a re-derive. That
   is the same cost editing one line of `05-gate.md` already carries, and
   the alternative, a `warn` that one command treats as blocking and the
   others do not, would be the first place a verdict meant two things.

7. **Mid-build, the command reports blast radius instead of editing tasks.**
   When `active_pipeline` is `build`, `/gatekit:design` writes the spec
   files as usual, then lists every task in `04-tasks.md` whose instruction
   or gate names an affected `S<n>` or `P<n>`, and tells the user those
   tasks need redelegation. It does not touch `04-tasks.md` or
   `05-gate.md`; that remains the job of `/gatekit:tasks` and
   `/gatekit:gate`, and the write gate keeps workers out of `spec/` as it
   does today. A redelegated task gets the new `## Design` section on its
   next attempt automatically, because decision 4 generates it at spawn.

8. **The assumption ledger records supersession.** A design input that
   contradicts an existing ledger row does not delete the row. It appends
   a new row whose evidence reads `supersedes A<n>: <source>`, and
   `spec.validate` warns when a superseded row is still referenced by an
   inline marker without its successor.

9. **`spec.validate` learns the `tokens.json` shape.** Version present,
   every group an object of string or object values, `patterns` rows with
   `id`, `rule`, `applies_to`, `evidence`. A malformed file is `warn`, not
   `fail`, because the kernel does not depend on it to run; the finding
   names the key.

## Consequences

- A design reaches a worker by code, in the brief it already reads, scoped
  to the screens its task names. Task instructions may still cite `P<n>`
  for emphasis, but nothing depends on the author remembering to.
- The token gate turns "use the design system" from prose into a verdict.
  A worker that hard-codes a colour fails its task, gets the gate output
  appended to its next prompt by the existing `redelegate` path, and
  retries. This is the first gate that judges *content* rather than
  *scope*; the scan is deliberately narrow (colour, length, font-family)
  so that `fail` stays trustworthy.
- A reference URL is turned into files under `spec/design/` before it is
  read into the spec. The evidence column always points at something in
  the repo. The 1 MB file limit applies to captures; the command
  downsizes or refuses rather than committing a large PNG.
- Changing the design after the gate is approved makes the contract
  stale, exactly as editing `05-gate.md` does. The gate file and its
  inputs are treated alike; there is no file a worker builds against that
  can drift without `build` noticing before it starts.
- `tokens.json` v1 files keep working: a missing `version` or `version: 1`
  is read as one group per top-level key with `source` as a string, and
  the next write upgrades it. No migration step.
- `contract.json` grows one map. `verify`, `build`, and `doctor` each gain
  one line of output naming which input changed. The hooks that exist do
  not change; freshness is checked by the CLI before a build or a verify
  begins, not enforced at Stop.
- Presets are a second place a design value can come from, so every
  merged row carries its origin. The report distinguishes "from preset",
  "from source", and "assumed" exactly as `mockup.md` already separates
  observed from designed.
- `docs/ARCHITECTURE.md` must be updated in the same change: the `spec/`
  tree gains `02-design.md` and `design/`, `tokens.json` becomes
  "optional, from mockup or design pipeline", `active_pipeline` gains
  `"design"`, and the gate table gains `tokens`.

## Open questions

- Which presets ship first, and who observes them in a real build?
