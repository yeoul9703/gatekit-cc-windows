---
name: gatekit-gate
description: Turn acceptance criteria and tasks into executable completion criteria, then pin them with a hash-anchored approval so the build gate opens and Stop enforces them. Korean triggers — "완료 기준 정해줘", "게이트 만들어줘", "언제 끝난 건지 정의해줘", "DoD 만들어줘". English triggers — "define done", "set the completion gate", "write the acceptance gate", "definition of done". NOT for running the criteria after the fact — that is /gatekit:verify — and NOT for approving on the user's behalf.
---

# gatekit-gate

Invoke `/gatekit:gate` with any extra criteria the user named as the argument.

Do not derive or approve criteria here. `.claude/commands/gatekit/gate.md` is the
execution instruction; this file only routes to it.

Approval is always the user's action, taken through the command's
`AskUserQuestion` step. Never record an approval without it.
