# The reviewer's brief

Read by `/gatekit-verify` Step 3, only when the contract run left items a
command cannot decide. It covers how the reviewer is spawned and the exact
brief it is given, including the screenshot judgement and the `-visual`
verdict.

## Spawn one read-only reviewer

Spawn one Agent. Its prompt **must** contain this fence verbatim — the spawn
gate parses it as JSON and denies the spawn without it:

````
```gatekit-scope
{"write_scope": "read-only", "stop_when": "every listed item has a verdict", "tools": ["Read", "Grep", "Glob", "Bash"]}
```
````

Put the list from Step 3 in the prompt: each screenshot's criterion id and
image path, and each check from `spec/05-gate.md` quoted as written. The
reviewer gets these items and nothing else to decide.

The rest of the prompt says, in `output_lang`:

- You are the reviewer. You did not write this code and you must not change it.
- Do not run the completion contract. The command criteria are already
  decided; you are asked only about the items listed here.
- For each check quoted from `spec/05-gate.md`, carry it out by hand. Record
  what you actually observed, not what should happen.
- Give each item one verdict from `ok / warn / fail / unverified`. An item you
  could not carry out is `unverified`; never round it to either side.
- **For each screenshot in the list** (ADR-0017 decision 9), read that image
  file and judge it:
  does it match the design direction on record (a chosen preset, or a
  pattern in `spec/02-design.md`)? Does it show any pattern listed in
  `.claude/skills/gatekit-verify/assets/design-antipatterns.json`? **Read that
  file rather than working from this sentence** — it is the list, and it
  grows. It covers two kinds of failure: a screen that looks *generic* (an
  unstated gradient hero, one sans-serif for every text role, a page of
  identical cards, emoji standing in for icons, centered-everything), and a
  screen that looks *unfinished* — content locked to a narrow centered
  column while a wide window sits empty either side, blocks stopping short
  and leaving a bare band below, a failed load rendering as real figures
  (`0` with a trend arrow) so an error is indistinguishable from an empty
  result, an "overview" holding only a table, and the loading/empty/error
  states simply absent. The unfinished kind only shows up once something is
  actually rendered, which is why it is judged here and not in review of the
  spec. Report this as its own
  verdict, on a criterion id suffixed `-visual` (e.g.
  `task-one-screenshot-visual`), separate from the capture criterion's own
  `ok`/`fail` — the screenshot existing and the screenshot looking right
  are two different facts. If you cannot open or read the image, that
  verdict is `unverified`, not a silent skip.
- Do not fix anything you find. Report it.
- Reply with the verdict table only. Do not paste command transcripts.

The reviewer writes nothing. `spec/PROGRESS.md` is yours to write in Step 5.

## A different program as the reviewer (opt-in)

A project that has set `verify.evaluator` to an enabled backend name in
`.gatekit/config.json` runs the same brief through that program instead of a
subagent: write the bullet list above to `.gatekit/evaluator-prompt.md`, then

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs evaluate --prompt .gatekit/evaluator-prompt.md
```

`evaluate` always uses the backend's read-only arguments. `failed` or
`timeout` means every listed item is `unverified`, never a pass. A backend
that cannot read image files cannot judge a screenshot: treat its `-visual`
verdicts as `unverified`. Nothing is configured this way by default; the
`evaluator` field of this command's output names the reviewer (`agent` unless
the project chose otherwise):

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py workers list --json
```
