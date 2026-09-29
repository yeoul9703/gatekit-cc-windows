---
name: gatekit-tasks
description: Break an existing spec into vertical-slice tasks with non-overlapping write scopes, dependency rounds, and a gate command each. Korean triggers — "작업 나눠줘", "태스크로 쪼개줘", "할 일 목록 만들어줘", "작업 분해해줘". English triggers — "break this into tasks", "split the work", "make a task list from the spec", "decompose into work items". NOT for executing the tasks — that is /gatekit:build — and NOT for writing the spec itself.
---

# gatekit-tasks

Invoke `/gatekit:tasks` with any constraints the user mentioned as the
argument.

Do not decompose anything here. `.claude/commands/gatekit/tasks.md` is the execution
instruction; this file only routes to it.

The command requires `spec/01-prd.md` to exist. If it does not, route to
`/gatekit:interview` first.
