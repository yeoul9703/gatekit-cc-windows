# Notes app — architecture

## Stack

| Layer | Choice | Why | Alternative and why not |
|---|---|---|---|
| Runtime | Python 3.11 | Standard library suffices | Node — more dependencies |

## Data model

### Note

| Field | Type | Required | Notes |
|---|---|---|---|
| id | string(uuid) | yes | Identifier |
| body | string | yes | Content |

## Identifiers and tokens

| Kind | Rule | Example |
|---|---|---|
| Files | kebab-case | note-store.py |

## External integrations

None.

## Constraints

- Must work without network access.
