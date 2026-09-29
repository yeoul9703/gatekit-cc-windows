# Policy: the assumption ledger

Every judgement made without the user's confirmation is recorded in
`spec/01-prd.md`'s assumption ledger, and marked inline where it is used.
`spec validate` checks the two against each other.

## The two halves must match

An inline marker at the place the assumption is used:

```
> ⚠️ Assumption 2: {{what you assumed}}
```

and a numbered row in the ledger table. **Numbers match one-to-one between
markers and rows.** A marker with no row fails validation; a row with no
marker warns.

Measured values you do not have are written as "not measured" plus a ledger
row — never invented.

## `Blocking` and `Confirmed`

Every row carries two extra columns, each `y` or `n`.

**`Blocking: y` when being wrong about this specific row would directly
hurt how a core feature actually feels to use** — not only when it would
sink the entire plan. "Would this make the plan collapse" is too high a bar
and lets exactly the assumptions worth catching slip through as `n`.

A worked example: for a feature whose description is literally "친밀도와
말투 변화," both the numeric weighting behind intimacy and its on-screen
display form are `Blocking: y`, even though the plan survives being wrong
about either. What does not survive is that feature's actual quality.

Things genuinely low-cost to be wrong about — which of three interchangeable
sample characters ships first, an internal file name — stay `Blocking: n`.

**Every row starts `Confirmed: n`** unless the conversation already
established it as fact, in which case it is not an assumption at all and
gets no row.

## What a blocking, unconfirmed row does

A row marked `Blocking: y` and left `Confirmed: n` makes `spec validate`
**fail**, not warn, and `/gatekit:gate` refuses to proceed while it stands.

So name the blocking rows plainly in the command's own report, rather than
letting the user discover the block later at a stage that looks unrelated.

## Supersession, not deletion

When a later source contradicts an existing row, do not delete the row.
Append a new one whose evidence reads `supersedes A<n>: <source>`, and note
the supersession next to the row it replaces. The record of what was once
believed is part of what makes the ledger worth keeping.
