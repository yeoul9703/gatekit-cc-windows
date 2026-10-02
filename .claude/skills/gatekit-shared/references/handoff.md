# Policy: handing off to the next skill

Read this at the last step of a `/gatekit-<name>` skill, right after its
report. The user may not know the order of the skills, so every skill ends
the same way: it says what comes next and offers to go there. The skill's
own last step adds only what is specific to it — the form of the question,
the next skill, and what "more work here" means.

## The rule

1. **Ask right after the report**, in `output_lang`, in the same turn. It is
   one question, a routing choice and not information-gathering; then stop
   and wait for the answer.
2. **Use the form your skill names** — an `AskUserQuestion` call or a plain
   chat message. This file does not change it. `AskUserQuestion` is never
   added to a skill's `allowed-tools` (see `questioning.md`), and
   `/gatekit-discover` never calls it.
3. **Offer these choices**, each with one line saying what it does:
   - **go on to the next skill** — name it the way it is typed,
     `/gatekit-<name>`, and say in a few plain words what it will do;
   - **more work here** — only when the skill has something to revise; its
     last step says what, and when it names nothing this choice is left out;
   - **stop here**.
4. **Going on means invoking the next skill**, not merely naming it.
5. **More work here**: do the work, run the skill's validation again, give
   the changed part of the report, and ask this question again.
6. **Stopping**: say which files are saved, with their paths, and which
   command to type later to continue. Then end the turn.
7. **When the condition in the table does not hold, do not offer to go on.**
   Say in plain words what is blocked — the failing check, the missing
   approval, the task that did not pass — and which command clears it. Offer
   that command if it is another skill; otherwise stop.
8. **When there is no next skill** (verification passed), say that the
   pipeline is finished and end without a question.

## What a handoff never does

- `/gatekit-gate` never approves for the user, and never hands off to
  `/gatekit-build` while `approve check` prints anything but `ok`.
- `/gatekit-build` never hands off while a task is `failed`, `stopped` or
  still `queued`. A build that passed is not a completion contract
  that passed; only `/gatekit-verify` reports that.
- `/gatekit-verify` never fixes what it finds. A failure goes back to
  `/gatekit-build`.
- `/gatekit-doctor` never runs a fix without asking, and never one that
  rewrites `spec/05-gate.md` or records an approval.
- No skill edits a file to make a check pass so that the handoff can happen.

## Which skill comes next

| Finished skill | Usual next | Condition, and what happens instead |
|---|---|---|
| `/gatekit-setup` | `/gatekit-interview` | The user can name what to build. If not: `/gatekit-discover`. Setup names the next command itself; if something is still missing it stays in setup. |
| `/gatekit-discover` | `/gatekit-interview` | `spec validate` is not `fail`. A confirmed verdict of `eliminate` or `reuse` blocks interview: offer a different opportunity instead. |
| `/gatekit-interview` | `/gatekit-mockup` | The project has screens. A PRD carrying the `[non-ui]` marker goes to `/gatekit-tasks` instead. `spec validate` is not `fail`. |
| `/gatekit-mockup` | `/gatekit-tasks` | The `Prototype confirmed <date>` line is written (not needed under `[non-ui]`). Unconfirmed: keep revising the prototype. `01-prd.md` still a draft: `/gatekit-interview` first. |
| `/gatekit-design` | `/gatekit-tasks` | Run mid-build with affected tasks: `/gatekit-tasks`, then `/gatekit-gate`, before building again. Otherwise, a project with screens and no `spec/02-screens.md` yet: `/gatekit-mockup` first, because tasks stops without it. |
| `/gatekit-tasks` | `/gatekit-gate` | `spec validate` is `ok` or `warn`. |
| `/gatekit-gate` | `/gatekit-build` | The user approved and `approve check` printed `ok`. Not approved: the write gate stays closed; say so and stop. |
| `/gatekit-build` | `/gatekit-verify` | Every task is `passed`. Otherwise name the tasks and the failing gate, and stay in build. |
| `/gatekit-verify` | none — finished | The aggregate is `ok` and no `-visual` verdict is `fail`. A failure: `/gatekit-build`. A stale contract: `/gatekit-tasks`, then `/gatekit-gate`. |
| `/gatekit-doctor` | the skill that owns the first axis not `ok` | python, uv: `/gatekit-setup`. Contract freshness: `/gatekit-tasks`, then `/gatekit-gate`. Spec set: the skill that writes the failing file. Every axis `ok`: nothing to hand off. |

The required path is `/gatekit-interview` → `/gatekit-tasks` →
`/gatekit-gate` → `/gatekit-build` → `/gatekit-verify`, with
`/gatekit-mockup` between interview and tasks for every project that has
screens. `/gatekit-discover` comes before interview only when the user does
not yet know what to build. `/gatekit-design` may run at any stage.
