---
title: "{{project_name}} — screen specification"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — screen specification

Source: {{Figma URL · HTML file · screenshot filenames · interview}}

## Screen list

| Screen ID | Name | Feature | Evidence |
|---|---|---|---|
| S1 | {{screen name}} | F1 | {{which mockup frame, or "assumed"}} |

## Screen flow

Entry points and movement between screens. Any transition not shown in the
mockup becomes an assumption-ledger row.

```
{{entry point}} → S1 → S2
                  └→ (error) S3
```

| From | Action | To | Evidence |
|---|---|---|---|
| S1 | {{button or link label}} | S2 | {{mockup frame, or assumption N}} |

## Per-screen states

Every screen lists all four states. States the mockup does not show must still
be designed here, and that gap recorded in the assumption ledger.

### S1 — {{screen name}}

| State | What the user sees | Evidence |
|---|---|---|
| Normal | {{with data present}} | {{mockup frame}} |
| Empty | {{zero-item message and the next action offered}} | {{mockup or assumption N}} |
| Error | {{what went wrong, what the user can do}} | {{mockup or assumption N}} |
| Loading | {{skeleton, spinner, or optimistic update}} | {{mockup or assumption N}} |

## Components

| Component | Used on | Variants | Evidence |
|---|---|---|---|
| {{e.g. PrimaryButton}} | S1, S2 | {{default / disabled / loading}} | {{mockup component name}} |

## Design tokens

Machine-readable values live in `spec/tokens.json`; keep only a summary here.

| Group | Token | Value |
|---|---|---|
| Color | {{color.primary}} | {{#000000}} |
| Spacing | {{space.md}} | {{16px}} |
| Type | {{font.body}} | {{16px / 1.5}} |

## Negative space

State what the mockup does **not** cover. An empty list here means the mockup
was not read closely enough.

- {{e.g. no screen covers the offline state}}
- {{e.g. no screen covers a user without permission}}
- {{e.g. no pagination once the list passes 100 items}}
