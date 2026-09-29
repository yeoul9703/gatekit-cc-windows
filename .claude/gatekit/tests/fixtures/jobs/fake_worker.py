#!/usr/bin/env python3
"""Fake worker backend used by the jobs tests.

Reads the prompt on stdin, writes a file into its declared write scope, and
exits with a configurable code. Behaviour is driven entirely by environment
variables so one script can stand in for every scenario:

  FAKE_WORKER_OUT    path (relative to cwd) to create
  FAKE_WORKER_BODY   text to write into it (default: "ok")
  FAKE_WORKER_EXIT   exit code (default: 0)
  FAKE_WORKER_SLEEP  seconds to sleep before exiting (default: 0)
  FAKE_WORKER_ATTEMPT_FILE  counter file; when set, the Nth run writes
                     FAKE_WORKER_BODY only from attempt FAKE_WORKER_PASS_AT on
"""
import os
import sys
import time


def main():
    prompt = sys.stdin.read()
    sys.stderr.write("fake-worker: task=%s job=%s prompt=%d chars\n" % (
        os.environ.get("GATEKIT_TASK_ID", ""),
        os.environ.get("GATEKIT_JOB_ID", ""),
        len(prompt),
    ))

    attempt = 1
    counter = os.environ.get("FAKE_WORKER_ATTEMPT_FILE")
    if counter:
        try:
            with open(counter, "r", encoding="utf-8") as handle:
                attempt = int(handle.read().strip() or "0") + 1
        except (OSError, ValueError):
            attempt = 1
        with open(counter, "w", encoding="utf-8") as handle:
            handle.write(str(attempt))

    pass_at = int(os.environ.get("FAKE_WORKER_PASS_AT", "1"))
    body = os.environ.get("FAKE_WORKER_BODY", "ok")
    out = os.environ.get("FAKE_WORKER_OUT")
    if out and attempt >= pass_at:
        directory = os.path.dirname(out)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(body)

    sleep_s = float(os.environ.get("FAKE_WORKER_SLEEP", "0"))
    if sleep_s:
        time.sleep(sleep_s)

    sys.stdout.write("fake-worker report: attempt %d, wrote %s\n" % (attempt, out or "(nothing)"))
    sys.exit(int(os.environ.get("FAKE_WORKER_EXIT", "0")))


if __name__ == "__main__":
    main()
