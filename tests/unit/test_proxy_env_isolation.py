# -*- coding: utf-8 -*-
"""Proxy-environment isolation regression tests (iteration-32 acceptance, F8).

``examples/013_1|013_2/ctp_example_support.py`` run ``load_dotenv`` at import
time, which copies a developer's ``.env`` proxy settings into ``os.environ``
and never restores them. Any later test in the same xdist worker that opens a
real socket then dials a proxy that is not running (``ConnectionRefusedError
[Errno 61]``). The ``isolate_proxy_environment`` autouse fixture in
``tests/conftest.py`` removes those variables before every test.

Verification recipe (repo root; the command fails without the fixture):

    HTTP_PROXY=http://127.0.0.1:15732 python -m pytest tests/unit/test_proxy_env_isolation.py -q
"""

import os
import urllib.request


def _proxy_like_vars():
    """Return sorted names of proxy-steering environment variables."""
    return sorted(
        name
        for name in os.environ
        if name.lower().endswith("_proxy") or name.lower() == "proxy_host"
    )


def test_proxy_variables_are_stripped_by_the_autouse_fixture():
    """No proxy variable survives into a test body."""
    assert _proxy_like_vars() == []


def test_urllib_environment_proxies_are_empty():
    """The stdlib environment proxy resolver agrees: sockets go direct."""
    assert urllib.request.getproxies_environment() == {}
