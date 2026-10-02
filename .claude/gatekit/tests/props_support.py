"""Shared setup for the property tests (``test_*_props.py``).

hypothesis lives in the uv dev group, which a user's machine never installs
(``default-groups = []``). A property module imports everything hypothesis
from here, so it still imports without the package and its classes skip:

    from tests.props_support import HAVE_HYPOTHESIS, given, settings, st, requires_hypothesis

    @requires_hypothesis
    class TestSomething(unittest.TestCase):
        @given(st.text())
        @settings(max_examples=EXAMPLES, deadline=None)
        def test_it(self, text): ...

``GATEKIT_PROPS_EXAMPLES`` sets how many inputs each property tries: 100 by
default (seconds), 10000 for the occasional deep run (minutes).
"""
from __future__ import annotations

import os
import unittest

try:
    from hypothesis import HealthCheck, assume, example, given, settings
    from hypothesis import strategies as st

    HAVE_HYPOTHESIS = True
except ImportError:  # the dev group is not installed: every property class skips
    HAVE_HYPOTHESIS = False

    def _passthrough(*_args, **_kwargs):
        def wrap(function):
            return function

        return wrap

    given = settings = example = _passthrough  # type: ignore[assignment]

    def assume(_condition) -> bool:  # type: ignore[misc]
        return True

    class _Anything:
        """Stands in for ``hypothesis.strategies`` and ``HealthCheck`` at import time."""

        def __getattr__(self, _name):
            return self

        def __call__(self, *_args, **_kwargs):
            return self

        def __or__(self, _other):
            return self

        def __iter__(self):
            return iter(())

    st = HealthCheck = _Anything()  # type: ignore[assignment]

try:
    EXAMPLES = max(1, int(os.environ.get("GATEKIT_PROPS_EXAMPLES", "100")))
except ValueError:
    EXAMPLES = 100

requires_hypothesis = unittest.skipUnless(
    HAVE_HYPOTHESIS, "hypothesis is not installed (uv sync --frozen --group dev)")

__all__ = ["EXAMPLES", "HAVE_HYPOTHESIS", "HealthCheck", "assume", "example", "given",
           "requires_hypothesis", "settings", "st"]
