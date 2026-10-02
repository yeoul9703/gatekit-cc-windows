# ADR-0017: A branch floor for discover/interview, and a verdict gate before promotion

Status: accepted 2026-09-19, extended 2026-09-20/21/24 with decisions 7–24
found during real use on `gk-todo2`, `gk-todo3`, and `gk-todo4` (decision 22
from reading `gk-todo4`'s completed, end-to-end run; decisions 23–24 from
the owner's review of that same run's PRD quality — 23 was superseded by
24 the same day, in the same review conversation, before either shipped).
All 1091 plugin tests pass — decisions 13 through 24 are prompt/template-only changes with no
new spec.py logic, so the count is unchanged from decision 12. Implementation
notes on decisions this document left underspecified:

- **Decision 5's "blocking (y/n) column"** was implemented as **two**
  trailing columns, `Blocking` and `Confirmed`, not one. The template's own
  prose rule ("when confirmed, replace the basis with the confirmed fact")
  cannot be checked mechanically — there is no way for a validator to tell
  "this basis cell was rewritten to a confirmed fact" from "this basis cell
  always read this" by pattern-matching text. A second explicit `Confirmed`
  column makes both facts machine-checkable. See `spec.py`'s
  `_blocking_unconfirmed_rows` and its docstring.
- **The `[non-ui]` marker** (decisions 3 and 4's exemption for CLI/library
  projects) is a literal string in `01-prd.md`'s Non-goals section, checked
  by regex rather than by scanning Features for UI-shaped keywords — a
  keyword scan would be exactly the kind of prose-based guess a code gate
  must not make. Default is UI-bearing (the check fires unless the marker is
  present), on the reasoning that most specs have a UI and a false negative
  (wrongly exempting a UI project) is worse than the one-line cost of
  declaring `[non-ui]` explicitly.
- **The prototype confirmation record** (decision 4) is the prose line
  `Prototype confirmed <date>` / `프로토타입 확정 <date>` appended to
  `02-screens.md`, not a hash-anchored approval like `05-gate.md`'s
  (`approval.py`). The live prototype is revised in a loop until confirmed,
  so — unlike the gate file's one-shot approve/expire shape — there is no
  single moment before the last accepted revision to pin a hash to.
- **Decision 1's floor waiver** is the top-level fence field
  `pain_floor_waived: true`, mirroring the existing `unpassed` list's role
  for the six deepening gates: an explicit, checkable record that the user
  chose to stop, rather than silence being read as compliance.
- **Decision 2's verdict enum** has no `connect` case (rejected in the ADR
  body already) and `unknown` is deliberately absent from the blocking set —
  both enforced in `spec.py`'s `PAIN_VERDICTS` / `_PAIN_VERDICTS_BLOCKING`
  with the "why blocking unknown would be worse" reasoning kept as a code
  comment, not only here, so it survives independent of this document.
- **Decision 9's screenshot criterion is a real `subprocess.run`-able
  script (`npx playwright test` or whatever E2E runner
  `03-architecture.md` already names), never an MCP tool call.** The first
  design draft assumed Claude-in-Chrome tools could serve as a criterion's
  `argv`; checking `contract.py`'s actual execution path
  (`subprocess.run(list(crit["argv"]), ...)`) showed that is impossible —
  MCP tools exist only inside an interactive agent session. `contract.py`'s
  existing `OSError`/timeout handling already turns "the capture script
  cannot even launch" into `unverified` for free, and its existing
  `artifacts` check already turns "the script ran but produced no file"
  into `fail` — decision 9 needed no new verdict-mapping logic in
  `contract.py` itself, only new criteria in `gate.md`'s derivation step
  that use machinery already there.
- **The "AI-made defaults" list (decision 9) is a new data file,
  `design-antipatterns.json`, committed immediately** rather
  than held to the same "must be observed in a real build first" rule
  `presets/design/README.md` states for design *presets*. The two are not
  the same kind of claim: a preset asserts "these values work," which is
  unverified until a build proves it; this list asserts "these patterns
  look generic," which does not need a gatekit build to be true — it is
  seeded from the reviewed conversation's own observations of existing
  tools' output, with one entry (`AP6`, no styling at all) added from
  `gk-todo`'s own real, observed failure. It grows the same way presets do
  going forward: a new trial names a new pattern, it gets added with its
  evidence tag.
- **2026-09-29: five rows added (`AP7`-`AP11`) under a third evidence
  prefix, `reported:`.** They came from a design review done in another
  project of its own agent-built screens, not from a gatekit trial, so
  tagging them `observed:` would claim this repo rendered something it
  never rendered — hence the separate prefix, and a test that keeps the
  three apart. The rows themselves are a different *kind* of failure from
  `AP1`-`AP5`: those describe a screen that looks generic, these describe
  one that looks **unfinished** — a narrow centered column leaving a wide
  window empty at both sides, blocks stopping short above a bare band, an
  error state rendering `0` with a trend arrow so a failed load is
  indistinguishable from a real zero, an "overview" that is only a table,
  and loading/empty/error states simply not built. The reason they belong
  in *this* file rather than in spec review is that none of them is visible
  in the spec: each one is a property of what actually rendered, which is
  exactly what the `-visual` verdict reads. No code was taken from that
  project — these are judgement criteria, not an implementation, and the
  clean-room rule in `CLAUDE.md` stands.
- **Decision 10's three seed presets tag their `source` as `seed:<origin>`,
  a new convention this preset system did not previously need** (existing
  code only ever wrote `preset:<name>` for an *observed* preset's origin
  after a merge). `shadcn-neutral.json`'s color values are shadcn/ui's own
  documented neutral-base defaults, not the original design of the owner's own project they were read
  from — that project was checked (`src/components/` has no
  components beyond unmodified shadcn primitives) and found to be an
  uncustomized shadcn/ui install, so only its *structure* (HSL custom
  properties, base/foreground pairs, single-radius derivation, `.dark`
  class redefinition) is cited as coming from it; the values themselves are
  cited as `seed:shadcn-ui` directly, not laundered through the project
  that happened to have them. `editorial-warm.json` and `tool-dense.json`
  are not lifted from any single named project — they cite general,
  widely-documented conventions (serif/sans pairing, dense-tool spacing)
  as their seed origin, since no single canonical source exists to name.

Origin: real-world trial `gk-trial2` (a Next.js Socratic-questioning app for
church youth education). The owner's verdict on the delivered spec, read
directly from the artifacts, not just reported dissatisfaction:

> "discovery 단계에서는 충분히 질문도 안하고, interview에서는 어떻게 만들건지
> 물어보지도 않고, 중간에 mockup도 안보여주고, 혼자 기계적으로만 테스트
> 완료했다고 하고, 최종 결론은 이렇게 오랜 기다림 뒤에 전혀 다른게 만들어져
> 있는데 이게 좋은 툴이 될 수 있을까?"

And the target shape:

> "discovery에서 개선과제 도출을 위한 요소를 뽑아낼 만큼 충분한 대화가
> 필요하고, interview단계에서는 그걸 구현하기 위한 구체적인 필요조건을
> 뽑아냈으면 했고... 스텝 바이 스텝으로 진행을 하면서 사람과 인터렉션을
> 하고 개선해 가는 프로세스가 아니라 기계적으로 지 맘대로 해 놓고, 기다림
> 끝에 보여지는 결과는 엉망이잖아"

## Context

### What actually happened in `gk-trial2`, read from its own spec files

`spec/00-discovery.md` (67 lines) is not shallow. All six deepening gates
(real user, current way, frequency, cause, failed attempts — `/gatekit:discover`
Step 3) are filled, the why-chain runs five links deep, two failed attempts
are recorded. Discovery worked as designed.

The break is downstream, in two places:

**Assumption 4 of `spec/01-prd.md`**: "일곱 기능은 사용자가 제시한 4단계를
그대로 옮긴 것이다 — F1·F3이 '스스로질문', F2가 '다양한 방향으로의 사고',
F5가 '판단', F6이 '실천적 책임'에 대응한다. **각 단계를 어떤 화면 동작으로
옮길지는 인터뷰어가 정했고 사용자가 확인하지 않았다.**" This is the
interview command doing exactly what its own spec allows: Step 5 caps
`AskUserQuestion` at two calls and restricts them to "decisions the user
alone owns" — but sets no floor. Nothing in `interview.md` requires the
four-stage-to-seven-feature mapping to be one of those two questions, or any
question at all. The interviewer is free to decide silently, and did.

**`spec/02-screens.md` never existed.** `/gatekit:mockup` was never run.
`spec/tasks.md` reads `02-screens.md` "if it exists" (`tasks.md` Step 1) —
absence is not an error, only `01-prd.md`'s absence stops the pipeline. So
`/gatekit:tasks` proceeded straight from a PRD with an unconfirmed feature
mapping to a design nobody had seen, and Assumption 13 already named the
resulting risk while accepting it anyway: "목표가 5개로 늘었다... 어느
단계가 효과를 냈는지 분리 측정할 수 없고, 첫 판이 커져 민수에게 써보는
시점이 늦어진다."

Two independent gaps, not one:

1. **No floor on how much must be asked** before a command is allowed to
   draft and move on. `interview.md` Step 5 has a ceiling (2 calls) but no
   minimum, and nothing forces the feature-to-screen mapping specifically to
   be user-confirmed rather than interviewer-decided.
2. **No enforcement that a design source exists** before tasks are cut.
   `heading-map.json`'s `absent_ok` treats `02-screens.md` like `02-design.md`
   and `00-discovery.md` — always optional — when the owner's stated model
   (Lovable-style: PRD → design pattern → mockup → confirmed prototype →
   *then* the design doc exists) makes the screen spec a required gate for
   any build with a UI.

### Three related systems the owner asked to compare against

**`grill-me`** (45 lines): a
PreToolUse/Stop hook pair blocks file writes until at least 20 (30 for
complex work) "distinct decision branches" are resolved. The count is done
by a separate deterministic script (`grill_gate.py`, 766 lines) — the
producer (the LLM asking questions) is never trusted to self-report that it
asked enough. Three roles stay separate: producer, evaluator (the counting
script), gatekeeper (the hook that denies the write).

**`oh-my-claudecode:deep-interview`** (802 lines): an ambiguity score
(`1 - (goal×0.40 + constraints×0.30 + criteria×0.30)` for greenfield work)
decides when to stop asking, with a one-time topology check at Round 0 and
challenge agents (Contrarian/Simplifier/Ontologist) injected at rounds
4/6/8. This is a *depth* instrument for a single, already-scoped project —
it does not branch into multiple candidate problems.

**`ai-dev-pm`** (the owner's own internal project): the piece most relevant here, because it is
structured as exactly the three stages the owner described directly —
discovery → verdict/selection → deep interview — as actual running code:

- `discovery.service.ts`'s `extractUseCases()` pulls **multiple** candidate
  use cases out of one discovery interview automatically, each carrying
  `sourceSeqs` back to the answers it came from. Discovery is not narrowed
  to one problem before the next stage; it fans out.
- `discovery-verdict.ts` gives each use case a verdict —
  `ELIMINATE | CONNECT | REUSE | BUILD | UNKNOWN` — with **`verdictSuggested`
  (the model's proposal) kept in a separate field from `verdict` (the
  human's confirmed choice, `verdictBy: null` until someone sets it)**.
  `blocksPromote()` refuses to let `ELIMINATE` or `REUSE` verdicts become
  projects; `UNKNOWN` is deliberately *not* blocking, with the reasoning
  spelled out in comments: blocking on "don't know yet" would reward staying
  undecided.
- `promote()` is a server-side gate, not a prompt convention: it re-queries
  the picked use cases' stored verdicts and throws `VALIDATION_FAILED` if
  any of them is `ELIMINATE`/`REUSE`, naming which ones. A person picks from
  the fanned-out candidates; the server, not the LLM, enforces which picks
  are allowed to become a project.
- Once promoted, `wizard.service.ts` + `interview-guide.ts` run the
  *implementation* interview in three stages (`BASIC → DEEP → ADVANCED`),
  each with both a `minAnswers` floor and a `maxAnswers` ceiling computed
  server-side (`canAdvanceStage`), not asserted by the LLM:

  ```typescript
  export function canAdvanceStage(stage, answeredCount, stageComplete): boolean {
    if (answeredCount >= WIZARD_MAX_ANSWERS[stage]) return true;
    return stageComplete && answeredCount >= WIZARD_MIN_ANSWERS[stage];
  }
  ```

  The comment on why this exists names the exact failure this ADR is about:
  measured over 28 real calls, the model's own `stageComplete` claim was
  `false` every single time — an LLM alone never volunteers "I've asked
  enough." The ceiling exists so an under-confident model doesn't loop
  forever; the floor exists so an over-confident one doesn't skip ahead.
  `DEEP`'s coverage is split into five named axes in code (edge cases,
  constraints, priority, screen tone, **data cardinality**) specifically
  because a merged axis ("data structure") let a single vague question
  satisfy it without ever surfacing the cardinality question — the exact
  shape of `gk-trial2`'s Assumption 4 (a mapping decided without ever being
  posed as a question).

