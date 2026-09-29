---
title: "{{project_name}} — architecture"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — architecture

## Stack

| Layer | Choice | Why | Alternative and why not |
|---|---|---|---|
| Runtime | {{e.g. Node 20}} | {{why}} | {{what was rejected and why}} |
| Framework | {{}} | {{}} | {{}} |
| Storage | {{}} | {{}} | {{}} |
| Tests | {{}} | {{}} | {{}} |

Any choice the user has not confirmed goes in the assumption ledger.

> ⚠️ Assumption N: {{stack choice the user did not confirm}}

## Data model

Write identifiers exactly as they appear in code. Never translate them.

### {{EntityName}}

| Field | Type | Required | Notes |
|---|---|---|---|
| id | {{string(uuid)}} | yes | {{}} |
| {{field}} | {{}} | {{yes/no}} | {{}} |

Relationships: {{EntityA 1 — N EntityB}}

## Identifiers and tokens

Fix naming in one place. Tasks (04) follow these rules.

| Kind | Rule | Example |
|---|---|---|
| Files and directories | {{kebab-case}} | {{user-profile.ts}} |
| Types and classes | {{PascalCase}} | {{UserProfile}} |
| Functions and variables | {{camelCase}} | {{loadUserProfile}} |
| Environment variables | {{SCREAMING_SNAKE}} | {{DATABASE_URL}} |
| API routes | {{/api/<plural noun>}} | {{/api/users}} |

## External integrations

| Service | Purpose | Auth | Behaviour on failure |
|---|---|---|---|
| {{}} | {{}} | {{keys via environment only; never in code or logs}} | {{}} |

## Constraints

- {{Performance, security, compatibility, or regulatory limits that narrow the design.}}
- {{If there are none, say "none" explicitly.}}
