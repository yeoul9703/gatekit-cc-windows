---
name: gatekit-build
description: Run the tasks in spec/04-tasks.md as gated worker jobs — spawn a worker per task, let the gates decide pass or fail, redelegate failures up to the retry budget, then hand off to verify. Korean triggers — "빌드 시작해줘", "작업 실행해줘", "워커 돌려줘", "태스크 자동으로 만들어줘". English triggers — "build it", "run the tasks", "start the workers", "execute the task list". NOT for writing code directly in this session, NOT for judging whether the result is done — that is /gatekit:verify.
---

# gatekit-build

Invoke `/gatekit:build`, passing any task ids the user named as the argument.

Do not implement tasks here. `.claude/commands/gatekit/build.md` is the execution
instruction; this file only routes to it.

Two things the command enforces and this shim must not undercut: the main
session never edits a task's files while its job runs, and a worker's own
report never decides a verdict. The gates decide.
