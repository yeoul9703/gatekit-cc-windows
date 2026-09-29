# Notes app — task list

## Task list

```gatekit-task
{"id": "note-store", "title": "Note storage", "write_scope": ["src/store/**"],
 "instruction": "Write functions that persist and read notes from a file.",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": [], "round": 1}
```

```gatekit-task
{"id": "note-ui", "title": "Note list screen", "write_scope": ["src/ui/**"],
 "instruction": "Render the list by reading from the store.",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": ["note-store"], "round": 2}
```

## Execution order

| Round | Tasks | Why they can run together |
|---|---|---|
| 1 | note-store | No file overlap |
| 2 | note-ui | Depends on note-store |

## Scope rules

- Tasks in the same round must not share a write scope.
