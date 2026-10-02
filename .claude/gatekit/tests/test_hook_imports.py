"""A hook has about 150 ms. Importing a gate must not pull in the heavy modules.

Each gate is imported in a fresh interpreter and ``sys.modules`` is read right
after the import. A module a gate needs only on one branch (a lazy import inside
a function) is fine: it is not loaded by the import itself.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1]

GATES = ("prompt", "write", "bash", "powershell", "spawn", "release", "skill", "stop", "compact")

#: gatekit modules a gate must never load at import time (the job commands, the
#: spec checker, the doctor, design, the CLI).
HEAVY_GATEKIT = ("gatekit.jobs", "gatekit.spec", "gatekit.doctor",
                 "gatekit.design", "gatekit.cli")

#: Standard-library modules that cost milliseconds and that no gate needs on import.
HEAVY_STDLIB = ("subprocess", "argparse", "tempfile", "shutil")


def loaded_after_import(gate: str) -> list:
    code = ("import json, sys; sys.path.insert(0, %r); import gatekit.gates.%s; "
            "print(json.dumps(sorted(sys.modules)))") % (str(KIT), gate)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=60, cwd=str(KIT))
    if out.returncode != 0:
        raise AssertionError("importing gatekit.gates.%s failed:\n%s" % (gate, out.stderr))
    return json.loads(out.stdout)


class TestGateImports(unittest.TestCase):
    def test_no_gate_loads_a_heavy_module(self) -> None:
        for gate in GATES:
            with self.subTest(gate=gate):
                loaded = set(loaded_after_import(gate))
                self.assertEqual(sorted(loaded & set(HEAVY_GATEKIT)), [], gate)
                self.assertEqual(sorted(loaded & set(HEAVY_STDLIB)), [], gate)


if __name__ == "__main__":
    unittest.main()
