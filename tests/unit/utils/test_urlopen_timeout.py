"""Network-robustness regression tests for the urlopen shim (iteration 12, S-2).

The ``backtrader.utils.py3.urlopen`` compatibility shim must apply a default
timeout so that data feeds do not hang indefinitely on an unresponsive remote
endpoint, while still letting callers override the timeout explicitly.
"""

from unittest import mock

import backtrader.utils.py3 as py3


def test_urlopen_applies_default_timeout():
    """When no timeout is supplied, the default timeout must be passed through."""
    with mock.patch.object(py3, "_urllib_request") as req:
        py3.urlopen("https://example.com/data.csv")
    _, kwargs = req.urlopen.call_args
    assert kwargs["timeout"] == py3._DEFAULT_URLOPEN_TIMEOUT


def test_urlopen_respects_explicit_timeout():
    """An explicit timeout must not be overridden by the default."""
    with mock.patch.object(py3, "_urllib_request") as req:
        py3.urlopen("https://example.com/data.csv", timeout=5)
    _, kwargs = req.urlopen.call_args
    assert kwargs["timeout"] == 5


def test_default_timeout_is_positive():
    """The default timeout must be a sane positive value."""
    assert py3._DEFAULT_URLOPEN_TIMEOUT > 0