**A fourth, smaller data point** (the owner's own `cys-terminal` project,
checked for reusable principle, not code): `javis_verdict.py` rejects any
`score`/`grade`/`rating` key anywhere in a verdict object, recursively,
because "a score channel is reward-hackable" — verdicts must be one of a
small enum with required evidence refs, never a number. This is the same
posture gatekit's own CLAUDE.md already states (`verdict words: ok / warn /
fail / unverified. Never round unverified to either side.`) — no new
mechanism to adopt, but a confirmation that the verdict field this ADR adds
must stay an enum, never a score.

### Why deep-interview's ambiguity score does not fit here

Ambiguity scoring answers "is this one project's spec clear enough yet,"
which presupposes the project is already chosen. gatekit's actual gap is
upstream of that: nothing forces *multiple* candidate improvements to be
drafted and chosen among before one is scoped at all. Grafting an ambiguity
score onto `/gatekit:discover` would still only deepen the single pain
already selected in Step 2 — it would not open the branching `ai-dev-pm`'s
`extractUseCases()` does. A branch-count floor (grill-me's mechanism, not
its code) is the right shape for *this* gap; a per-project depth score is a
separate, already-solved concern gatekit's per-gate three-question budget
already covers reasonably.

### Two decisions already made by the owner, ahead of this document

Asked directly:

- **When no design source exists for a genuinely new idea** (nothing to
  read for `/gatekit:mockup`): "추천 스타일 새 고르게 하고 진행" — offer a
  recommended style, let the user pick, then proceed. This is the resolution
  for the "must a design source be mandatory even for greenfield work"
  question below.
- **When a blocking assumption in the ledger is unconfirmed**: "완전히
  막기 (fail)" — block outright, not merely warn. This settles backlog item
  1's open question in favor of the strict option.
- **When to ask whether a design source exists at all**: "`/gatekit:mockup`
  진입 직후, 매번" — every `/gatekit:mockup` run asks this explicitly, not
  only when `$ARGUMENTS` happens to be empty. Today's command infers "no
  source" purely from an empty argument and silently free-designs the
  screens (`mockup.md` Step 2's "extract; do not imagine" only fires once a
  branch is already picked) — nobody is ever asked to actively choose
  between "I have something to show you" and "design something new." The
  choice itself needs to be a forced step, not an inference from whether the
  user happened to pass an argument.

## Decision

### 1. A branch floor on `/gatekit:discover`'s pain collection

Step 2 of `discover.md` currently collects "at most three" recent pains and
narrows to one by computed monthly cost before Step 3 ever runs. Change the
floor, not the ceiling: **at least three distinct pains must be surfaced
before ranking**, using the same climb-one-rung fallback Step 2 already has
(yesterday's longest task → a repeated task → a named tool → a colleague's
complaint → a known-but-skipped task) to fill in when the user runs out on
their own. A user who names a pain immediately gets asked, once, "다른 것도
있나요?" up to the floor of three or until they give a stop signal — never
past a stop signal, per `policy/questioning.md`.

This is deliberately a **count**, decided the same way `grill-me` decides
its 20/30 branch count and `WIZARD_MAX_ANSWERS` decides interview
stage caps: a number the command enforces mechanically, not a judgement the
interviewing agent is trusted to make about whether it has asked "enough."
Self-reported sufficiency is exactly what `ai-dev-pm`'s 28-call measurement
showed does not work.

Three, not `grill-me`'s twenty, because discovery pains and grill-me's
decision branches are not the same unit — a pain takes the six-gate
deep-dive of `discover.md` Step 3 to fill in, so three pains already
represents substantially more dialogue than twenty single-sentence branch
resolutions. The number is stated, not measured against a real run yet, the
same honesty ADR-0016 required of its own 75% threshold; it is revisited
once a real discovery session under this rule is observed.

### 2. A verdict field per pain, server-checked before scoping

Each collected pain, once written into `spec/00-discovery.md`'s pain list,
gets a `verdict` — one of `build | reuse | eliminate | unknown` — following
`ai-dev-pm`'s enum shape adapted to gatekit's one-pipeline-per-run scope
(gatekit has no `connect` case: there is no adjacent system to wire into
inside a single spec pipeline).

- The interviewer proposes a verdict for each pain (`verdict_suggested`,
  with one sentence why) after asking the four `ai-dev-pm`-derived questions
  once per pain: does a real recipient already use what this would produce;
  does the input already exist in a system instead of being retyped by
  hand; does an existing tool already do this; does it need human judgement
  this pipeline can't automate away.
- The user picks which pain to carry forward via the existing
  `AskUserQuestion` ranking step (Step 2 already shows the ranking and asks
  which one to build; this ADR adds the verdict as a column in that same
  question, not a new call).
- **`spec validate` refuses to let `/gatekit:interview` proceed past Step 1
  if the chosen pain's confirmed verdict is `eliminate` or `reuse`.** This
  mirrors `promote()`'s `VALIDATION_FAILED` — a code-level refusal, not a
  prompt suggestion — and `unknown` is explicitly **not** blocking, for the
  same reason `ai-dev-pm`'s comment gives: blocking on "not sure yet" would
  make staying undecided the safer choice.
- `verdict_suggested` and `verdict` (the user's confirmed choice) are
  separate fields in the discovery fence, never merged — so a future
  `spec validate` finding can tell "the interviewer guessed this" from "the
  user actually decided this" without re-reading prose. This directly
  answers Assumption 4's failure mode: a mapping decision the interviewer
  made would now show up as `verdict_suggested` with no matching `verdict`,
  which is a discoverable, checkable gap instead of a silent one.

The verdict stays an enum with a required one-line justification, never a
numeric score — confirmed as the right posture by `javis_verdict.py`'s
score-rejection above and already gatekit's own stated rule.

### 3. `spec/02-screens.md` becomes a required gate before `/gatekit:tasks`, and `/gatekit:mockup` forces the source-or-new choice every run

`heading-map.json`'s `absent_ok` currently lists `02-screens.md` alongside
`00-discovery.md` and `02-design.md` — always optional. Split it: a project
whose `01-prd.md` features imply any user-facing screen (i.e., not a
pure-CLI or pure-library spec — detected the same way `tasks.md` Step 2
already distinguishes vertical slices with "the surface a user touches")
requires `02-screens.md` to exist before `/gatekit:tasks` Step 1 proceeds.
Its absence is a hard stop with the same shape `01-prd.md`'s absence
already gets, not a silent `warn`.

**The choice between "I have a design source" and "design something new"
becomes an explicit, forced step, not an inference from whether
`$ARGUMENTS` happened to be empty.** Today's `mockup.md` Step 2 branches
silently on argument presence — an empty argument is read as permission to
free-design, and nobody actively decided that. New Step 1.5, run on every
invocation regardless of `$ARGUMENTS`:

- If `$ARGUMENTS` already names a Figma URL, HTML files, or screenshot
  paths, confirm briefly ("이 소스로 진행할까요, 아니면 새로 디자인을
  받을까요?") rather than skipping the question outright — a user who pasted
  a stale or wrong link should still get the chance to say "actually, design
  something new."
- If `$ARGUMENTS` is empty, ask directly, as one `AskUserQuestion`: does a
  design source exist somewhere (Figma link, screenshots, an HTML export,
  a live site to point at) that just was not attached, or should gatekit
  propose something new. This costs one question on every mockup run, which
  is deliberate — the point is that "no source" becomes something the user
  said, not something the command assumed from silence.
- Answering "propose something new" routes to the recommended-style
  fallback below. Answering "I have a source" and then not providing one in
  the same turn is treated as a stop signal would be under
  `policy/questioning.md` — ask once more for the path or link, and only
  fall through to the new-design branch if the user says there truly is
  none.

For the "design something new" branch — the owner's decision above —
`/gatekit:mockup` offers a small set of recommended styles (drawing from
`spec/tokens.json`'s existing preset mechanism, `design merge-preset`) as an
`AskUserQuestion`, lets the user pick one, and proceeds to draw the preview
from that. This reuses the design-preview machinery ADR-0011 already built
(`preview-<name>.html`, the "approximate pattern" banner, corrections
written into `02-screens.md`) — it only adds a starting point before the
preview when there was nothing to extract, rather than skipping the screen
spec entirely.

### 4. A live, editable HTML prototype gate between design and `/gatekit:tasks` — never skip straight from decision to build

This is the owner's most direct restatement of the original complaint:
"기다림 끝에 보여지는 결과는 엉망" — the damage happens when the distance
between a design decision and the first thing the user actually *sees*
spans the entire build. ADR-0011's existing preview
(`preview-<name>.html`, drawn once, corrections folded back into
`02-screens.md` as text) narrows that gap but does not close it: the
artifact is a static picture, and feedback flows through prose ("2번 화면
버튼 색 바꿔줘") rather than through the user touching the thing itself.

**Once `01-prd.md` and `02-screens.md`/`02-design.md` exist, `/gatekit:tasks`
gets a new required precondition: a live HTML/CSS prototype, built from
`spec/tokens.json` and the screen spec, that the user actually opens,
clicks through, and revises — in a loop — before a single line of
application code is written.** Concretely:

- After Step 2's screen/design extraction (or the new-design branch in
  decision 3), `/gatekit:mockup` builds `spec/design/prototype-<name>.html`
  as real, clickable HTML/CSS — every named screen `S<n>` reachable through
  its own recorded flow, using the same tokens `02-design.md` and
  `tokens.json` already extracted, not just a still image. This is still
  frontend-only and disconnected from any backend (no build has started —
  `/gatekit:build` has not run), the same boundary ADR-0011 already drew,
  now expressed as interactive markup instead of a picture.
- The prototype is handed to the user to actually open (a file path today;
  a Claude-in-Chrome-driven walkthrough where that tool is available).
  Feedback comes back as concrete change requests against a *specific*
  screen and element, not free-form prose about the whole app — the same
  discipline `policy/questioning.md` already asks of every other step:
  research and show, don't interrogate.
- Each revision is applied directly to the HTML/CSS and to `02-screens.md`
  (the source of truth `tasks.md` reads from — ADR-0011 already wired this
  path for the static preview; nothing new needed there), and the prototype
  is handed back. This repeats until the user confirms explicitly — a new
  `AskUserQuestion` ("이대로 확정할까요?" / "더 수정할 부분이 있어요") — not
  until the pipeline decides the prototype looks finished.
- **`/gatekit:tasks` Step 1 now also requires this confirmation to be
  recorded** (a line in `02-screens.md`, e.g. `프로토타입 확정 <date>`,
  parallel to how `05-gate.md`'s approval hash already gates `/gatekit:build`
  in `approve check`). Its absence blocks Step 1 the same way a missing
  `02-screens.md` does under decision 3 — the two checks compose: no screen
  spec, no prototype gate to pass; a screen spec with no confirmed
  prototype, still blocked.

This is deliberately **not** the same thing as backlog item 11b's
explicitly-rejected per-screen approval convention — that was rejected in
2026-09-17 for adding process ("자꾸 프로세스를 추가하지 마") on top of a
*static* preview the owner had not yet complained about. The complaint this
ADR responds to is different and newer: the static preview shipped, and the
distance between "preview shown once" and "code appears at the end" was
still large enough to produce a result the owner called "엉망." A single
whole-prototype confirmation (not one row per screen) is the smaller
version of that gate — it blocks on one signed-off round-trip, not N.

### 5. Blocking assumptions fail the gate, not just warn

Per the owner's second decision: the assumption ledger in `01-prd.md` gains
a `blocking (y/n)` column (already backlog item 1's proposal, now decided).
`spec validate` treats an unconfirmed row marked blocking as a `fail`, not a
`warn`, and `/gatekit:gate`'s Step 4 (`spec validate --json` must not be
`fail`) already refuses to proceed on a `fail` — so this closes backlog
item 1 by picking the strict branch of its own open question, no new gate
code beyond the severity change and the column itself.

### 6. Every command's final report ends with an explicit continue-or-extend question, never a silent stop

The pattern across `discover.md`, `interview.md`, `mockup.md`, and
`tasks.md` today is identical: the last step is titled "report," lists what
was written, names the next command in prose ("Next command:
`/gatekit:tasks`"), and the command's instructions end there. Nothing asks
the user anything — the session sits idle until the user remembers to type
the next slash command themselves. This is a smaller instance of the same
root complaint as the rest of this ADR: the pipeline finishes a step and
"기계적으로" waits, instead of interacting with the person who is supposed
to be steering it.

**Every pipeline command's final report step gains one closing
`AskUserQuestion`** (or, for `discover.md`, plain chat per that command's
own rule that it never calls `AskUserQuestion` — see below), asked after
the existing report content, with at minimum these options:

- proceed to the named next command now (the command actually invokes it,
  rather than telling the user to type it),
- do more work at the current step (revise a named section, add another
  pain/screen/task/criterion — whatever this step's own vocabulary is),
- stop here and let the user decide later.

This is not a new gate that blocks anything — it is the missing symmetric
half of `policy/questioning.md`'s stop-signal handling: that policy already
says what to do when a user wants to stop *mid*-step, but nothing currently
prompts at the natural end of a step. Concretely, per command:

- `discover.md` Step 5: since this command's own Step 0 rule excludes it
  from `AskUserQuestion` entirely ("this pipeline never calls
  `AskUserQuestion`. Every question is plain chat."), the closing question
  is plain chat text, matching the rest of the command's own questioning
  style, not a picker.
- `interview.md` Step 7, `mockup.md` Step 8, `tasks.md` Step 7: a genuine
  `AskUserQuestion`, since these commands already use the tool elsewhere in
  the same run and it does not cost a new budget line — `policy/
  questioning.md`'s budget governs *information-gathering* questions during
  drafting, not a closing routing choice after the draft already validated.
- `/gatekit:gate` and `/gatekit:build`/`/gatekit:verify` are **out of scope
  for this change** — `gate` already ends on an explicit `AskUserQuestion`
  approval (Step 6), and `build`/`verify` end on a pass/fail report where
  "proceed automatically" is exactly the behavior ADR-0013 already
  decided against (the host session must not silently keep going past a
  build result). Extending the closing-question pattern there would
  contradict decisions already made; this decision only touches the four
  planning-stage commands that currently end in bare prose.

Choosing "do more work" loops back into the current command rather than
exiting — e.g., `mockup.md` answering "더 수정할 부분이 있어요" returns to
the prototype revision loop decision 4 already added, not to a fresh run of
Step 1.

### 7. Drop the per-gate question ceiling; a gate closes on context saturation, not a count

**Superseded by decision 12.** This decision kept the six named deepening
gates and their fixed one-at-a-time order, and only changed how many
questions each gate could take. Real use after this shipped showed the
gates *themselves* — not just their question count — were the problem: a
named slot, filled in a fixed sequence, with progress shown to the user, is
a scripted interrogation regardless of how deep each slot is allowed to go.
Decision 12 removes the gates as a structure entirely. This section is kept
for the record of what was tried and why it was not enough, not as current
behavior — see decision 12 for what `discover.md` actually does now.

Found only once decisions 1–6 were run for real, against a fresh project
(`gk-todo2`): decision 1's branch floor fixed *how many* pains get surfaced,
but did nothing about *how deep* each one, or each of `discover.md`'s six
deepening gates (user, current way, frequency, minutes, why-chain, failed
attempts), gets probed. `discover.md`'s existing "per-gate budget: three
questions" rule is a **ceiling**, not a floor — and worse, it is read as
satisfied by a single shallow answer well under three questions, because
nothing checks depth, only presence. One word ("바빠서요") answering "why"
once closes the gate exactly as thoroughly as three real attempts would. The
result, reported directly: "왜 이렇게 급해 사용자는 인터뷰를 원하는데" — a
gate that looks complete after one thin exchange, with no mechanism asking
whether the exchange was thin.

This is not a new gate; it is removing the wrong one. **Delete the
three-question ceiling per gate entirely.** A deepening gate does not close
after N questions or after any single answer — it closes when the
conversation's own context starts to circle: the user restates something
already said in different words, a new question would ask about ground the
last two exchanges already covered, or the answers stop adding anything a
`why_chain` link or a `current_way` step does not already capture. This is
the same signal `discover.md`'s existing paraphrase-detection already uses
for `why_chain` specifically (`_RESTATEMENT_OVERLAP` in `spec.py`, word-set
overlap ≥ 0.6 counts as a restatement, not a new link) — decision 7 makes
that the *general* closing condition for every gate, not only the one gate
that already had it.

Concretely, per gate: keep asking, varying the angle, until either (a) the
next planned question's likely answer already appears, in substance, in what
was said in the current gate's last exchange or two — the conversational
equivalent of the word-overlap check — or (b) a stop signal
(`policy/questioning.md`) arrives, which always wins immediately regardless
of how little has been asked. There is deliberately no number to replace the
deleted "three": a gate about a single well-understood fact (a named person,
for `user`) saturates in one exchange; a gate about a causal chain
(`why_chain`) may take five. Bounding it by count was exactly the mistake —
the point of this decision is that gate depth is judged by whether the
dialogue is still producing new information, the way `deep-interview`'s
Round-4/6/8 challenge agents keep probing a topic only while it keeps
yielding new ground, never by a fixed round count. The owner's own framing,
stated directly while this gap was found: "질문 상한은 없애고 대화의 맥락을
보면서 충분히 도출해 내고 그 대화를 근거로 프로젝트 뭘 진행할지 뽑아내는게
목적" — the goal was never "fill six slots," it is a conversation substantial
enough to ground a real decision about what to build.

`unpassed` keeps its existing role for a gate that never produces anything
usable even without a count limit (nothing to circle back to because nothing
was ever said) — decision 7 changes *when* a gate is judged done, not the
fallback for a gate that is genuinely empty.

**The same removal applies to `interview.md`'s feature-to-screen mapping
check.** Decision 2's `verdict_suggested`/`verdict` split already stops a
pain's build/reuse/eliminate judgement from being decided silently; the
same silent-decision risk exists for how each PRD feature (`F<n>`) maps to a
screen or behavior — gk-trial2's Assumption 4 was exactly this, and a count
limit on `interview.md`'s own questions would reproduce decision 7's
`discover.md` mistake in a new place. Each feature-to-screen mapping is
confirmed with the user through however many exchanges it takes to stop
producing new information, using the same saturation signal, rather than
being folded into interview's existing two-`AskUserQuestion` ceiling
(`policy/questioning.md`'s budget stays for genuinely separate decisions —
this is about not letting the ceiling silently swallow a mapping
confirmation that needed its own room).

### 8. A named product or solution is a domain hint, not nothing — `discover.md` must search inside it before broadening

Found immediately after decision 7 was checked for real, on the same
`gk-todo2` session: the user opened with "할 일 관리 앱" ("a todo app"), a
solution shape with no named user or pain. Step 1's routing already
correctly sent this to Step 2 rather than treating it as a chosen problem —
but Step 2 then discarded the hint entirely, asking about "any annoyance in
the last two weeks" with no connection to what the user had just said. The
second pain-collection question jumped to an unrelated example ("그 회의
관련 불편 말고... 같은 정보를 두 번 입력했다거나") that had nothing to do
with managing tasks, and the user noticed immediately: "제목을 할일 관리
앱으로 하고 시작했는데 해당 주제에 대해서는 더이상 안물어보고 다른 질문으로
넘어가네." A user who names a product is not naming nothing — they are
pointing at a domain, and discarding that pointer to ask about a random
unrelated topic wastes the one piece of direction they already gave.

**`discover.md` Step 1 now carries a named product/solution forward as an
explicit domain hint** (distinct from "one real user and their pain," which
still routes straight to Step 3) rather than treating it identically to
empty input. **Step 2 searches inside that domain first**: two questions
about pains specific to it (for "a todo app" — tracking tasks, deadlines,
priority, telling someone else something is done) before broadening. Only
once the domain has been tried and still leaves the floor of three unmet
does Step 2 broaden to unrelated topics — and it says so in one line when it
does, rather than silently pivoting the way the observed session did. This
does not relax decision 1's floor (still three pains, still `pain_floor_
waived` for a genuine stop) — it changes *where* Step 2 looks first, so a
user who already pointed somewhere is not made to feel ignored by their own
opening sentence.

### 9. Real-implementation screenshots as build evidence, judged by the verify evaluator — not a second self-critique loop at the prototype stage

Origin: the owner reviewed a separate ChatGPT conversation about why
Lovable's default output looks better than a bare agent's, and asked
whether to adopt it. Most of that conversation's advice does not transfer —
it assumes a fixed frontend stack (Vite+React+Tailwind+shadcn) and a
project-level `CLAUDE.md` gatekit does not generate, both of which conflict
with gatekit being stack-agnostic (`03-architecture.md` derives the stack
per project; this repo's own CLAUDE.md already forbids assuming a
dependency) and with `/gatekit:build` reading design instructions from
`spec/02-design.md`/`tokens.json`, not from a project's own `CLAUDE.md`,
which gatekit does not author.

**Where this belongs was itself wrong on the first pass and is worth
recording.** The first draft of this decision put a self-critique
screenshot loop inside decision 4's *prototype* gate — but the prototype is
static HTML/CSS built only to agree on screens and flow; the real
implementation (in whatever stack `03-architecture.md` names) is written
later, entirely inside `/gatekit:build`, by workers who never touch the
prototype file again. A screenshot loop at the prototype stage checks
markup that gets thrown away, not the thing that ships. Asked directly
where a screenshot check would actually catch drift, the answer is
`/gatekit:build` itself — the same "구현 → 스크린샷 → 자가비평 → 수정" loop
the reviewed conversation describes is about the real implementation step,
not the throwaway agreement artifact.

**Even inside `/gatekit:build`, a self-critique loop was rejected as the
mechanism**, because it does not add anything a human is not already going
to do: the prototype's own revision loop (decision 4, item 3) already puts
a human in the exact position of looking at a rendering and judging it, so
a second round of the model judging its own output before build even starts
would mostly re-litigate a decision a human already gets to make later — and
`/gatekit:build`'s own screenshots (below) get a *real* independent
judgement already, from the verify evaluator, so a worker's self-judgement
of its own screenshot would just be the producer grading itself a second
time, the exact thing `verify.md`'s "Producer ≠ evaluator" line already
exists to prevent.

**The decision, then, is mechanical evidence at build time, judged later by
someone who is not the producer:**

- For any task in `04-tasks.md` whose `write_scope` touches a UI surface
  (the same "the surface a user touches" test `tasks.md` Step 2 already
  uses to cut vertical slices), the task's gate requirements include one
  screenshot of the real, running implementation —
  `spec/design/build-<task-id>.png` — captured after the task's own gates
  pass. **This must be a criterion `argv` `contract.py` can actually
  `subprocess.run`, so it is a standalone script, not an MCP tool call a
  worker session happens to have** — `mcp__claude-in-chrome__*` tools exist
  only inside an interactive agent session and cannot be a criterion's
  `argv`; a script `npx playwright test` (or an equivalent already in the
  project, if `spec/03-architecture.md` names a different E2E runner) can,
  the same way ADR-0013's and ADR-0015's own criteria already run
  `npx playwright test` as a contract criterion today. Where the project
  has no E2E runner set up yet, the task's own gate step (`tasks.md` Step
  4) is responsible for adding one, the same way it already adds the token
  gate for a styling-touching task.
- The screenshot's existence (and that it postdates the task's last source
  change) is a criterion `/gatekit:gate` can derive alongside the task's
  other completion criteria — a UI task whose capture script cannot run at
  all (no browser installed, no E2E runner configured) hits
  `contract.py`'s existing `OSError`/timeout path and comes back
  `unverified` on that criterion automatically, the same fourth state
  ADR-0015 already established for "could not check," never rounded to a
  pass. A UI task whose script *runs* but never produces the file is a
  `fail` on the `artifacts` check (`contract.py`'s existing behavior for a
  declared-but-missing artifact) — the script ran and still did not
  produce evidence, which is a different, worse signal than "could not
  even try."
- **`/gatekit:verify`'s evaluator — already a separate agent that reads but
  does not write (Step 2 of `verify.md`) — looks at each UI task's
  screenshot as part of its existing verdict pass**, checking it against
  the design direction decision 3 established (a chosen preset or an
  extracted `02-design.md` pattern) and against the named defaults list
  below. This is not new machinery: it is one more thing the evaluator that
  already exists looks at, reported as an `ok`/`warn`/`fail`/`unverified`
  verdict on that criterion like any other, never as prose buried in the
  evaluator's free-form reply.

**A named list of generic-AI-output defaults**, checked by the evaluator
against each UI screenshot: a purple-to-blue gradient hero with no stated
reason, a single sans-serif (Inter or similar) used for every text role
with no second face for contrast, a page built entirely from
identically-shaped cards in a row, decorative emoji standing in for icons,
and centered-everything layouts with no deliberate asymmetry. This list is
a starting point, not exhaustive — it lives in a data file (per this
repo's own rule that presets live in data files, not in command prose), so it can grow from real trials the way the presets
themselves already do.

### 10. Ship seed presets now — an empty preset catalog defeats decision 3's greenfield fallback

Found on `gk-todo2` immediately after decision 3 was live: the owner picked
the new-design branch (no Figma/HTML/screenshot source), and the pipeline
had nothing to offer — the design preset folder held only its own
README, empty by design, per the rule stated there ("no preset ships...
until one has been observed in a real build"). The result was a shipped
todo app with a bold `<h1>`, an unstyled native `<input type="datetime-
local">`, and a plain bordered button — the exact defaults decision 9's
antipattern list exists to catch, produced not because a worker chose them
but because there was nothing else to choose. Screenshot, quoted directly:
"default 디자인 요소가 없으니깐 아웃풋 마다 흰 배경에 허접한 글씨, 비뚜러진
콤보박스... 이런 결과가 반복되고 있어." The greenfield branch decision 3
built is real, but a fallback with an empty menu is not a fallback.

