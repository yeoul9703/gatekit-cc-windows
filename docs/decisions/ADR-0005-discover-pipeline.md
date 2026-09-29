# ADR-0005: An optional discover stage before interview, with code-checked gates

## Context

`/gatekit:interview` assumes the user can already name one real person and
what that person struggles with. It researches the repository, asks one open
question, drafts, and asks at most two decision questions. That is the right
shape for someone who knows what to build. It is the wrong shape for the
person who arrives with "a chatbot", "a productivity app", or nothing:
interview would draft a PRD around a solution nobody has a problem for.

A separate starter kit the owner maintains solves this with a three-act
questioning script (find a pain, deepen it, then scope). Its questioning
rules are good; its enforcement is prose. Its deepening gates — one
named user, the current way as ordered steps, frequency and minutes, a cause
reached by asking why at least three times, and something already tried —
are exactly the facts a PRD's users and current-state tables need, and
nothing checks whether they were actually filled.

## Decision

1. A new, optional first pipeline `/gatekit:discover` (`commands/discover.md`,
   skill `gatekit-discover`, ledger pipeline value `discover`) writes
   `spec/00-discovery.md` and nothing else.
2. The record carries one `gatekit-discovery` JSON fence (§6a). The six
   deepening gates (frequency and minutes count separately) are fields of that fence, and `spec.validate` checks
   them: a missing fence or empty problem sentence is `fail`; every unfilled
   gate is `warn`, with a distinct message when the record declares it in
   `unpassed`. The validator never fills a gate.
3. The file is optional in the strictest sense: its absence is silent, not a
   `warn`. `heading-map.json` gains `absent_ok` for this.
4. `interview` reads the fence as its primary source of facts, skips its
   open probe when the file exists, and turns every `unpassed` gate into an
   assumption ledger row. `interview` routes an argument with no real user
   and no pain to `discover`.
5. Discovery questions are plain chat, one per message, each with a
   recommended answer, budgeted by the command at three per gate. They are
   not `AskUserQuestion` calls and the question gate does not count them.
   Stop signals from `policy/questioning.md` apply unchanged.

## Consequences

- The questioning rules that make discovery work (past events only, a
  solution is not an answer, an abstraction is not an answer, the reverse
  "when did it go well" question, splitting failed attempts into failed and
  works-but-costly) live in one command file of about 150 lines. They are
  patterns rewritten for gatekit's format and language policy, not copied
  text.
- The gates become verifiable. A record that claims a cause after one
  "why", or that pads the chain by rewording the same link, shows up as
  `warn` — the reworded-link check is a word-overlap heuristic, which is the
  honest limit of a stdlib validator, and the command still requires the
  user to confirm the cause in their own words; a record that skipped frequency shows up as
  `warn` naming the gate; interview cannot read either as a fact without the
  ledger saying so.
- This is the first pipeline whose questions are unbudgeted by the hook.
  The per-gate budget is prose, which §0 says is not enforcement. The
  mitigation is structural rather than a new hook: the record is written
  after every gate, so a runaway interview still leaves a valid file, and
  the user can stop at any moment with a stop signal.
- `spec validate` grows one more check and the heading map one more file.
  Existing spec sets are unaffected because absence is silent; the fixture
  sets pass unchanged.
- The user manual's pipeline table gains a row 0. The pipeline diagram
  (`docs/assets/pipeline.svg`) is not updated by this ADR.
