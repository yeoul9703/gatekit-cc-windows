# What the interview conversation itself pursues

Read by `/gatekit-interview` Step 2, alongside `.claude/skills/gatekit-shared/references/conversation.md`
(which governs *how* to ask). This file names *what* to ask about.

Ask in whatever order the conversation actually goes — follow the thread
the last answer opened, never a fixed checklist.

- **How many pages or screens does this need**, and what is each for? A
  todo app might be one; a multi-role tool several. Do not assume a number
  — ask, and let the answer shape everything after it.
- **For each page, what can a user actually do there** — every feature that
  lives on it, described as behavior ("registers a task, sees it appear in
  a list immediately"), not as a UI element name.
- **What does each feature need to work** — what information it reads, what
  it writes, what has to already exist for it to make sense (a user has to
  exist before a task can belong to them).
- **The unglamorous branches**: what happens when a list is empty, an
  action fails, two people try the same thing at once, something the user
  expects to see is missing. These keep surfacing new ground, not padding.
- **How each feature maps to actual behavior** — confirm the translation
  from "the feature exists" to "here is what happens when someone uses it"
  **in the same turn the feature comes up**, never as a later pass. A real
  trial skipped this and its own Assumption 4 recorded the result: "각
  단계를 어떤 화면 동작으로 옮길지는 인터뷰어가 정했고 사용자가 확인하지
  않았다" — a mapping decided silently reached the PRD as fact. A mapping
  obvious from what the user already said needs no separate question; one
  that is not gets however much back-and-forth it takes, in the moment.

**The checkpoint's specific gap, in this command, is a screen or branch the
conversation implies but never described** — a page a feature obviously
needs that nobody detailed, an error path never asked about. Name that when
asking whether to continue or write the design documents now.
