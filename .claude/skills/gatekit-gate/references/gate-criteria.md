# Writing completion criteria

Read this in `/gatekit-gate` before deriving criteria (Step 2) and before
writing the "not counted as done" section (Step 3).

## One criterion

Each is a ` ```gatekit-criterion ` fence holding one JSON object:

```json
{"id": "task-one-works", "argv": ["python3", "-m", "unittest", "discover", "-k", "task_one"],
 "expect": {"exit": 0}, "timeout_s": 30, "artifacts": []}
```

Requirements:

- `id` unique, and containing the task id it verifies so traceability holds
- `argv` a non-empty list of strings, run without a shell — no `&&`, no pipes,
  no redirection. Chain steps by adding more criteria instead.
- `timeout_s` realistic. The run-wide budget defaults to 45 seconds; if the
  criteria together need more, add one `gatekit-budget` fence declaring
  `total_budget_s` (ceiling 600). Measure first, then declare — never raise a
  budget to hide a slow test you have not looked at
- `artifacts` only for files the command genuinely produces. A declared
  artifact that does not appear is a `fail`, so do not declare aspirational ones.
- `expect` beyond `exit` when the exit code alone can lie. A test runner that
  reports skips still exits 0, so pin it: `"expect": {"exit": 0,
  "stdout_not_contains": ["skipped", "SKIP"]}`. `stdout_contains`,
  `stdout_regex` and the `stderr_*` forms exist too; every unknown key is a
  derive error, so spell them exactly.

## The screenshot criterion (ADR-0017 decision 9)

For every task in 04 whose `write_scope` touched a UI surface, add one more
criterion whose `argv` runs the project's E2E runner (`npx playwright test`
unless `spec/03-architecture.md` names a different one already in use)
against a spec that navigates to the task's screen and saves
`spec/design/build-<task-id>.png`, and whose `artifacts` names that same
path:

```json
{"id": "task-one-screenshot", "argv": ["npx", "playwright", "test", "e2e/screenshot-task-one.spec.ts"],
 "expect": {"exit": 0}, "timeout_s": 30, "artifacts": ["spec/design/build-task-one.png"]}
```

Write the actual Playwright spec file this `argv` runs — like every other
criterion it must be runnable here right now, not a guess. If the project
has no E2E runner at all, that setup is the task's own responsibility; do
not derive a criterion whose `argv` cannot run yet. gatekit installs at most
the Node.js runtime itself (see "When the program an `argv` starts is
missing" below); what lives inside the project — `@playwright/test`, its
browsers, anything `npm install` brings — stays the task's work.
**Never substitute an
MCP browser tool call for the `argv`** — `contract.py` runs criteria with
`subprocess.run`, and `mcp__*` tools exist only inside an agent session. On
a host with no browser the `argv` fails to launch and `contract.py` reports
`unverified`, never a fabricated pass; that is the correct outcome.

## Run it before writing it in

Every criterion must be **runnable in this repository right now**. Run each
one before writing it in — an unexecuted criterion is a guess, and the Stop
hook will run it for real. Read the output, not only the exit code:
`node --test <directory>` and `gates/tokens.py <directory>` both "run" and
both are wrong (the first loads the directory as a module, the second scans
zero files and exits 3). Use glob patterns (`tests/rules/*.test.js`).

## When the program an `argv` starts is missing

A criterion can fail before its command starts: the shell says the name is
not recognized, and `contract run` reports `unverified` with
`could not execute`. That is a missing program, not a failing criterion.

gatekit handles one case, Node.js (`npx`, `node`, `npm`), and only when the
project runs on it: `spec/03-architecture.md` names Node.js as the runtime,
or an `argv` you derived starts with one of those three names. For any
other stack, ask nothing and install nothing: name the missing program and
leave that criterion out.

Do these four in order:

1. **Tell.** Run the check below and read its `S18` item, then say in
   `output_lang` what is missing and what it is for. (Korean: "완료 기준을
   돌려 보려면 Node.js가 필요한데 이 PC에 없습니다.")

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Status -Json -Lang <output_lang>
   ```

2. **Ask.** In a plain chat message, ask whether to install it, and wait
   for the answer. Say that a Windows administrator prompt may appear and
   can hide behind other windows. (Korean: "설치해도 될까요? 설치 중에
   Windows 관리자 확인 창이 뜰 수 있고, 다른 창 뒤에 숨을 수 있습니다.")
   A permission window from Claude Code is not this yes.
3. **Install**, only after a yes, and only this name:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install node -Json -Lang <output_lang>
   ```

   Exit code 3: it is installed but not visible in this session. The user
   closes Claude Code completely, opens it again and types `/gatekit-gate`
   again. An `S16-node` item: the install failed. Show its hints and stop.
4. **Run the criterion again**, and write it in only when it runs.

Without a yes, or after a failed install, do not install it another way and
do not write a criterion that cannot run: tell the user that the criteria
which start Node.js wait until it is installed.

## The "not counted as done" section

This section is the point of the file. Write the conditions that make a
plausible-looking pass invalid, at minimum:

- tests passing because they were skipped, disabled, or narrowed — and where
  the runner prints skips, make that a criterion with `stdout_not_contains`
  rather than only a sentence here
- a criterion that timed out, which is `unverified` and never a pass
- a command exiting 0 with its declared artifact absent
- a UI task's screenshot criterion coming back `unverified` (no browser, no
  E2E runner) being reported as if the screen were confirmed working — it
  means nobody, human or reviewer, has actually looked at it yet
- **a feature whose own tests pass while nothing on a real screen reaches
  it.** A real trial shipped three features this way: each had passing
  tests and none was wired into the page. So for a UI-bearing project,
  cover the wiring itself with at least one criterion that drives the app
  end to end — open the screen, act on it, assert the result — rather than
  trusting per-feature tests to imply it
- TODOs, stubs, or empty implementations left behind
- editing this file to remove a failing criterion
- reporting success without having run anything

Add project-specific ones from the constraints in `spec/03-architecture.md`.
