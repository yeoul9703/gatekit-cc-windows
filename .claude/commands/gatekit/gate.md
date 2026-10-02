---
name: gate
description: Derive executable completion criteria into spec/05-gate.md, show them for approval, and on approval pin the hash so the build gate opens. Korean triggers — "완료 기준 정해줘", "게이트 만들어줘", "언제 끝난 건지 정의해줘", "DoD 만들어줘". English triggers — "define done", "set the completion gate", "write the acceptance gate", "definition of done". NOT for running the criteria after the fact — that is /gatekit:verify — and NOT for approving on the user's behalf.
argument-hint: "[optional: extra criteria to include]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, PowerShell
---

# /gatekit:gate

Input: `$ARGUMENTS` — optional additional criteria the user wants enforced.

## Step 0 — load policy and language

1. Read `.claude/gatekit/policy/preamble.md` and follow it, detecting
   `output_lang` **from the spec**.
2. Read `.claude/gatekit/policy/verification.md`.
3. Read `.claude/gatekit/spec-kit/heading-map.json` and
   `.claude/gatekit/spec-kit/templates/<output_lang>/05-gate.md`.

## Step 1 — read the inputs

Read the acceptance criteria in `spec/01-prd.md` and every task in
`spec/04-tasks.md`. Both files must exist; if `04-tasks.md` is missing, stop and
send the user to `/gatekit:tasks`.

## Step 2 — derive criteria

**Read `.claude/gatekit/spec-kit/gate-criteria.md` now and follow it**
for this step and the next. It holds the `gatekit-criterion` fence and its
fields, the `gatekit-budget` fence, the screenshot criterion for UI tasks,
and the rule that every criterion is run here before it is written in.

Fill the template's YAML frontmatter block (`title`/`date`/`status`) along
with the rest of `spec/05-gate.md`. Write one criterion per acceptance
criterion in 01, plus one per task in 04 whose completion is not already
covered, plus the screenshot criterion for every task that touched a UI
surface. `argv` runs without a shell: no `&&`, no pipes, no redirection.

## Step 3 — write the "not counted as done" section

This section is the point of the file: the conditions that make a
plausible-looking pass invalid. The minimum list is in
`gate-criteria.md`; add project-specific ones from the constraints in
`spec/03-architecture.md`.

## Step 4 — validate and derive the contract

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate --json
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py contract derive
```

`spec validate` must not be `fail` before you continue. `contract derive` writes `.gatekit/contract.json` with the source hash of `05-gate.md`.

## Step 5 — show the criteria

Present every criterion to the user in `output_lang`, as a table: id, what it
proves, the exact command. Then state plainly what approval changes:

> Approving pins the hash of this file. From that point the write gate stops
> blocking edits outside `spec/`, so source files can be written. The Stop hook
> will run these commands and block completion while any of them fails or comes
> back unverified. Editing this file afterwards expires the approval.

## Step 6 — approve

One `AskUserQuestion` in `output_lang`, with options: approve as written,
revise a named criterion, or add a criterion. On revise or add, apply the
change, re-run Step 4, and ask again.

On approve:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve spec/05-gate.md
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py approve check spec/05-gate.md
```

The check must print `ok`. Never edit the file to make a hash match.

## Step 7 — report

In `output_lang`: (1) the file path and the number of criteria; (2) the
`spec validate` and `approve check` results, quoted from the runs; (3) that
the write gate now allows source edits outside `spec/`; (4) that any later
edit to `05-gate.md` expires the approval and requires re-approval plus
`contract derive`; (5) the next command, `/gatekit:build`.

If the user did not approve, say so explicitly and state that the write gate
remains closed. Do not approve on their behalf.
