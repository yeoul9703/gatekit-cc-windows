---
name: gatekit-setup
description: Initialize .gatekit/config.json and check worker backends. Korean triggers — "셋업 해줘", "초기 설정", "워커 확인해줘", "백엔드 설정". English triggers — "set up gatekit", "check my workers", "configure the backend". NOT for diagnosing a broken install — that is /gatekit:doctor — and NOT for enabling a bypass or unsandboxed backend, which gatekit refuses.
---

# gatekit-setup

Invoke `/gatekit:setup`.

Do not edit `.gatekit/config.json` by hand here. `.claude/commands/gatekit/setup.md` is
the execution instruction; this file only routes to it.

Enabling a backend is the user's decision, taken through the command's
`AskUserQuestion` step after it explains what the sandbox does. Never enable one
ahead of that answer.
