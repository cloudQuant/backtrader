#!/usr/bin/env python
"""Smoke tests for backtrader version metadata.

Verifies __version__/__btversion__ are exposed, consistent with each other and
with the top-level backtrader namespace.
"""

import backtrader as bt
from backtrader import version as ver


def test_version_string_present():
    assert isinstance(ver.__version__, str)
    assert ver.__version__  # non-empty


def test_btversion_tuple_matches_string():
    assert isinstance(ver.__btversion__, tuple)
    assert all(isinstance(part, int) for part in ver.__btversion__)
    assert ver.__btversion__ == tuple(int(x) for x in ver.__version__.split("."))


def test_exposed_at_top_level():
    assert bt.__version__ == ver.__version__
    assert bt.__btversion__ == ver.__btversion__
