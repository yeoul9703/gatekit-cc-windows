# Policy: verification

## Never report from memory

A claim about the current state of the code is only reportable if you ran
something in this session and read the result. "It should work", "that fix
handles it", and "the tests pass" without a run are not findings.

If you did not run it, the verdict is `unverified`. Say so.

## Make the claim falsifiable first

Before verifying, write down the claim in a form that could come out false.

| Falsifiable | Not falsifiable |
|---|---|
| "`python3 -m unittest discover` exits 0" | "the tests are fine" |
| "GET /api/users returns 200 with a JSON array" | "the endpoint works" |
| "the empty state renders when the list has 0 items" | "the UI handles empty data" |

If you cannot state what result would prove the claim wrong, you are not
verifying, you are asserting.

## Baseline and treatment

One observation proves nothing about a change. Take two.

1. **Baseline** — run the check *before* the change, or on the unchanged path.
   Record the exact output.
2. **Treatment** — run the identical check after the change.
3. **Compare** — the difference between the two is the evidence. Same command,
   same environment, same input.

If the baseline already passed, the change did not fix anything and you are
looking at the wrong cause. If the baseline cannot be taken (the code did not
exist), say so and mark the result `unverified` for causation while `ok` for
current state.

## The four verdicts

| Verdict | Means | Requires |
|---|---|---|
| `ok` | The claim was tested and held | A run, its output, and the exit code |
| `warn` | It works, but something is off that a human should see | The observation and why it matters |
| `fail` | The claim was tested and did not hold | A run and the failing output |
| `unverified` | It was not tested, or the test could not conclude | What blocked it |

`unverified` never rounds to `ok` and never rounds to `fail`. A timeout, a
missing binary, a skipped test, and a check you ran out of budget for are all
`unverified`. Reporting one of them as a pass is the failure this policy exists
to prevent.

## What does not count as evidence

- A test that was skipped, marked `only`, or disabled to make the suite green
- A command that exited 0 while its declared artifact is missing
- Code that compiles or type-checks — that is not the same as behaving correctly
- A subagent's summary that you did not see the underlying output for
- A previous session's result

## Reporting

State the command, the observed result, and the verdict. Put the exact command
and any error text in a code block. When a check is `unverified`, say what
would make it verifiable — that sentence is the useful part of the report.
