---
name: gatekit-mockup
description: Read a Figma file, HTML page, or screenshots and derive a screen specification with per-screen states and design tokens, recording everything the mockup does not show as an assumption. Korean triggers — "피그마 보고 화면 명세 만들어줘", "목업에서 스펙 뽑아줘", "이 디자인 정리해줘", "화면 명세 써줘". English triggers — "spec these screens from Figma", "extract screens from this mockup", "turn this design into a screen spec". NOT for implementing the design as code, and NOT for writing the PRD — use gatekit-interview for requirements.
---

# gatekit-mockup

Invoke `/gatekit:mockup` with the user's Figma URL, file path, or screenshot
paths as the argument.

Do not read the mockup or extract anything here.
`.claude/commands/gatekit/mockup.md` is the execution instruction; this file only routes
to it.

If the user wants the design implemented as working code rather than specified,
this is not the right skill.
