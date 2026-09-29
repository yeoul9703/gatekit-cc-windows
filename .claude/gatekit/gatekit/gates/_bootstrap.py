"""Make the ``gatekit`` package importable when a gate runs as a script.

Claude Code invokes gates as plain scripts:
``python3 "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/write.py"``. In that mode Python
puts ``gatekit/gates/`` on ``sys.path`` — not the plugin root — so ``import
gatekit`` fails and there is no PYTHONPATH to rely on.

Every gate calls :func:`ensure_package_path` before importing anything from the
package. The path is computed from ``__file__``, so the plugin works from
whatever directory it was installed or cached into.
"""
from __future__ import annotations

import os
import sys


def ensure_package_path() -> str:
    """Prepend the plugin root (the parent of ``gatekit/``) to ``sys.path``.

    Returns the directory that was added, for diagnostics. Idempotent: a
    repeated call will not add a duplicate entry.
    """
    here = os.path.dirname(os.path.abspath(__file__))          # …/gatekit/gates
    package_dir = os.path.dirname(here)                         # …/gatekit
    plugin_root = os.path.dirname(package_dir)                  # …/plugin
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    return plugin_root
