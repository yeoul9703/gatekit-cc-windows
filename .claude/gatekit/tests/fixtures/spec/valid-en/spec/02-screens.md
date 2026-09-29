# Notes app — screen specification

## Screen list

| Screen ID | Name | Feature | Evidence |
|---|---|---|---|
| S1 | Note list | F1 | Mockup frame List |

## Screen flow

| From | Action | To | Evidence |
|---|---|---|---|
| S1 | New note | S1 | Mockup frame List |

## Per-screen states

### S1 — Note list

| State | What the user sees | Evidence |
|---|---|---|
| Normal | The list of notes | Mockup |
| Empty | Prompt to write the first note | Assumed |
| Error | Save failure with retry | Assumed |
| Loading | Skeleton rows | Assumed |

## Components

| Component | Used on | Variants | Evidence |
|---|---|---|---|
| NoteRow | S1 | default | Mockup |

## Design tokens

| Group | Token | Value |
|---|---|---|
| Color | color.primary | #111111 |

## Negative space

- No screen covers the offline state.

Prototype confirmed 2026-09-19