This is a chicken-and-egg problem the original preset rule did not
anticipate: a preset needs a real gatekit build to be observed, but no
project reaches a good build without *some* preset to start from, and
`gk-todo`, `gk-todo2`, and every other real trial so far predates decision
3 or ran before any preset existed. The rule, taken literally, guaranteed
its own fallback would stay empty indefinitely.

**Decision, with the owner's explicit permission to change the rule that
caused it: `presets/design/README.md` now recognizes two kinds of preset,
told apart by their `source` tag.**

- **Seed presets** (`"source": ["seed:<origin>"]`) are adopted from an
  established, widely-used design system or component library — not
  invented here — and may be committed immediately, with no gatekit build
  required first. The origin's own track record (shadcn/ui's actual
  defaults, a documented typography convention) is the evidence a fresh
  build cannot yet provide.
- **Observed presets** keep the original rule exactly as it was: merged
  into a real project, built, and only then committed.

**Three seed presets ship now**, covering visibly different directions so
the greenfield `AskUserQuestion` (decision 3) is a real choice, not one
option dressed up as several:

- `shadcn-neutral.json` — the shadcn/ui default token structure itself
  (HSL custom properties, base/foreground color pairs, one `--radius` value
  the rest derive from, `.dark` class token redefinition), extracted from
  the owner's own project as a *structural*
  reference — its actual color values are shadcn's own neutral-grey
  defaults, cited as `seed:shadcn-ui` rather than presented as this
  project's original design, because that project itself never customized
  them (confirmed by reading its `src/components/` — no components beyond
  the unmodified shadcn primitives).
