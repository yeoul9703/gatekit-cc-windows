# Routing a failed build task

Read this when `/gatekit-build` has a task in `failed` or `timeout`. It is
not needed while every task passes.

## Decide first: is the code wrong, or the gate?

For every `failed` or `timeout` task, read the failing gate's output tail in
`gates.json` and decide **whether the code or the gate is wrong**. A gate names
files and commands that do not exist until the work is done, so narrowing one
mid-build is normal, not a mistake.

## The gate is wrong

Too broad, names a path the task never had to create, or fails the same way
regardless of the code: fix `spec/04-tasks.md`, then

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py jobs recheck <task_id>
```

which runs the new gate against existing code in seconds with no worker and
no new job. **Never redelegate or start a job for a gate edit** — on the
trial behind ADR-0013 that was 28 of 35 spawns.

## The code is wrong

Under `host`, fix it yourself and run `jobs complete <task_id>` again. Under
`worker`, run `jobs redelegate <task_id>`: it archives the attempt under
`attempt-N/`, appends the gate output to the prompt and re-runs. Exit 3
means out of retries (`build.max_retries`) and you do not retry past it.

## Out of retries

Consecutive failures bind across jobs by code (ADR-0014): `redelegate` and
`start` both refuse a task at `max_retries`, exit 3, naming the jobs it failed
in. On refusal, diagnose: read `spec/RECOVERY.md` and the task's `gates.json`,
write the diagnosis there under a heading naming the task (what gate fails,
what the output says, likely causes), then **stop the pipeline**. Once the
cause is fixed, `jobs start --force-retry <task_id>` clears its count — never
to route around a diagnosis you have not done.
