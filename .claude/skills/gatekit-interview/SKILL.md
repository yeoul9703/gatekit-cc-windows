---
name: gatekit-interview
description: Turn a rough product idea into a validated PRD and architecture spec with a labelled assumption ledger. Korean triggers — "기획해줘", "PRD 써줘", "요구사항 정리해줘", "뭘 만들지 정리하자", "스펙 만들어줘". English triggers — "write a PRD", "spec this out", "turn this idea into requirements", "plan what to build". NOT for writing code, and NOT for reading an existing design file — use gatekit-mockup for a Figma or HTML mockup.
---

# gatekit-interview

Invoke `/gatekit:interview` with the user's text as the argument.

Do not run the interview steps here. `.claude/commands/gatekit/interview.md` is the
execution instruction; this file only routes to it.

Pass the user's own wording through, unparaphrased — the command detects the
output language from it.

If the user already has a Figma file, HTML, or screenshots, route to
`/gatekit:mockup` instead.