- `editorial-warm.json` — a warm off-white ground, a serif/sans-serif
  heading/body pairing, one accent hue — the shape decision 9's own
  antipattern list points away from (`AP1` unstated gradients, `AP2`
  single-typeface, `AP5` centered-everything) by construction.
- `tool-dense.json` — tight spacing, small text and radius, a utilitarian
  palette — for the dashboard/CLI-adjacent shape a marketing-page-style
  preset would fit badly.

All three declare a `P5`-or-similar pattern requiring interactive controls
(button, input, select, checkbox) to render with a visible border/fill and
a radius from the scale — a direct, mechanical answer to "비뚜러진
콤보박스": the pattern names the exact defect and `gates/tokens.py` (ADR-0008)
already scans for literal color values outside the token set, so a
component that ignores this pattern and reaches for an ad hoc color still
gets caught even though "uses the unstyled native control" itself is not
something a token scanner can detect.

### 11. `interview.md`'s open probe must not be discarded just because discovery ran — it answers a different question

Found while explaining decision 7's saturation change: `interview.md` Step 2
read, before this ADR touched it at all, "**Skip this step entirely when
`spec/00-discovery.md` exists.** The discovery record already holds the
answer to any open probe." That premise is false. `00-discovery.md` answers
questions about **the problem** — who has it, how often, why. It says
nothing about **how the solution behaves** — what a user sees or gets back
after acting. Treating "discovery ran" as "no more open questions needed"
collapses two different pipelines' jobs into one: discover finds the
problem, interview is supposed to find the shape of the fix, and a
thorough discovery record does not make the second job unnecessary — if
anything, a thorough discovery record made this worse, because it gave
Step 2 a plausible-looking reason to skip straight to drafting, and
drafting is exactly where `gk-trial2`'s Assumption 4 came from: the
interviewer decided the feature-to-screen mapping alone, with nobody having
asked a single question about implementation shape first. Decision 7's own
Step 3.5 (confirm the mapping after drafting) was built to catch this after
the fact — but catching a silent decision post-hoc is strictly worse than
not drafting it silently to begin with, and Step 2's blanket skip was
guaranteeing exactly that path every time discovery existed.

**Step 2 now skips only the specific open question discovery already
answered, never the step wholesale.** discovery covers the problem; Step 2's
question is retargeted to implementation shape specifically — what happens
right after a user acts (submits a form, checks a box), not "what's the
problem" restated. This is not new question volume so much as pointing the
one open probe interview already had at the thing discover cannot answer,
which is the entire reason two commands exist instead of one.

**Follow-up found immediately after, on the same `gk-todo3` run:**
`discover.md`'s own Step 5 report — untouched by this ADR until now — told
the user its next command, `/gatekit:interview`, "reads this file and asks
almost nothing," and decision 6's new closing question (Step 6) repeated the
same prediction almost verbatim: "사실은 이미 다 모았으니 질문이 거의
없습니다." This is the same mistaken premise decision 11 just removed from
`interview.md` itself, leaking from the other side — `discover.md` cannot
know how much interview will ask, and predicting "almost nothing" primes
the user to expect exactly the silent skip-to-draft decision 11 exists to
prevent, undermining the fix before the user even runs the next command.
**`discover.md` Step 5's report and Step 6's closing question both drop the
prediction entirely** — they name the next command without claiming
anything about how much it will ask.

### 12. Remove the six deepening gates entirely — discovery is one free-ranging conversation, not a form

Found immediately after running the fully-implemented decisions 1–11
against a real project (`gk-todo3`): decision 7 changed *how many*
questions each of the six named gates (`user`, `current_way`,
`frequency_per_month`, `minutes_per_run`, `why_chain`, `failed_attempts`)
could take, but left the gates themselves in place — a fixed list, filled
one at a time, in a fixed order, with progress shown to the user
(`[gate 3-4 · frequency, minutes] 2/6`). Watching this run for real, the
owner rejected the whole structure, not its question count: "6개 게이트
틀 자체를 없애줘... 의도를 가지고 질문을 하니까 grill-me나 내가 만든
ai-dev-pm보다 허접하잖아. 이렇게 동작하면 gatekit을 누가 쓸까?" Both
reference tools this ADR already compared against work by following
whatever thread a conversation actually opens — grill-me hunts "distinct
decision branches," ai-dev-pm's discovery interview is scored on coverage,
not walked through named slots — neither operates a fixed-order form with a
visible completion counter. A named slot with a progress bar is a
scripted interrogation no matter how deep each slot is allowed to go, which
is exactly why decision 7 (loosening the depth per slot) was not enough:
the structure itself, not its depth limit, was what read as "허접."

**Decision: `discover.md`'s six deepening gates, their fixed order, and
their progress display are removed entirely.** Discovery becomes one
continuous free-ranging conversation from the first question to the last —
no separate "collect pains" phase followed by a separate "deepen the chosen
one" phase with different rules, no gate names or slot-filling shown to the
user, no `[gate N-M] x/6` counter. Each question is chosen because the
previous answer made it the obviously next thing to ask (a why, a
step-by-step replay, a look at what was already tried), not because it is
next on a list. The underlying *information* the six gates used to name —
who has the pain, what they do today, how often, why, what was tried — is
still exactly as useful as it was; only the scripted, one-at-a-time,
counted *process* of extracting it is gone, per the owner's own framing:
"틀을 깨라고... 인사이트를 찾아내게 도와주는게 discovery야."

**The conversation's output changes shape to match.** Once the conversation
stops producing anything new (or a stop signal arrives), the whole
conversation is reviewed **post-hoc** — the same move `ai-dev-pm`'s
`extractUseCases()` makes over a raw interview transcript, never a slot
filled turn-by-turn during the conversation — and one or more **improvement
opportunities** are pulled out of it as a summary, each carrying whatever
of the old gate fields the conversation actually established for it (never
invented to fill a gap: what a given opportunity's conversation never
covered is simply absent, and that unevenness across opportunities is
itself honest information about where the conversation actually went
deep). This absorbs decision 1's pain list and decision 2's verdict
proposal into the same post-hoc summary step, rather than pain-collection
and gate-deepening being two separate phases with two different rulebooks —
one conversation, one summary, several possible opportunities in it.

**The summary is shown to the user with one mandatory question: is this
what you want a tool built for?** Not foldable into a smaller confirmation
and never skippable — per the owner's explicit requirement, discovery must
"반드시 되물어" whether the summarized opportunity is really the thing to
build, before anything is written as the chosen problem. Confirming (or
correcting) this is what turns a proposed opportunity's `verdict_suggested`
into the user's own `verdict`, exactly as decision 2 already required, just
moved to this post-summary confirmation point instead of a mid-conversation
ranking question.

**grill-me's floor-not-ceiling principle survives, in an uncapped form.**
Rather than translate grill-me's 20-30 decision-branch floor into a new
fixed number for this differently-shaped conversation, the record now
carries `insights_count` — how many distinct facts and branches the
conversation actually surfaced, counted honestly after the fact.
`spec validate` warns (never fails, never caps) when it looks implausibly
low. This is deliberately the *only* number involved anywhere in this
command, and it exists only as a floor-side honesty check, never surfaced
to the user as a target or a progress figure — the owner was explicit that
uncapping this was non-negotiable: "N개는 한계가 없어야 하고... 상한은
없어야 한다." There is no ceiling constant anywhere in `spec.py` or
`discover.md` for this value, and none should ever be added.

**Choosing to proceed actually invokes `/gatekit:interview`.** Decision 6's
closing question already asked whether to proceed, continue, or stop; this
decision makes "proceed" a real handoff — the command invokes
`/gatekit:interview` itself rather than telling the user to type it — per
the owner's explicit request that choosing to move on should actually carry
the conversation forward, not just print a suggestion and end the turn.

### 13. `interview.md` gets the same treatment: no question ceiling, one continuous conversation toward implementation shape

Found immediately after decision 12, reviewing `interview.md` for the same
structural problem: Step 5 capped the whole interview conversation at two
`AskUserQuestion` calls, and Step 3.5 (added by decision 7, now superseded)
ran feature-mapping confirmation as a separate pass *after* drafting,
one feature at a time. Asked directly to state what this command is for,
the owner's answer reframes its whole purpose: not writing a PRD quickly,
but a **deep interview that turns a chosen problem into implementation
shape** — how many pages the thing needs, what each page does, what each
feature needs to work, "실제로 AI가 해당 기능을 구체화 하면서 설계를 위해
필요한 항목을 인터뷰를 통해 심도있게 뽑아내고 완성도를 높일 수 있도록
초석을 다지는 게 인터뷰 기능." Design direction is explicitly deferred to
`/gatekit:mockup` ("디자인은... 추후로 넘기더라도"), kept out of this
command on purpose.

