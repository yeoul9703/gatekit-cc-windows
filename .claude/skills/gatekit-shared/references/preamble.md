# Preamble: the first step of every /gatekit command

Every command's Step 0 points here. It settles one thing before anything
else happens: the language the user reads, called `output_lang`. Read
`language.md` next to this file as well — it says what is written in that
language and what is never translated.

## `output_lang` is always `ko`

This repository is Korean-only. `output_lang` is `ko`, whatever language the
user wrote in and whatever the spec holds.

A command's Step 0 says to detect it **from the spec** or **from the
input**. Both give the same answer, `ko`. Do not run a detection command,
and do not write the input to a file for one.

## Use it

- Every user-facing string from here on is written in Korean. Identifiers
  are never translated.
- Each skill keeps its spec templates in its own `assets/` folder, one
  Korean set; the skill's Step 0 names the files.
- Spec headings come verbatim from `headings` in
  `.claude/skills/gatekit-shared/assets/heading-map.json`.
