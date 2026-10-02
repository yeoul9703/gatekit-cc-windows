# Routing a failed build task

Read this when `/gatekit-build` has a task in `failed`. It is not needed
while every task passes.

## Decide first: is the code wrong, or the gate?

For every `failed` task, read the failing gate's output tail in
`gates.json` and decide **whether the code or the gate is wrong**. A gate names
files and commands that do not exist until the work is done, so narrowing one
mid-build is normal, not a mistake.

## The gate is wrong

Too broad, names a path the task never had to create, or fails the same way
regardless of the code: fix `spec/04-tasks.md`, then

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs recheck <task_id>
```

which runs the new gate against existing code in seconds, with no new job
and no attempt counted. **Never start a job for a gate edit** — on the trial
behind ADR-0013 that was 28 of 35 task runs.

## The code is wrong

Fix it yourself, inside the task's write scope, and run
`jobs complete <task_id>` again. Every failed `complete` counts: `jobs status`
shows the count as `(N consecutive)`. When it reaches `max_retries` (under
`build` in `.gatekit/config.json`; 2 when the file or the key is absent), do
not try again; go to the next section.

## Out of retries

Consecutive failures bind across jobs by code (ADR-0014): `jobs start`
refuses a task whose consecutive failures have reached `max_retries`. It
exits 3 and prints the task, the count and `max_retries` (not the job ids).
At the limit, diagnose: read `spec/RECOVERY.md` and the task's `gates.json`,
write the diagnosis there under a heading naming the task (what gate fails,
what the output says, likely causes), then **stop the pipeline**. Once the
cause is fixed, `jobs start --force-retry <task_id>` clears its count — never
to route around a diagnosis you have not done.
