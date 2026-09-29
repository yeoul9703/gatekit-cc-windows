# Notes app — completion gate

## Completion criteria

```gatekit-criterion
{"id": "note-store-tests", "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0}, "timeout_s": 30}
```

```gatekit-criterion
{"id": "note-ui-tests", "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0}, "timeout_s": 30}
```

## Not counted as done

- Tests made to pass by skipping them
- A criterion that timed out

## How evidence is collected

| Criterion | How it runs | Evidence left behind |
|---|---|---|
| note-store-tests | contract run | exit code |