**Decision: `interview.md`'s two-call ceiling is removed, and the interview
becomes one continuous conversation with no fixed question count**, the
same principle decision 12 already applied to `discover.md`:

- `spec/00-discovery.md`'s chosen pain is brought in as **given, not
  re-asked** — it answers the problem; this interview answers the
  implementation shape, and does not re-litigate the problem itself.
- From there, one open-ended conversation asks about pages/screens needed,
  what each page lets a user do, what each feature needs to work, and the
  unglamorous branches (empty, failure, conflict) — following whichever
  thread the last answer opens, not a fixed checklist, exactly as
  `discover.md`'s Step 2 already works.
- **Feature-to-behavior mapping is confirmed in the same turn a feature
  comes up**, not deferred to a separate post-draft pass (decision 7's old
  Step 3.5 is folded into this single conversation) — closing the
  `gk-trial2` Assumption 4 gap at the point of origin instead of auditing
  for it afterward.
- The conversation ends the same way discovery's does: not a count, but
  whether it is still turning up something concrete the next two commands
  (mockup, tasks) will need. When it stops, the command says so and asks
  directly — continue, or stop here and write the design documents now —
  never predicting the answer in advance, mirroring decision 6's own rule
  against `discover.md` predicting how much interview would ask.
- The report (Step 6) now names the pages/screens the interview actually
  settled on, since that concrete list is the actual deliverable the next
  stage consumes, and the closing question (Step 7) routes to
  `/gatekit:mockup` explicitly — completing the handoff chain decision 6
  and 12 already made discovery-to-interview automatic.

### 14. Discovery must ask before summarizing, not decide privately that it has heard enough

Found immediately after decision 12 shipped, on the very next real run
(`gk-todo3`): decision 12 removed the six-gate structure and told the
command to keep asking "until it stops producing anything new," but named
no explicit moment where the user is asked whether that point has actually
been reached — the command was left to privately judge saturation and walk
straight into Step 3's summary. The owner caught this immediately: "discovery
진행하다가 개선과제 도출 전에, 추가로 질의/응답을 더 할지 여기서 마무리 하고
내용 요약을 할지 왜 안물어봐? 지 맘대로 개선 과제 도출을 하네?" Decision
12's own Step 4 already asks the user to confirm the *summary* once it
exists, but that is a check on the summary's content, not on whether
summarizing was the right moment to begin with — by the time Step 4 runs,
the conversation has already ended on the command's own unchecked judgement.

This is the same class of mistake decision 12 was written to fix, recurring
one step later: a scripted, self-judged transition standing in for an
actual question to the user. Removing the six named gates did not remove
every place a silent judgement call could hide — it moved one from "is this
gate filled" to "is this conversation done," and the second one still
needed its own explicit checkpoint.

**Decision: before Step 3 ever runs, the command states plainly that the
conversation seems to have run its course and asks directly whether to
summarize now or keep going** — never inferred from questions merely
trailing off, never decided and acted on in the same turn. Only a stop
signal (the user already answered this by stopping) skips the checkpoint;
otherwise every transition into summarizing waits for the user's actual
answer. Choosing to continue returns to the free conversation and the
checkpoint runs again whenever it next looks finished — it is not a
one-time gate, it recurs every time the question needs asking.

**A second, smaller finding from the same review**: `insights_count`'s
floor constant (`_INSIGHT_FLOOR = 3` in `spec.py`, surfaced to the user only
through a validator message like "최소 3 권장") risked being read as an
implicit target — "reach roughly this many and stop" — rather than the
floor-only honesty check it is meant to be. `discover.md`'s own text now
says explicitly that reaching any particular count of surfaced facts is
never itself a reason to summarize; the only reason is the conversation
actually running dry, confirmed at the checkpoint above.

### 15. Nothing but the question — no narration of the model's own process leaks into the conversation

Found on the very next `gk-todo3` exchange after decision 14: right after
the user answered a question, the conversation showed lines like "Let me
record where the conversation has gotten to, then continue" and "This is an
important answer... Let me follow this thread" — in English, while
`output_lang` was Korean. The user's question named exactly what was wrong:
"이거 왜 나오냐고." This is the model's own internal deliberation leaking
into what should be a plain interview turn — the same failure mode this
harness's own house style already names for chat replies generally ("Don't
narrate your internal deliberation... user-facing text should be relevant
communication, not a running commentary on your thought process"), showing
up specifically inside a free-form conversation this ADR just built to run
turn-by-turn with nothing scripted between question and answer. Removing
the six named gates and the fixed slots (decision 12) removed one source of
scripted-feeling interaction; it did not by itself guarantee every message
in between stayed clean of narration — that needed its own explicit rule.

**Decision: every message the user sees during `discover.md`'s or
`interview.md`'s conversation is either a question or a plain statement in
`output_lang` — never narration of the model's own process, never
meta-commentary on the answer just given, in any language.** Read the
answer, decide the next question, ask it; nothing goes in between. This is
now stated directly in both commands (`discover.md`'s and `interview.md`'s
"Rules for every question" sections) and in `policy/questioning.md` itself,
so any future interview-style command inherits it rather than needing to
rediscover the same failure independently.

### 16. A recommended guess with more than one real branch is a short numbered list, not rambling prose

