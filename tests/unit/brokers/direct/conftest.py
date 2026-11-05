"""Fixtures for BtApiBroker direct-mode unit tests (UNIT/FAKE evidence only)."""

import pytest


@pytest.fixture
def env(tmp_path):
    pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")
    from ._fakes import Env

    environment = Env(tmp_path)
    try:
        yield environment
    finally:
        environment.close()


@pytest.fixture
def clock(monkeypatch):
    """Controllable UTC clock for the waiting-order dispatcher."""
    from backtrader.brokers import _btapi_direct_mode as direct_mode

    from ._fakes import T0

    now = {"value": T0}
    monkeypatch.setattr(direct_mode, "_utc_now", lambda: now["value"])
    return now
