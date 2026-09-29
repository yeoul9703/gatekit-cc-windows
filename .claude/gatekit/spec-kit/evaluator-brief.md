# Running the independent evaluator

Read by `/gatekit:verify` Step 2. It covers who grades, how each
evaluator backend is launched, and the exact brief the evaluator is
given — including the screenshot judgement and the `-visual` verdict.

## Step 2 — run the evaluator

Read who grades — the `evaluator` field of:

```
".claude/gatekit/bin/gatekit" workers list --json
```

Unless the user set one explicitly, this resolves to an enabled backend whose
name differs from the host, so the grader is not the model that wrote the code
(ADR-0013). When no such backend exists it falls back to `agent` and the JSON
carries `evaluator_warning` — **report that warning to the user**: it means the
producer is grading itself, which is what this command exists to prevent. There
is no second backend configured by default; a project that wants one adds it
to `.gatekit/config.json`'s `worker.backends` (see `docs/USAGE.md`).

**If the evaluator is a backend name**, the grader is a separate CLI, a
different model, running read-only against source (`write.py` refuses inside
its session either way). Write the bullet list below (from "You
are the evaluator" onward, in `output_lang`, leaving out the one bullet that
starts "Record the result under" — a CLI evaluator cannot write) to
`.gatekit/evaluator-prompt.md`, then run:

```
".claude/gatekit/bin/gatekit" jobs evaluate --prompt .gatekit/evaluator-prompt.md --lang <output_lang>
```

`evaluate` always runs the backend's read-only sandbox — the write gate is the
real protection, so the evaluator never gets a writable session.

It prints the evaluator's reply tail (the verdict table) and its state.
`failed` or `timeout` means the evaluator did not finish; that is
`unverified` for every criterion, never a pass. Then continue at Step 3 and
write `spec/PROGRESS.md` yourself in Step 5.

**Screenshot judging (decision 9) depends on the evaluator backend actually
being able to read an image file**, which not every CLI backend supports
the same way an `agent` evaluator (a multimodal model reading via `Read`)
does. If the configured backend's documentation does not confirm image
input, treat every `-visual` verdict from it as `unverified` rather than
trusting a text-only guess about an image it could not actually see.

**If the evaluator is `agent`**, spawn one Agent. Its prompt **must** contain
this fence verbatim — the spawn gate parses it as JSON and denies the spawn
without it:

````
```gatekit-scope
{"write_scope": "read-only", "stop_when": "every criterion in .gatekit/contract.json and every E2E step in spec/05-gate.md has a verdict", "tools": ["Read", "Grep", "Glob", "Bash"]}
```
````

The rest of the evaluator's prompt says, in `output_lang`:

- You are the evaluator. You did not write this code and you must not change it.
- Run `".claude/gatekit/bin/gatekit" contract run --json` from the project root.
- Read `spec/05-gate.md` and carry out every E2E step it describes by hand,
  in order. Record what you actually observed, not what should happen.
- For each criterion and each E2E step, give one verdict from
  `ok / warn / fail / unverified`. A step you could not run is `unverified`;
  never round it to either side.
- **For each screenshot criterion that came back `ok`** (ADR-0017 decision
  9 — its `artifacts` entry is a `spec/design/build-<task-id>.png`), read
  that image file and judge it, in addition to the criterion's own pass:
  does it match the design direction on record (a chosen preset, or a
  pattern in `spec/02-design.md`)? Does it show any pattern listed in
  `.claude/gatekit/spec-kit/design-antipatterns.json`? **Read that
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
- Record the result under the **last-verification heading that already exists**
  in `spec/PROGRESS.md` (`## 마지막 검증` in Korean, `## Last verification` in
  English). Do not add a heading in another language — `spec validate` treats
  that as cross-language residue and fails. If the file or the heading is
  missing, copy
  `.claude/gatekit/spec-kit/templates/<output_lang>/PROGRESS.md` first,
  filling its YAML frontmatter block (`title`/`date`/`status`) along with the
  rest of the placeholders.
  Write the timestamp, the aggregate verdict, and one line per criterion and per
  E2E step. This file is the one exception to read-only; nothing else may be
  written.
- Reply with the verdict table only. Do not paste command transcripts.

