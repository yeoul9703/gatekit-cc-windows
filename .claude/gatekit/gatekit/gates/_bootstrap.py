"""Make the ``gatekit`` package importable when a gate runs as a script.

A gate can still be run as a plain script directly —
``python3 ".../gatekit/gates/write.py"`` — even though the standard path is
through ``bin/gatekit _gate write``. In script mode Python puts
``gatekit/gates/`` on ``sys.path`` — not the gatekit root — so ``import
gatekit`` fails and there is no PYTHONPATH to rely on.

Every gate calls :func:`ensure_package_path` before importing anything from the
package. The path is computed from ``__file__``, so this works regardless of
which of the two invocation styles is used.
"""
from __future__ import annotations

import os
import sys


def ensure_package_path() -> str:
    """Prepend the gatekit root (the parent of ``gatekit/``) to ``sys.path``.

    Returns the directory that was added, for diagnostics. Idempotent: a
    repeated call will not add a duplicate entry.
    """
    here = os.path.dirname(os.path.abspath(__file__))          # …/gatekit/gates
    package_dir = os.path.dirname(here)                         # …/gatekit
    gatekit_root = os.path.dirname(package_dir)                 # …/.claude/gatekit
    if gatekit_root not in sys.path:
        sys.path.insert(0, gatekit_root)
    return gatekit_root
