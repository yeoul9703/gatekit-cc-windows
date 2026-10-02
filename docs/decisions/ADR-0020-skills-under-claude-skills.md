# ADR-0020: Each pipeline is a skill folder under `.claude/skills`

Status: accepted 2026-10-02. Supersedes ADR-0019 decision 1 (the entry
points move from `.claude/commands/gatekit/` to `.claude/skills/`) and
changes the paths in its decisions 3 to 5; the single preamble and the
rare-path split of ADR-0019 stay.

## Context

ADR-0019 made the command file the one entry point per pipeline and kept
what a command reads in two kernel folders: `policy/` (shared rules) and
`spec-kit/` (templates, the heading map, presets, and eight reference docs).
Three things were wrong with that layout.

- **The material sat far from its user.** Everything in `spec-kit` belongs
  to one pipeline or another: `00-discovery.md` is discover's template,
  `gate-criteria.md` is read only by gate, `design-antipatterns.json` only
  by verify's evaluator. The folder name said nothing about that, and a
  reader had to open every command to learn which file fed which pipeline.
- **Setup read `docs/`.** The rare paths of setup (reinstall, retry, winget
  error codes, a broken CLI) lived in `docs/SETUP-REFERENCE.md`, a Korean
  document written for people to copy commands from. The model was told to
  read sections of it, so one file served two readers and could be tuned for
  neither.
- **The layout matched no convention.** The skill-creator guide describes
  one shape for exactly this: a folder with `SKILL.md` (the entry point,
  under 500 lines, loaded when the skill triggers), `references/` (docs
  loaded only when needed), `assets/` (files used in the output) and
  `scripts/`. `SKILL.md` names each reference together with when to read it.

ADR-0019 stayed with commands for one reason: the name. The probe of
2026-09-30 showed that a project skill is listed under its folder name and
cannot carry a colon, so moving to skills renames `/gatekit:<name>` to
`/gatekit-<name>`. On 2026-10-02 the user decided that this repository only
has to be consistent with itself, not with the upstream plugin's names, which
removes that reason. The same probe rules out the two alternatives: a nested
`.claude/skills/gatekit/<name>/SKILL.md` is not listed at all, and unprefixed
folders `doctor` and `setup` collide with built-in commands.

## Decision

1. **One skill folder per pipeline**: `.claude/skills/gatekit-<name>/` for
   the ten pipelines (discover, interview, mockup, design, tasks, gate,
   build, verify, doctor, setup). The folder name is the invocation name,
   `/gatekit-<name>`, and the frontmatter `name`. The `/gatekit:<name>`
   spelling is not used anywhere outside ADR-0001 to ADR-0019, which are
   records of their time.
2. **Inside a skill folder**: `SKILL.md` (frontmatter `name`, `description`,
   `allowed-tools`, and `argument-hint` where the skill takes input; the description keeps the triggers and
   the boundary of ADR-0019 decision 2), `references/` for what one step
   reads only when it needs it, `assets/` for templates
   (`assets/<output_lang>/<file>.md`) and data.
3. **`.claude/skills/gatekit-shared/` holds what several skills use** and is
   not a skill: it has no `SKILL.md`, so Claude Code does not list it.
   `references/` carries the former policy files (the preamble that every
   Step 0 names, language, questioning, conversation, assumptions,
   verification); `assets/` carries `heading-map.json` and
   `presets/design/*.json`, which the kernel reads too.
4. **Three folders are gone**: `.claude/commands/gatekit/`,
   `.claude/gatekit/policy/` and `.claude/gatekit/spec-kit/`. The kernel
   finds the moved data through `paths.skills_root()` and
   `paths.skill_dir(name)`.
5. **Who reads which document.**

   | Location | Reader | Holds |
   |---|---|---|
   | `SKILL.md` | the model | step order, safety rules, the next command |
   | `references/` | the model | detail for one step; the first lines say when to read it |
   | `assets/` | the model and the kernel | templates, presets, JSON data |
   | `gatekit-shared/` | the model and the kernel | rules and data several skills use |
   | `docs/` | people | usage, setup reference, architecture, decisions |

   A `SKILL.md` or a reference doc never names a `docs/` file as something
   to read. It may tell the user that a guide exists.
6. **Setup is split along the same line.** `gatekit-setup/SKILL.md` keeps
   the steps and every safety rule (install only after a yes in the chat, a
   reinstall or a retry is a separate permission, no bypass flag).
   `references/install-programs.md` is read before the install question,
   `references/settings.md` when `S12-settings` fails, and
   `references/rare-paths.md` for reinstall, retry, winget error codes and a
   CLI that cannot start. `docs/SETUP-REFERENCE.md` stays as the document a
   person copies commands from.
7. **`.claude/gatekit/scripts/` does not move.** `setup.ps1` is setup's
   script by nature, but `session-check.ps1` is called by a hook,
   `common.ps1` is shared by both and `verify.ps1` is for developers. Moving
   them would change the hook paths in `settings.json`, doctor's file checks
   and many tests for no gain.
8. **Tests follow the layout.** `tests/test_command_docs.py` checks the ten
   skills and the shared folder, that the replaced folders hold no files,
   that `name` equals the folder name, the description rules, the preamble
   in every Step 0, that every `.claude/skills/...` path a doc names exists
   (with `<output_lang>` resolved to `ko` and `en`), that no doc names a
   `docs/` path or the colon spelling, and the invocation form and bash-only
   syntax across every `SKILL.md` and `references/**/*.md`.

## Consequences

- The names users type change from `/gatekit:<name>` to `/gatekit-<name>`.
  Material written for the upstream plugin no longer matches letter for
  letter.
- Everything a pipeline uses sits in one folder, and a reference doc can be
  written for the model alone.
- The kernel now reads data from outside its own folder
  (`.claude/skills/gatekit-shared/assets/`), so the two trees must be
  copied together.
- A skill can be loaded by the model without the user typing its name. The
  prompt gate records the active pipeline from the typed prompt only; whether
  a `Skill` tool call needs its own hook is not decided here.
- Paths inside ADR-0005, 0008, 0009, 0012 and 0017 describe the old folders
  and are left as they were written.

## Not decided here

- The name `gatekit` itself: the skill prefix, the kernel folder
  `.claude/gatekit/` and the state folder `.gatekit/` stay.
- Recording the active pipeline when the model loads a skill on its own (see
  Consequences).
