# Preamble: the first step of every /gatekit command

Every command's Step 0 points here. It settles one thing before anything
else happens: the language the user reads, called `output_lang` (`ko` or
`en`). Read `language.md` next to this file as well — it says what follows
the detected language and what is never translated.

## Detect `output_lang`

Each command names one of two sources.

**From the spec** — for commands that run once the PRD exists:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py lang --file spec/01-prd.md --lines 40
```

If `spec/01-prd.md` does not exist, or the command cannot run because uv or
the `.venv` is not there yet, use the language of the user's own message:
`ko` if it is Korean, else `en`.

**From the input** — for commands that start from the user's own words.
Write the command's input text verbatim to `.gatekit/runs/lang-input.txt`
with the Write tool, then run:

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py lang --file .gatekit/runs/lang-input.txt
```

The input goes through a file because it may hold quotes, `$` or backticks;
it never travels as a shell argument. If the input is empty, or is only a
URL or a path, detect from the user's surrounding message instead.

## Use it

- Every user-facing string from here on is written in `output_lang`.
  Identifiers are never translated.
- Each skill keeps its spec templates in its own `assets/<output_lang>/`
  folder; the skill's Step 0 names the files. If no folder matches, use `en`
  and say so once.
- Spec headings come verbatim from
  `.claude/skills/gatekit-shared/assets/heading-map.json[<output_lang>]`. Never mix two
  languages' headings in one file.
