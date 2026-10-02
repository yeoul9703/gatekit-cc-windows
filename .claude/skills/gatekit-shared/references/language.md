# Policy: output language

## The rule

The output language is Korean, always: `output_lang` is `ko`. Nothing is
detected. A user who writes in English, or a spec that holds English text,
still gets Korean. `preamble.md` next to this file says the same for Step 0.

## What is written in Korean

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
it. This applies everywhere Korean applies, above.

## What never gets translated

Identifiers stay in their source form regardless of language:

| Never translate | Examples |
|---|---|
| File and directory names | `spec/01-prd.md`, `.gatekit/contract.json` |
| JSON keys | `write_scope`, `depends_on`, `timeout_s` |
| Fence names | ` ```gatekit-task `, ` ```gatekit-criterion ` |
| CLI commands and flags | `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate --json` |
| Verdict tokens in JSON | `ok`, `warn`, `fail`, `unverified` |
| Code symbols from the project | type names, function names, env vars |

Verdict tokens are localized only when rendered as prose for a human
(`verdict.render(v, lang)`). In any JSON output they stay English.

## Templates

Each skill that writes a spec file keeps its templates in its own `assets/`
folder (for example `.claude/skills/gatekit-interview/assets/01-prd.md`).
There is one set, in Korean. Fill it in Korean; a code word or a product name
in English inside a Korean sentence is fine.

## Checking your own output

Before writing a file under `spec/`, confirm its headings come from
`headings` in `.claude/skills/gatekit-shared/assets/heading-map.json`, exactly
as written there. A missing canonical heading is a hard `fail` in `spec
validate`, not a style issue: an English or reworded heading does not count
as the Korean one. A heading the list does not hold may be added.
