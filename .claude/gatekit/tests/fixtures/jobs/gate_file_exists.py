#!/usr/bin/env python3
"""Gate fixture: exits 0 iff every path given on argv exists under cwd."""
import os
import sys

missing = [p for p in sys.argv[1:] if not os.path.exists(p)]
if missing:
    sys.stderr.write("missing: %s\n" % ", ".join(missing))
    sys.exit(1)
sys.stdout.write("all %d path(s) present\n" % (len(sys.argv) - 1))
sys.exit(0)
