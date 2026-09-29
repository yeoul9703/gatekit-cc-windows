---
name: design
description: Read a Figma file, screenshots, HTML files, a live site URL, a preset, or a user pattern file and derive spec/02-design.md plus spec/tokens.json, recording every gap the source does not evidence as an assumption.
argument-hint: "[Figma URL | screenshot/HTML paths | live site URL | preset name | pattern file]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__figma__get_design_context, mcp__figma__get_variable_defs, mcp__figma__get_screenshot, mcp__figma__get_metadata, WebFetch, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__computer, mcp__claude-in-chrome__tabs_close_mcp
---

# /gatekit:design

Input: `$ARGUMENTS` — a Figma URL, screenshot or HTML paths, a live site URL, a
preset name, or a path to a pattern file the user wrote.

This is an *extraction* command, not an interview: read the source
deterministically, write what was observed, push every gap into the
assumption ledger, and ask at most one `AskUserQuestion` about the single gap
where a wrong guess costs most. It may run at any stage of the pipeline,
including mid-build.

## Step 0 — load policy and language

Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md`,
`${CLAUDE_PLUGIN_ROOT}/policy/questioning.md`, and
`${CLAUDE_PLUGIN_ROOT}/policy/verification.md`. Detect the language with
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"` — if
`$ARGUMENTS` is only a URL or a path, detect from the user's surrounding
message instead. Call the result `output_lang`. Read
`${CLAUDE_PLUGIN_ROOT}/spec-kit/heading-map.json` and
`${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/02-design.md`.

## Step 1 — re-entry check

If `spec/02-design.md` or `spec/tokens.json` already exists, you are
**revising**, not creating: keep every existing `S<n>` and `P<n>` id stable
(never renumber or delete a row), add new rows rather than overwriting, and
when a new source contradicts an existing row, do not delete it — append a
new row whose evidence reads `supersedes A<n>: <source>` in the assumption
ledger (Step 5), noting the supersession next to the row it replaces.

## Step 2 — mid-build check

Check the session ledger (`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py"
ledger show --session <session_id>`, using the current `session_id`). If
`active_pipeline` is `build`, run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" design impact --json`,
report every task it lists grouped by id, and tell the user those tasks need
redelegation once `/gatekit:tasks` and `/gatekit:gate` bring the contract
current again. **Do not edit `spec/04-tasks.md` or `spec/05-gate.md`** —
that stays the job of those two commands. Then continue to Step 3; the
design files are still written as usual.

## Step 3 — read the source deterministically

Pick the branch that matches `$ARGUMENTS`. Extract; do not imagine. Every
extracted row cites the source it came from — a frame name, a file path, a
selector, or a preset name. **Refuse a `spec/design/preview-*.html` path**: a
preview is drawn from the spec, so reading it back in would let the spec
corroborate itself (ADR-0011). Say so and ask for a real source.

| Input | How to read it |
|---|---|
| Figma URL | Same as `/gatekit:mockup`: `get_metadata` for the frame tree, `get_design_context` for structure and component names, `get_variable_defs` for tokens, `get_screenshot` for a visual check. If the Figma MCP tools are unavailable, say so and ask for an export or screenshots — never guess a design from a URL. |
| Screenshot files | Read each image; record which file each observation came from. |
| HTML files | Read each file; extract repeated class or component patterns and CSS custom properties for tokens. |
| Live site URL | `WebFetch` the page and any linked CSS first for routes, repeated patterns, and CSS custom properties. If the fetched HTML is a client-rendered shell (little more than a script tag and an empty root element), use the Chrome tools instead: `navigate` to the URL, `get_page_text` for rendered content, `computer` to capture a screenshot. Save every capture — HTML, CSS, screenshots — under `spec/design/` and cite the saved file, never the URL, as evidence; a screenshot over 1 MB (CI's repo-wide limit) must be downsized or refused, never committed oversized. Host note: `WebFetch` and the Chrome tools are Claude Code host tools — under Codex, if unavailable, say so and ask for local captures instead of guessing from the URL. |
| Preset name | Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" design merge-preset <name>`. Project values win; every row the preset added carries `"evidence": "preset:<name>"`. Cite the preset name as the source. |
| User pattern file | Read the Markdown or JSON file; extract each rule as a `P<n>` row citing the file as evidence. |

## Step 4 — write spec/02-design.md

Fill the template, including its YAML frontmatter block (`title`/`date`/
`status`) at the top. Headings verbatim from `heading-map.json[<output_lang>]`:

- **Sources** — one row per input: kind, path or URL, capture date.
- **Design patterns** — `P<n>`, name, the rule in one sentence, screens it
  applies to (`S<n>` or `all`), evidence.
- **Components** — name, variants, visual spec in token names (not raw
  values), evidence: *what it looks like*. `02-screens.md`, if it exists,
  keeps its own component table for *which screens use it* — don't
  duplicate that here.
- **Design tokens** — a summary table; values live in `spec/tokens.json`.
- **Not covered** — what the sources do not show. Empty means under-read.

## Step 5 — write or merge spec/tokens.json

Shared with `/gatekit:mockup`, written as v2:

```json
{"version": 2, "source": ["<figma url, file path, live URL, or preset name>"],
 "patterns": [{"id": "P1", "rule": "…", "applies_to": ["S1"], "evidence": "…"}],
 "color": {"primary": "#000000"}, "space": {"md": "16px"}}
```

Groups are open — any top-level key mapping to an object of tokens is a
group. Omit a group entirely rather than inventing values for it. If
`tokens.json` already exists (v1 or v2), merge rather than overwrite: add
new token names, append new `source` entries and new `patterns` rows
continuing the existing `P<n>` numbering. Never delete an existing row.

## Step 6 — push gaps into the assumption ledger

Every pattern, component spec, or token the source does not evidence
becomes a row in the assumption ledger of `spec/01-prd.md`, plus an inline
marker in `02-design.md`. If `01-prd.md` does not exist, create it from the
template in draft mode as `/gatekit:mockup` does, and tell the user to run
`/gatekit:interview` to complete it. Inline marker numbers and ledger row
numbers must match exactly; a supersession row (Step 1) is a ledger row
like any other.

## Step 7 — validate

Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json`.
On `fail`, rewrite the offending file from the template rather than
patching — never deliver a failing file. Missing 03, 04, 05 are expected
`warn` here.

## Step 8 — ask only about gaps

At most **one** `AskUserQuestion` call, four options, in `output_lang`, for
the single gap where guessing wrong would cost the most. Skip it after a
stop signal, and skip it if Step 2 already reported blast radius (don't
stack a question on a mid-build report).

## Step 9 — report

In `output_lang`: files written (including anything under `spec/design/`);
patterns and tokens extracted as counts; the `spec validate` verdict quoted
from the run; the not-covered list; new or superseded assumption rows by
number; if Step 2 found the pipeline mid-build, the tasks needing
redelegation; and the next command — `/gatekit:tasks` if `04-tasks.md`
doesn't exist yet or Step 2 found affected tasks (contract now stale),
otherwise `/gatekit:mockup` if no screen spec exists, otherwise
`/gatekit:tasks`.

State what the source showed and what you filled in. Never present a
designed value as an observed one.