Found on the next `gk-todo3` exchange after decision 15: asked whether any
prior attempt had been made to speed up the silence-cutting work, the
recommended-answer guess spelled out two branches as full sentences strung
together with "아니면... 그런데... 아니면..." — technically one
recommendation, but long enough that the user asked directly: "질문이 너무
장황하지 않아?" The owner's fix, stated directly: "차라리 저 부분을 저렇게
할거면 1, 2, 3, 4, 형태로 이런 경우였냐고 질문을 주고 선택하게 하던가" —
explicitly keeping this inside plain chat, not reaching for
`AskUserQuestion` (confirmed when asked directly: "`AskUserQuestion`은 그대로
안 쓰고, 채팅 안에서 1/2/3/4로 짧게 나열해줘").

**Decision: when a recommended answer genuinely has more than one plausible
branch, list them as a short numbered set (1/2/3/4, one short phrase each)
instead of writing them out as prose sentences.** This stays inside plain
chat exactly as before — it does not reach for `AskUserQuestion`, which
`discover.md` still never calls (Step 0's own rule) and `interview.md` uses
only for the small number of discrete decisions Step 5 already covers, not
for open conversation. A single clear guess stays a single sentence; the
numbered form is only for the case that was actually rambling — several
real possibilities worth telling apart, not one recommendation padded with
qualifiers.

**Immediately after this shipped, the owner asked for one more piece:
"선택 옵션과, 직접 입력하게 하는 옵션 선택하게 하면 좋을 것 같아," confirmed
as "직접 입력 옵션도 항상 넣어줘."** A numbered set of guessed scenarios can
itself become a trap if the real answer is not one of them and nothing
invites the user to say so. **Every numbered branch list now always ends
with one more option for "none of these — tell me directly"** (e.g. "5.
다른 이유가 있다면 직접 말씀해주세요"), so the guessed scenarios are never
presented as if they were exhaustive.

### 17. The pre-summary checkpoint must not become a scripted sentence, and a summary must not force a "pain" framing onto something that is not one

Found on the next `gk-todo3` conversation, one about a character-chat
feature the user wanted built — a capability that did not exist yet, not a
workaround to an existing annoyance. Two problems surfaced together:

**The checkpoint (decision 14) was reused verbatim as a fixed sentence.**
The example wording given for it — "지금까지 나온 이야기를 정리해볼까 하는데,
더 나누고 싶은 게 있으신가요, 아니면 이 정도면 정리해봐도 될까요?" — was
written into the file as an illustration of the shape the checkpoint should
take, but it was pasted back to the user unchanged regardless of what the
conversation had actually covered, and with no reference to a specific
uncovered area (a character-creation screen, revisiting past
conversations) that the conversation had visibly not touched yet. The
owner's correction: "멘트를 정하지 말고 맥락을 보고 멘트를 줘야지," followed
by naming exactly what the checkpoint should have surfaced — "예를 들어
캐릭터를 만드는 화면이 어땠으면 좋겠다거나, 이전 대화를 다시 찾아보는 일이
있을까 같은 건 아직 안 여쭤봤어요." A single example sentence in this file
is not a script — every command in this file that shows example wording is
one instance of a shape, not text to reuse.

**The summary itself forced a "problem/pain" framing onto a conversation
that was about creating something new.** Reviewing the summary, the owner's
verdict: "충분히 대화를 나눈 것까지는 좋았는데 이 경우는 개선과제가 아니라
이런 기능을 탑재해서 캐릭터 챗을 만들려고 하는지 내용을 제대로 요약하고...
개선과제가 아니잖아... 없는 걸 만드는 거지." Decision 12's `pains` schema
and `verdict_suggested` questions are still the right mechanism (something
new can still be `reuse` if a tool already does it), but the prose summary
had been written as if the conversation were about relieving a suffered
annoyance, when it was actually about wanting a capability that does not
exist. The fix generalizes past this one case: **write the summary in
whatever terms the conversation actually used** — a pain, when it was a
pain; a desired new capability, plainly, when it was that — never inventing
a suffered problem to fit the "improvement opportunity" vocabulary the
schema's field names might suggest.

**A related instruction from the same review, stated directly: "인터뷰
요약을 틀에 맞추지 말고 진짜 요약을 해줘, PRD를 바로 뽑아낼 수도 있는
재료가 될 거야."** The summary this command produces is not a form checked
off against field names — it is the raw material `/gatekit:interview`
builds the PRD from, so it needs to carry enough real, concrete detail
(in the conversation's own terms) that someone could start drafting a PRD
from it directly, not merely enough to satisfy `spec validate`.

### 18. Ask one question, then actually stop — do not generate the user's turn for them

Found immediately after, on `/gatekit:interview` in the same `gk-todo3`
session: the conversation asked one question, then — without a real reply
ever arriving — kept producing further questions on its own, one after
another, until the owner cut it off mid-stream: "질문에 답을 하지
않았는데 계속해서 질문을 만들고 그 다음 질문을 계속해서 쏟아내고 있어서
중간에 끊었어." Every rule this ADR had added by this point (no ceiling, no
narration, numbered branches with a free-text option, an honest checkpoint)
governs *what a question looks like* or *when the conversation as a whole
ends* — none of them said, in so many words, that sending a question ends
the model's turn and the next question is written only once an actual reply
exists. "One question per message" reads naturally as a formatting rule
(don't bundle two questions together); it does not by itself rule out the
model imagining a plausible answer and rolling forward to the next question
unprompted, which is exactly what happened.

**Decision: asking a question ends the turn, unconditionally.** The model
never invents or imagines the user's answer and continues on its own to a
further question in the same turn — every next question is written only
after the user's actual reply arrives, no exception for an answer that
seems obvious, questions that feel related enough to bundle, or a
conversation that feels almost finished. This is stated once in
`policy/questioning.md` (a new "Ask one, then stop and wait" section, ahead
of decision 15's "nothing but the question" section, since this is a prior,
more basic requirement — a clean single question is worthless if three more
get generated on top of it uninvited) and referenced directly in both
`discover.md` and `interview.md`'s own question rules, so neither command
depends on inferring it from the general "one question per message"
phrasing alone.

### 19. Do not preview a question and then ask it again for real

Found on the next exchange, once decision 18's fix had the conversation
correctly waiting for replies again: a question was preceded by a preview
sentence ("직접 만드는 기능이 있었는데 안 써본 이유가 궁금합니다") and then
asked again, essentially unchanged, as the actual numbered question
("캐릭터를 직접 만드는 기능이 있었는데 안 써보신 이유가 뭐였나요?" followed
by the 1-5 list). Not two different messages — decision 18 already fixed
that — but the same question said twice inside one turn, the "궁금합니다"
sentence functioning as an unnecessary preview of the question that
immediately follows it.

**Decision: never precede a question with a sentence that previews it and
then ask the same thing again as the real question — say it once.** Added
to both `discover.md` and `interview.md`'s question rules. This is a small,
narrow fix, but it is also a fourth instance in the same session of the
same underlying pattern this whole run of decisions (12, 15, 16, 18, and
this one) keeps finding: a scripted-sounding habit that survives past the
structural fix (removing the six gates) because it lives in phrasing habits,
not in the six-gate structure itself. Each of these was caught only by
watching a real conversation, not by reasoning about the command file in
the abstract — the honest pattern across this whole extension of the ADR.

### 20. Four fixes from one `gk-todo4` run: no raw tool-call leakage, a `notes` catch-all, an unambiguous checkpoint reply, and Step 4 split into individual questions

Found together on a single `gk-todo4` discovery conversation about a
character-chat app, reviewed as one batch:

**A. Raw tool-call syntax leaked into the conversation.** Mid-conversation,
literal `<invoke name="Bash"><parameter name="command">mkdir -p
.../gk-todo4/spec ...` text appeared in what the user saw. The underlying
cause — a tool call's raw form leaking into rendered output instead of
running silently — is a host-level failure this ADR cannot fix directly.
What is fixable here: `discover.md` never had a reason to call `Bash`/`mkdir`
at all — the `Write` tool creates missing parent directories itself — so
the command now says so explicitly, removing the one call in this command
whose leaked text caused real confusion, even though it cannot guarantee no
tool call ever leaks.

**B. Real information had no field to land in and was silently dropped.**
The conversation established two things with no home in the six named gate
fields: success criteria the user stated directly ("1번이랑 2번" — still
using it days later, and the character recalling past context) and a
concrete requirement ("character는 여러개 만들 수 있어야 해"). Neither
survived into the final summary. **Every pain in the fence now carries an
optional free-text `notes` field** for exactly this — real, conversation-
established facts with no matching named field — read by `interview.md`
with the same weight as any named field, not as a footnote. This is
distinct from decision 17's "don't force a pain framing" fix: that one was
about which vocabulary to use; this one is about not losing information a
fixed schema never anticipated needing to hold.

**C. A checkpoint reply that answered a different question was read as
consent to proceed.** The checkpoint (decision 14) asked whether to
continue or wrap up; the user's actual reply answered a content question
(the multi-character requirement) and happened to end with "정리해도
좋아" — a phrase about a different topic that the command read as an
unambiguous yes to the checkpoint. The owner's correction: "그걸 내가
선택한 게 아니야." **The checkpoint reply must be unambiguously about
continuing-or-wrapping-up before Step 3 runs** — a reply that answers
content but leaves the checkpoint itself unaddressed does not count, even if
it contains words that sound like permission; when ambiguous, the checkpoint
gets asked again, explicitly, rather than assumed answered.

**D. Step 4 fired as one uninterrupted burst instead of individual
questions.** Once the (misread) checkpoint reply arrived, the command
produced the summary, the "is this right" question, the verdict
confirmation, and the deadline question all in one message with no waiting
in between — decision 18's "ask one, then stop and wait" rule, already
stated for the free conversation, was never applied to Step 4's own
sequence of questions. **Step 4 is now explicitly three separate questions
under the same rule**: does the summary match, is the verdict right, what
is the deadline — each sent alone, each waited on, before `spec/
00-discovery.md` is written.

Findings B, C, and D compound: had C not misfired, D's burst would have
followed the very next reply regardless, so both needed fixing together for
the actual observed failure (the summary and every Step 4 question all
appearing unrequested in one message) to actually stop recurring.

### 21. Every spec-kit template gains YAML frontmatter (`title`/`date`/`status`)

Found on `gk-todo4`'s actual written output: the owner opened
`spec/00-discovery.md` and noted the file had no frontmatter at all — just
an H1 heading followed by a prose "작성일 · 상태" line. Checked against all
nine spec-kit templates (`00-discovery.md`, `01-prd.md`, `02-design.md`,
`02-screens.md`, `03-architecture.md`, `04-tasks.md`, `05-gate.md`,
`PROGRESS.md`, `RECOVERY.md`, in both `ko` and `en`): none of them ever had
frontmatter — this predates this ADR entirely and was simply never noticed
until a real written file was read directly.

**Decision: all 18 template files (9 files × 2 languages) gain a YAML
frontmatter block** —

```yaml
---
title: "{{project_name}} — <the file's existing title>"
date: "{{date}}"
status: "<the file's existing status value or placeholder>"
---
```

— confirmed to hold exactly `title`, `date`, and `status`, nothing more.
Verified beforehand, not assumed: `spec.py`'s `_present_headings()` only
scans lines starting with `## `, and `_iter_fences()` matches only
backtick-delimited code fences, so a leading `---`-delimited YAML block is
invisible to both and requires no validator changes — confirmed by running
the full test suite after the change (1091 tests, unchanged from decision
20, so no new `spec.py` logic was needed).

For the two files (`00-discovery.md`, `01-prd.md`) that already carried a
prose "Written: {{date}} · Status: {{...}}" line, that line is removed
(the frontmatter now carries the same information) rather than duplicated.
`PROGRESS.md` is the one exception: its existing body `STATUS:` line is
explicitly documented as something "do not change the format of," on the
suspicion it may be read by something outside `spec.py` — the frontmatter's
`status` is added *alongside* it as a summary field, not a replacement, and
the file says explicitly that the body line remains the source of truth.

Every command that writes one of these files (`discover.md`, `interview.md`,
`mockup.md`, `design.md`, `tasks.md`, `gate.md`, `build.md`, `verify.md`)
gains an explicit instruction to fill the frontmatter block along with every
other placeholder — filling frontmatter was already implied by each
command's existing "fill every placeholder, leave no `{{…}}` marker" rule,
but is now named directly so it is not the one part of the template a
command silently skips.

### 22. Two findings from reading a real, complete `gk-todo4` run end to end: the Blocking bar was too high, and `-visual` verdicts were invisible to the aggregate

Found by reading `gk-todo4`'s actual spec files after a full run through
every pipeline stage (discover → interview → mockup → tasks → gate → build →
verify), not from a live conversation — decisions 1 through 21 were checked
against real, finished output for the first time as a whole. Most of them
held up: the discovery summary and its `notes` field reached the PRD
faithfully, the assumption ledger's `Blocking`/`Confirmed` columns worked,
the prototype confirmation line and per-task build screenshots both existed,
and the verify evaluator's `-visual` judgement genuinely caught two real
defects (broken icon placeholders, clipped textarea text) by reading the
screenshots against `design-antipatterns.json`. Two gaps surfaced:

**A. The `Blocking` bar ("would this sink the plan") was too high and let
real defects through as `n`.** In the PRD's own ledger, the numeric weighting
behind intimacy level and its on-screen display form — the entire point of
a feature literally named "친밀도와 말투 변화" — were both marked
`Blocking: n`, alongside nine other rows, leaving exactly one `y` in the
whole ledger. Being wrong about either would not collapse the plan, so the
literal "sink the plan" test correctly said `n` — but that is the wrong
question. **Decision: the bar is now "would being wrong about this row
directly hurt how a core feature actually feels to use," not "would the
whole plan fail."** A feature's own defining mechanic (how a computed value
is weighted, how it is shown) blocks even though the plan survives being
wrong about it; what does not survive is that feature's quality. Genuinely
low-cost, interchangeable choices (which of several equivalent sample
characters ships first) still read `n`.

**B. `-visual` verdicts (decision 9) had no path into the reported result.**
`spec/PROGRESS.md` showed "ok 6 / fail 9 / unverified 1" as the contract's
aggregate — a number `contract.py` computes from code criteria only, because
it runs commands and checks exit codes and artifacts; it has no way to see
an image. Two `-visual` verdicts read `fail` (broken icons, clipped text)
in the same report, sitting beside that aggregate with no stated
relationship to it. Nothing in `verify.md` said whether a clean aggregate
could be reported as "the contract passes" while a `-visual` verdict
disagreed — the two numbers existed in the same file without ever being
reconciled. **Decision: `verify.md`'s Step 4 now states explicitly that the
aggregate never includes `-visual` verdicts (they come from the evaluator
reading an image, not from running a command), and that "the contract
passes" may only be reported when the aggregate is `ok` *and* every
`-visual` verdict is `ok` or `unverified` — never when any is `fail`.**
`-visual` verdicts get their own row in the report, with the same weight as
any other criterion, never silently folded into or omitted because of the
aggregate.

Both findings share a root cause worth naming: `contract.py`'s aggregate is
the one number this ADR's whole verification chain ultimately reports
against, and anything that cannot be expressed as a code criterion (a
subjective judgement about feel, a verdict from reading an image) is
invisible to it by construction. Decision 9 already worked around this once
by inventing the `-visual` convention; this decision is the fix for the gap
that convention left — a second, unreconciled number sitting next to the
one everyone actually reads.

### 23. Superseded same-day by decision 24 — a checklist-question fix was too narrow for what the owner was actually asking for

Found on `gk-todo4` (same finding as decision 24 below): the character-chat
interview never surfaced context-window management, content-safety limits,
or persona drift. The first fix tried here was narrow — a new Step 2.5
reading a seed data file (`domain-checklists.json`, same
convention as `design-antipatterns.json`) that matched a known domain and
asked its checklist items as ordinary questions. Reviewing it with the
owner surfaced that this missed the actual point: **a seed file starts
empty and only grows from real trials, so it cannot help a domain it has
not seen yet — "쓸만해질 때까지 기다려달라" is not something a user will
accept.** More fundamentally, the owner's real complaint was not "a few
questions are missing" but that `interview.md`'s whole posture is
answer-only — it builds exclusively from what the user thought to say, the
same structural gap decision 12 already named, never from what the
interviewer itself knows about the category. The owner named the actual
target directly: tools like Lovable propose a fuller feature set from
domain knowledge and let the user prune it, rather than building up from a
blank form one answer at a time. **The checklist-file approach and its
Step 2.5 are withdrawn; `domain-checklists.json` was
deleted the same day it was created.** Decision 24 replaces it.

### 24. `interview.md` researches the category and proposes a fuller feature set for the user to prune, instead of building only from what the conversation's own threads produced

This is the shape decision 23 was reaching for and missed: not "ask a few
more questions from a static list" but "propose, then prune" — the same
posture the owner pointed to in Lovable, adapted to keep gatekit's own
discipline (nothing invented silently, every addition auditable, the
user's own words never overridden).

**The core risk this decision had to solve first: research proposing
generic, averaged-out features could dilute a product's actual
differentiators** — if research does not know character-chat's intimacy
mechanic is the whole point of this specific product, treating research
output and conversation output as one undifferentiated pool risks
"smoothing" the product toward a category average. The fix is a hard
separation, not a shared bucket: **Step 2.5a freezes everything Step 2's
conversation already established as a locked differentiator set before any
research runs, and research (2.5b–d) is only ever allowed to propose items
that do not already overlap it** — filling gaps beside the user's own
stated reasons for building this thing, never second-guessing or replacing
them.

**Decision:**

- **Step 2.5a** locks Step 2's conversation output as-is — the
  differentiator ledger, untouchable by what follows.
- **Step 2.5b** runs `WebSearch` (added to `interview.md`'s
  `allowed-tools`) across four distinct angles rather than one generic
  query: category-standard features, user complaints/reviews (the closest
  available proxy for what actually made `gk-todo4`'s reference product get
  deleted — a real failure mode, not a guessed feature list), recent/leading
  examples kept in a separate "reference idea" bucket, and
  technical-pitfall or postmortem sources. **An item is only labeled a
  "standard" (기본기) candidate when at least two independent sources
  corroborate it** — a single source's opinion never counts as a category
  norm, and anything from the leading-examples angle alone stays labeled a
  reference idea, explicitly not typical.
- **Step 2.5c** diffs research candidates against the Step 2.5a frozen set
  (drop anything already covered) and presents what remains to the user in
  two visibly separate groups — cross-checked hygiene candidates with their
  citation basis, and single-source/trend reference ideas marked as
  optional inspiration — cross-referencing `spec/00-discovery.md` when the
  user's own recorded experience confirms or contradicts a candidate (that
  evidence outranks research).
- **Step 2.5d** is a prune conversation, not a fill-in-the-blank one: the
  user reacts to the whole proposed set under the same rules as every other
  Step 2 question (one at a time, stop-and-wait, no fixed count), and
  "빼주세요"/"나중에요" are complete answers needing no further
  justification. Every kept item becomes an `F<n>` carrying a one-line
  evidence note (`출처: 리서치 (2건 이상 교차확인)`, `출처: 리서치 (참고
  아이디어)`, or `출처: 사용자 경험`) — so a later reader can audit why an
  item the user never explicitly requested is in the PRD, the same
  auditability principle behind decision 5's `Blocking`/`Confirmed`
  columns.
- **Step 5** (confirm the draft) now shows the full `F<n>` list — Step 2's
  own features and whatever Step 2.5 added that the user kept — as one
  undifferentiated list before asking for approval, so the confirmation
  covers the whole set the user is actually about to get built, not only
  the conversational part.
- **`/gatekit:mockup` Step 7b** gains two changes closing the loop this
  decision opens: the live prototype must now be filled with **realistic
  sample content for every `F<n>`**, not empty inputs, because the
  prototype is the point where a feature-list gap becomes visually obvious
  in a way a bullet list hides; and immediately before final confirmation,
  the command now asks explicitly whether the prototype fully covers what
  should be built — a "something's missing" answer routes back to
  `/gatekit:interview`'s Step 2 conversation to define the feature
  properly (page, behavior, data), never invented directly into the HTML.

**What this does not do.** It does not turn interview into a template
library the way Lovable's is — there is no stored library of
previously-built app structures to draw from; research runs fresh every
time via live search, which trades consistency (the same domain researched
twice can turn up different candidates) for not needing to wait for a seed
library to accumulate before being useful on day one. Whether specific
research findings are worth hard-coding as a `design-antipatterns.json`-style
seed file remains open, to be revisited once real interviews using this
flow show which research findings turn out reliably useful across runs.

## Consequences

**What this buys.** The exact failure the owner observed — an
interviewer-decided mapping that never became a question, a design phase
skipped without anything noticing, and a result only ever seen for the
first time after the full build finished — becomes structurally harder:
discovery must surface real alternatives before narrowing, a pain that
should not be built at all is refused before it reaches interview, a
UI-bearing spec cannot reach `/gatekit:tasks` without a screen spec existing
in some form, and `/gatekit:tasks` cannot run at all until the user has
actually touched a working prototype and signed off on it. The last of
these is the direct fix for "기다림 끝에 보여지는 결과는 엉망" — the user
now sees and edits the real shape of the thing *before* `/gatekit:build`
starts, not after. And the pipeline no longer goes quiet at the end of a
step waiting for the user to remember the next command — decision 6 makes
every planning-stage command ask what happens next. Decision 8 closes a gap
found while checking decision 7 for real: the user's own opening words are
no longer discarded the moment they fail to name "one real user and their
pain" — naming a product is still information, and Step 2 now uses it
instead of asking about a random unrelated topic on the very next question.
Decision 9 closes the gap between "the prototype looked right" and "the
shipped code looks right" — the real implementation now leaves screenshot
evidence an independent evaluator actually looks at, instead of the
prototype's visual quality being the last thing anyone checked before the
real, differently-built result appears at the end. Decision 10 closes
another gap this ADR's own earlier decisions left open: a greenfield
project now has real style options to choose from, instead of decision 3's
fallback question offering a choice between zero things and landing on
unstyled browser defaults every time. Decision 11 makes `interview.md` ask
about implementation shape even when discovery ran, closing the exact gap
`gk-trial2`'s Assumption 4 fell into. Decision 12 is the one that actually
delivers what the owner asked for from the start ("discovery에서 개선과제
도출을 위한 요소를 뽑아낼 만큼 충분한 대화") — decision 7's attempt to fix
this by loosening a per-gate question count was not enough, because the
six named gates and their fixed, progress-counted order were themselves the
"허접함" being pointed at; decision 12 removes that structure and makes
discovery one free-ranging conversation, summarized into improvement
opportunities after the fact, exactly as `grill-me` and the owner's own
`ai-dev-pm` already work. Decision 13 carries the same fix into
`interview.md`: no question ceiling there either, feature-to-behavior
mapping confirmed in the moment a feature comes up rather than in a
separate post-draft pass, and the command's own stated purpose corrected
from "draft a PRD" to "interview deep enough to fix implementation shape —
pages, behavior, data — before design or tasks ever start." Decision 14
closes the gap decision 12 left open one step later than expected: removing
the six named gates stopped one kind of silent judgement call (is this gate
filled) but left another in place (is this conversation done) — the
transition into summarizing now waits for the user's actual answer instead
of the command deciding on its own that it has heard enough. Decision 15
closes a gap of a different kind: the conversation itself now stays clean
of the model's own process narration leaking through between question and
answer, in any language, so a free-form conversation reads as an interview
and not as the model thinking out loud in front of the user. Decision 16
keeps the recommended-answer guess itself tight: a real multi-branch guess
becomes a short numbered list instead of rambling prose, so "recommend an
answer" (which every question already does) does not become its own source
of the over-long messages this whole redesign is trying to avoid — and
every such list always ends with a "none of these, tell me directly" option
so the guessed branches never crowd out the real answer. Decision 17 closes
two related gaps: the pre-summary checkpoint no longer degrades into a
copy-pasted sentence regardless of context, and the summary itself no
longer forces every conversation into "pain" vocabulary when some are
genuinely about building something that never existed — both fixes aimed at
the same goal, a summary specific and honest enough to draft a PRD from
directly. Decision 18 fixes the most basic requirement of an interview,
prior to any of the others: a question ends the turn, unconditionally — the
model does not generate the user's side of the conversation for them, no
matter how confident it is in the likely answer. Decision 19 is small but
completes the same pass: a question said once, not previewed and then
repeated in the same turn. Decision 20 closes four gaps at once — no
mkdir call left to leak, a `notes` field so real information stops being
silently dropped, a checkpoint reply that must unambiguously answer the
checkpoint before the command proceeds, and Step 4 held to the same
ask-one-then-wait discipline as everywhere else in the conversation.
Decision 21 fixes a gap that predates this whole ADR: every spec-kit
template now carries machine-readable frontmatter, so a written file's
title, date, and status are readable without opening the body — a plain
gap noticed only once a real written file was actually read. Decision 22,
found only once `gk-todo4` had run all the way through every pipeline
stage, closes the two gaps a live conversation could never have surfaced:
the `Blocking` bar now catches an assumption that would hurt a feature's
actual quality, not only one that would sink the whole plan, and a
`-visual` fail can no longer sit unreconciled next to a clean aggregate —
the report states plainly when the two disagree. Decision 24 (superseding
23's narrower attempt) closes the gap decisions 12/13 left open by design:
following only the threads the user opens can never surface a
domain-standard concern the user never thought to raise, so `interview.md`
now freezes what the conversation established, researches the category
live across four angles, and proposes a fuller feature set — cross-checked
hygiene candidates separated from single-source reference ideas — for the
user to prune, with "out of scope" as a valid, recorded answer rather than
a forced inclusion. `/gatekit:mockup`'s prototype now carries realistic
sample content for every feature and asks explicitly, before confirmation,
whether the prototype covers everything that should be built.

**What it costs.** Discovery sessions get longer for a user who arrives
with exactly one pain already in mind — the branch floor asks for two more
before narrowing, even if the first is obviously the right one to build.
This is the same trade `grill-me` and `WIZARD_MIN_ANSWERS` already make:
mechanical floors cost time on the easy case to guarantee depth on the hard
one. Every `/gatekit:mockup` run now costs one guaranteed question (source
vs. new design) even when `$ARGUMENTS` already carries an obviously valid
source. Every project now has a mandatory prototype round-trip between
design and tasks — at least one more full turn (build the HTML, hand it
over, get feedback or a sign-off) even for a spec the user would have
approved from the static preview alone. And with decision 7, a gate or
mapping confirmation with a genuinely simple answer no longer has a ceiling
protecting the user from being asked "is there really nothing more here?" —
the saturation signal has to do that work instead, and it is a heuristic
(word-overlap and restatement detection), not a proof; a badly-tuned
saturation check could either close too early (indistinguishable from the
old three-question ceiling) or drag out a gate whose paraphrase-detector
keeps seeing "new" wording in a genuinely closed topic. Decision 9 adds one
screenshot capture per UI-touching task during build (small, and does not
block the task's own gate) and one more thing the verify evaluator checks
per task — a modest addition to a step that already runs a full contract
pass. Decision 24 adds a live `WebSearch` round (four queries) plus a
prune conversation to every interview — real time and real risk: research
quality varies run to run since nothing is cached or reused, a
badly-corroborated candidate could still slip through the two-source bar
if the sources are not actually independent, and the frozen differentiator
set (Step 2.5a) is the only thing stopping research from diluting a
product's own reason for existing, so a bug in that freeze is a real
regression risk to watch for. `/gatekit:mockup` now costs more per
revision round too — sample content for every feature is real content to
write, not placeholders, and the new "does this cover everything"
question can send the flow back to `/gatekit:interview` for another
round-trip. All these costs are the same deliberate trade: less silent
inference and fewer artificial ceilings, more forced, cheap-relative-to-a-
full-build checkpoints — paid for in session length, not in rework after a
build.

**What it does not do.** It does not add `deep-interview`'s numeric
ambiguity score or its Round-4/6/8 challenge-agent machinery wholesale —
decision 7 borrows only the underlying principle (keep probing while a topic
still yields new ground) and reuses `discover.md`'s own existing
restatement/overlap detector as the mechanism, rather than importing a
second, differently-shaped scoring system. It does not touch
`policy/questioning.md`'s `AskUserQuestion` budget (2 free calls, then a
justification line) — that budget governs a different kind of question
(a discrete decision put to the user as options) from a deepening gate's
open-ended follow-up, and decision 7 is explicit that interview's
feature-to-screen confirmation runs on the saturation signal precisely so it
does not get folded into (and silently capped by) that budget. The prototype
gate (decision 4) does not touch the backend or make network calls — it
stays frontend-only markup, same as ADR-0011's static preview, so it cannot
itself become the thing that takes hours; only the back-and-forth with the
user can extend it, and that is the point.

**Contract changes** (`docs/ARCHITECTURE.md`): the discovery fence schema
gains `verdict_suggested` / `verdict` per pain; `spec validate` gains the
verdict-blocks-progression check and the blocking-assumption-fails check;
`heading-map.json`'s `absent_ok` list drops `02-screens.md` for UI-bearing
specs (conditional, not unconditional); `/gatekit:mockup` gains a new Step
1.5 (forced source-or-new question, every run) ahead of its existing Step 2
extraction branch, the recommended-style fallback branch for a source-less
greenfield input, and a new prototype step producing
`spec/design/prototype-<name>.html` plus the revision loop and its
confirmation record in `02-screens.md`; `/gatekit:tasks` Step 1 gains the
prototype-confirmation precondition alongside the existing `02-screens.md`
existence check; `discover.md` Step 6, `interview.md` Step 7, `mockup.md`
Step 8, and `tasks.md` Step 7 each gain a closing continue-or-extend
question (plain chat for `discover.md`, `AskUserQuestion` for the other
three) as the last thing the step does; `interview.md`'s feature-to-screen
mapping confirmation runs on a saturation condition instead of interview's
`AskUserQuestion` budget; **`discover.md`'s six named deepening gates, their
fixed order, and their progress display are removed entirely (decision 12,
superseding decision 7's smaller per-gate fix)** — discovery is now one
free-ranging conversation summarized post-hoc into `pains` entries carrying
whatever gate-shaped fields the conversation actually established, plus a
new `insights_count` field (a floor-only, uncapped honesty check, mirroring
`grill-me`'s decision-branch count) and a mandatory "is this what you want
built?" confirmation before the chosen pain's fields are written; `spec.py`
gains `_check_insight_count` and `_check_discovery` now reads gate fields
from the chosen pain when present there, falling back to the record's top
level for pre-decision-12 files;
`policy/questioning.md` and `policy/language.md` both gain new rules found
during this same real-world check: an "exhausted" stop-signal category
(a direct "no more" answer, distinct from the existing "delegating" category
like "you decide"), and an explicit ban on surfacing internal rule names
(ADR numbers, decision numbers, field names like `pain_floor_waived`) to the
user in any chat reply or written spec text. `presets/design/README.md`'s
commit rule is amended to distinguish seed presets (committed immediately,
citing an established origin) from observed presets (the original
build-first rule, unchanged); three seed presets ship immediately
(`shadcn-neutral.json`, `editorial-warm.json`, `tool-dense.json`) so
decision 3's greenfield fallback has real options instead of an empty
catalog. `interview.md` Step 2's blanket "skip when discovery exists" rule
is narrowed to "skip only the specific question discovery already
answered," retargeted at implementation shape rather than the problem
discovery already covers. `interview.md` is restructured end to end
(decision 13): Step 5's two-`AskUserQuestion` ceiling is removed, decision
7's post-draft Step 3.5 is folded into the main conversation (feature
mapping confirmed the turn a feature comes up), the conversation's stated
goal becomes settling pages/screens and per-page behavior, the closing
question and report both name `/gatekit:mockup` as the next command
explicitly. `discover.md` gains an explicit checkpoint (decision 14)
between the free conversation and the summary step, asked plainly and
waited on rather than inferred, skipped only by an actual stop signal; its
"no maximum" language is sharpened to say explicitly that reaching any
particular `insights_count` is never itself a reason to summarize.
`discover.md`, `interview.md`, and `policy/questioning.md` all gain an
explicit "nothing but the question" rule (decision 15): every user-facing
message in these conversations is a question or a plain statement, never
narration of the model's own process, in any language. Both commands'
recommended-answer rule (decision 16) now says a multi-branch guess is a
short numbered list (1/2/3/4), never prose spelling out each branch as a
full sentence, and always ends with a final "none of these, tell me
directly" option. `discover.md`'s pre-summary checkpoint (decision 17) is
now explicit that its example wording is an illustration, never a script,
and must reference a specific uncovered area when one is visible; Step 3's
summary instructions now say explicitly that a conversation about creating
something new must be summarized as that, not forced into "pain" language,
and that the summary is PRD-drafting material, not a schema checklist.
`policy/questioning.md` gains a new "Ask one, then stop and wait" section
(decision 18), and `discover.md`/`interview.md` both state directly that
sending a question ends the turn and the model never generates the user's
reply for them; both also gain a rule (decision 19) against previewing a
question in a sentence and then asking the same thing again for real.
`discover.md` (decision 20) now writes its file with `Write` directly (no
`Bash`/`mkdir`), the discovery fence schema gains an optional `notes` field
per pain read by `interview.md` alongside the named fields, the checkpoint
requires an unambiguous reply before Step 3 runs, and Step 4 is split into
three individually-asked, individually-waited-on questions instead of one
burst. All 18 spec-kit template files (decision 21) gain a YAML
frontmatter block (`title`/`date`/`status`); every command that writes one
of these files is updated to fill it along with every other placeholder.
`interview.md`'s `Blocking` criterion (decision 22) changes from "would
this sink the plan" to "would this hurt a core feature's actual quality";
`verify.md`'s Step 4 states explicitly that the aggregate excludes `-visual`
verdicts and that "the contract passes" may not be reported while any
`-visual` verdict reads `fail`.

## Rejected alternatives

- **Leave Step 2's blanket skip alone and rely on Step 3.5 (decision 7) to
  catch a bad mapping after drafting.** This was the state before decision
  11: Step 3.5 already existed specifically to confirm feature-to-screen
  mappings post-draft. Rejected as insufficient once traced through — Step
  3.5 only asks about a mapping "not obvious from the user's own words
  already on record," and if Step 2 never asked an implementation-shape
  question, nothing is ever on record to make a mapping obviously wrong,
  so Step 3.5 tends to rubber-stamp whatever the drafting step already
  decided. Fixing the skip at its source (Step 2) is cheaper than only
  auditing its consequence after the fact.
- **Keep supernext's structure staged as a scratch candidate until it is
  observed in a real gatekit build, per the original preset rule.** This
  was the first response to finding the empty catalog, and it was reversed
  once the owner pointed out the chicken-and-egg shape directly: no real
  build reaches a good result *without* a preset to start from, so waiting
  for one before shipping any would keep the catalog empty indefinitely —
  the exact failure just observed on `gk-todo2`. The seed/observed split
  (decision 10) resolves this without abandoning the original rule's intent
  (never launder a guess as a proven preset) — it only recognizes that an
  established design system's own defaults are not a guess.
- **Drop the "observed in a real build" rule entirely, for all presets.**
  Rejected: the distinction still matters for a preset invented from
  scratch rather than adopted from somewhere with its own track record —
  that kind of preset really is a guess until a build proves it, and the
  original rule's caution stays correct for it. Decision 10 narrows the
  rule's scope (seed vs. observed) rather than removing it.
- **Adopt the reviewed ChatGPT conversation's fixed-stack starter
  (Vite+React+Tailwind+shadcn, pre-installed components) and a generated
  per-project `CLAUDE.md` design section.** Rejected wholesale: gatekit
  derives the stack per project in `03-architecture.md` and this repo's own
  CLAUDE.md already forbids assuming a dependency exists — pinning one
  frontend stack would make gatekit wrong by default for any non-React
  project (a CLI tool, a backend service, `gk-todo2` itself if it had
  chosen something else). `/gatekit:build` already has a design-instruction
  channel (`spec/02-design.md`, `tokens.json`) that does not require
  authoring a file gatekit does not otherwise own. Only the
  stack-independent pieces (decision 9's build-evidence screenshots and
  defaults list) were kept.
- **Put the screenshot check inside decision 4's prototype gate
  (`/gatekit:mockup`), as a self-critique loop before the prototype reaches
  the user.** This was the ADR's own first draft of decision 9, reversed
  after being asked directly where it would actually catch drift. The
  prototype is throwaway HTML/CSS built only to agree on screens and flow;
  the real implementation is written later, in whatever stack
  `03-architecture.md` names, entirely inside `/gatekit:build`, and never
  touches the prototype file again. A screenshot loop at the prototype
  stage checks an artifact that gets discarded, not the thing that ships.
- **Have the worker self-critique its own build-time screenshot before
  moving on, instead of only capturing it as evidence for the verify
  evaluator.** Rejected because it adds a round that does not change the
  outcome: the prototype's own revision loop (decision 4) already puts a
  human in the position of judging a rendering, and the verify evaluator
  (an agent that is already, by `verify.md`'s existing design, not the
  producer) already gives the build-time screenshot an independent
  judgement. A worker grading its own screenshot before handing off would
  be the producer evaluating itself a second time — exactly what
  `verify.md`'s "Producer ≠ evaluator" line exists to prevent.
- **Have a human look at the build-time screenshot directly, the same way
  decision 4 has a human confirm the prototype.** Considered and rejected:
  `/gatekit:build` is designed to run unattended once a job starts (workers
  spawn, the host polls status, ADR-0013's whole point is not needing a
  human mid-round), and inserting a human checkpoint per UI task would
  change that shape for every build, not just ones where something is
  actually wrong. Routing the judgement through the evaluator that already
  exists at `/gatekit:verify` catches the same drift without adding a new
  synchronous human step inside build itself.
- **Adopt `deep-interview`'s ambiguity score for discovery.** Solves project
  depth, not branch breadth; would still only deepen the one pain already
  narrowed to, leaving the actual observed gap (no alternatives surfaced,
  no verdict gate) untouched. See "Why deep-interview's ambiguity score does
  not fit here" above.
- **Copy `ai-dev-pm`'s `CONNECT` verdict.** Requires an adjacent system to
  wire into; gatekit's discovery scope is one spec pipeline at a time with
  no cross-project registry to connect against. Dropped rather than
  stubbed.
- **Make the branch floor apply to `interview.md`'s `AskUserQuestion`
  budget instead of `discover.md`'s pain count.** The owner's complaint was
  about the interviewer deciding a mapping *silently*, not about too few
  `AskUserQuestion` calls — ADR-0012's justification tracking already makes
  interview's question budget observable. The actual gap was upstream, in
  discovery never branching into alternatives at all.
- **Run `grill-me` itself as a literal pre-pipeline step.** Considered
  because the owner used it this way in a prior study session, but decided
  out of scope for this ADR: that is a workflow composition choice (chain a
  separate skill in front of gatekit), not a gatekit code change, and stays
  a note for later rather than part of this decision.
- **Block on `unknown` verdicts too, for maximum safety.** Rejected for the
  same reason `ai-dev-pm`'s code gives: it would make refusing to decide
  the strategy that avoids the gate, which is worse than letting an
  honestly-uncertain pain through.
- **Drive the prototype loop through Claude-in-Chrome by default, instead of
  a handed-over file.** Considered for decision 4 because it would let
  feedback come from actual clicks and scrolls rather than typed change
  requests. Rejected as the default: it requires a Chrome session and adds
  real per-round latency (navigate, screenshot, read) for every revision,
  where a static file the user opens themselves costs nothing extra to
  iterate on. Left as an option when the tool is available and the user
  wants to drive it that way, not the required path.
- **Require a per-screen approval row, like backlog item 11b's originally-
  proposed (and explicitly rejected) convention.** Rejected again here for
  the same reason it was rejected in ADR-0011: it adds N checkpoints where
  one whole-prototype confirmation already closes the gap the owner is
  pointing at. The difference from 2026-09-17 is not that per-screen
  tracking is now a good idea — it still is not — but that *some* forced
  look-before-you-build step is now needed where none existed for the live
  prototype at all.
- **Add the same closing continue-or-extend question to `/gatekit:gate`,
  `/gatekit:build`, and `/gatekit:verify` too, for a fully uniform
  pattern.** Rejected: `gate` already closes on an `AskUserQuestion`
  approval decision (Step 6) — adding a second closing question after that
  one would be the over-questioning `policy/questioning.md` itself warns
  against. `build` and `verify` close on a pass/fail verdict where
  ADR-0013 already decided the host session must not silently continue
  past a build result without the user seeing it — an auto-continue option
  there would undo that decision. Decision 6 stays scoped to the four
  commands that currently end in bare prose with nothing to weigh.
- **Keep the per-gate question ceiling but raise the number (e.g. five
  instead of three).** Considered when decision 7's gap was found, and
  rejected: any fixed count reproduces the same failure at a different
  point — a gate about one plain fact would still be forced through padding
  questions, and a genuinely hard causal chain could still hit the ceiling
  one exchange short of the real cause. The owner's own framing named the
  actual defect as the count itself, not its size: "질문 상한은 없애고."
- **Adopt `deep-interview`'s numeric ambiguity score (weighted goal /
  constraints / criteria) as the saturation signal, instead of reusing
  `discover.md`'s existing restatement-overlap check.** Rejected for the
  same reason the ADR's original "why deep-interview's ambiguity score does
  not fit here" section gives: that score is calibrated for judging one
  already-scoped project's overall readiness, not for deciding, per
  exchange, whether one specific gate's conversation just repeated itself.
  Reusing the mechanism `discover.md` already has for exactly this
  (`_RESTATEMENT_OVERLAP`) keeps one detector instead of two with
  overlapping jobs.

## Open questions

- Whether three is the right floor for discovery pains once a real session
  runs under this rule — stated, not measured, the same honesty this ADR
  extends to its own numbers.
- Whether the four ai-dev-pm-derived verdict questions need per-project
  tuning (they were written for a project-management tool's use-case
  triage, not a general one-off spec pipeline) once observed against a
  non-software pain (the `gk-trial2` case itself was arguably closer to a
  content/pedagogy problem than a software one).
- Whether the recommended-style fallback (decision 3) needs its own small
  preset catalog beyond what `design merge-preset` already ships, once a
  genuinely stub-source-less greenfield project is run through it for real.
- How many prototype revision rounds are typical before confirmation
  (decision 4) — no real data yet; if it turns out to routinely take many
  rounds, the per-round cost named in Consequences may need its own stopping
  signal (a prototype-specific version of decision 7's saturation check —
  the revisions themselves stop changing anything material) so the loop
  itself does not become a new source of the "오래 기다림" the ADR is
  meant to shorten.
- Whether non-screen projects (CLI tools, libraries — exempted from
  decision 3's screen-spec requirement) need an equivalent prototype gate
  in some other form (a sample CLI transcript to react to, say), or whether
  skipping decision 4 entirely for them is correct because there is no UI
  to prototype.
- Whether the restatement-overlap threshold `discover.md` already tunes for
  `why_chain` (0.6) is the right sensitivity for decision 7's general
  saturation check across all six gates, or whether a gate about a concrete
  fact (`user`) needs a different threshold than one about a causal chain —
  no real multi-gate session has run under the new rule yet to tell whether
  one constant serves both.
- Whether decision 7's removal of `interview.md`'s implicit per-mapping
  question limit needs its own explicit ceiling once a real interview
  produces a feature-to-screen mapping that keeps generating "new" framings
  without ever converging — the saturation check assumes good-faith
  paraphrase detection catches this, which has not been tested against an
  adversarial or simply confused back-and-forth.
