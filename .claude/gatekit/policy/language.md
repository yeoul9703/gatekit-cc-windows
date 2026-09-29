# Policy: output language

## The rule

Detect the language for **this** call. Never carry a language over from a
previous session, and never default to Korean.

```
".claude/gatekit/bin/gatekit" lang "<the user's own words>"
```

The result is `ko` or `en`. Use the user's text, not your own paraphrase, as
the input. When a session ledger already holds an `output_lang` for this
session, prefer that value — the prompt gate recorded it from the same rule.

## What follows the detected language

Everything the user reads:

- chat replies
- headings and body text of files written under `spec/`
- `AskUserQuestion` question text, option labels, and option descriptions
- verdict explanations and error messages you surface

## What never reaches the user at all

Internal rule names — ADR numbers, decision numbers, fence field names like
`pain_floor_waived`, policy file names — are comments for whoever reads this
command's source, not vocabulary for the person being interviewed. Never say
"ADR-0017," "decision 4," "branch floor," or similar in a chat reply,
`AskUserQuestion` text, or a written spec file's prose. If a question needs
justifying, justify it in terms of the problem itself ("한두 개만으로는 뭐가
진짜 문제인지 판단하기 어려워서요"), never by citing the rule that produced
it. This applies everywhere the detected language applies, above.

## What never gets translated

Identifiers stay in their source form regardless of language:

| Never translate | Examples |
|---|---|
| File and directory names | `spec/01-prd.md`, `.gatekit/contract.json` |
| JSON keys | `write_scope`, `depends_on`, `timeout_s` |
| Fence names | ` ```gatekit-task `, ` ```gatekit-criterion ` |
| CLI commands and flags | `".claude/gatekit/bin/gatekit" spec validate --json` |
| Verdict tokens in JSON | `ok`, `warn`, `fail`, `unverified` |
| Code symbols from the project | type names, function names, env vars |

Verdict tokens are localized only when rendered as prose for a human
(`verdict.render(v, lang)`). In any JSON output they stay English.

## Templates

`plugin/spec-kit/templates/ko/` and `.../en/` exist. For a detected language
that is neither, use the `en` templates and say once, in the user's language:
"gatekit has no template set for this language yet, so the English structure is
used; the content is written in your language." Do not repeat that notice on
later steps in the same session.

## Mixed input

A prompt that mixes scripts follows the detector's threshold: Hangul at 30% or
more of the letters counts as `ko`. Do not override the detector because a
technical term appeared in English — code words in a Korean sentence are still
a Korean sentence.

## Checking your own output

Before writing a file under `spec/`, confirm its headings come from the
matching language block of `plugin/spec-kit/heading-map.json`. Mixing headings
from both languages in one file is a hard `fail` in `spec validate`, not a
style issue.
