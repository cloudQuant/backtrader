"""Iteration 67 G8: Store-owned facade calendar configuration.

A borrowed facade or one returned by a caller factory can be shared, so it is
never rewritten.  Only a facade this Store created itself receives the exact
explicit route roots, once.
"""

from __future__ import annotations

import os

import pytest
import yaml

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="needs the CTP calendar provider")

from bt_api_py.bt_api import BtApi  # noqa: E402

from backtrader.stores import btapistore as store_module  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from tests.unit.feeds.test_btapifeed_trading_calendar import publish  # noqa: E402
from tests.unit.stores.test_iter67_trading_calendar_status import ROUTE  # noqa: E402


class FakeApi:
    def __init__(self):
        self.configurations = []

    def configure_trading_calendar_status(self, *, route_roots):
        self.configurations.append(dict(route_roots))

    def list_exchanges(self):
        return [ROUTE]


def make_store(monkeypatch, tmp_path, base, *, api=None, api_cls=None):
    (base / "calendars/ctp").mkdir(parents=True)
    publish(base / "calendars/ctp")
    config_file = base / "config.yaml"
    config_file.write_text(yaml.safe_dump({"calendars": {"root": "calendars"}}), encoding="utf-8")
    options = {}
    if api is not None:
        options["api"] = api
    elif api_cls is not None:
        options["api_cls"] = api_cls
    store = BtApiStore(
        config={"exchange_kwargs": {ROUTE: {}}},
        calendar_config_file=config_file,
        calendar_config={"calendars": {"root": "calendars"}},
        calendar_ctp_routes=(ROUTE,),
        **options,
    )
    return store, config_file


def test_owned_facade_is_configured_once_with_the_exact_route_roots(monkeypatch, tmp_path):
    store, config_file = make_store(monkeypatch, tmp_path, tmp_path)
    fake = FakeApi()
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: fake)
    store._api = fake
    store._started = store._connected = store._sdk_configured = True

    store._ensure_api_ready()
    expected = os.path.normpath(config_file.parent / "calendars/ctp")
    assert fake.configurations == [{ROUTE: expected}]
    store._ensure_api_ready()
    assert len(fake.configurations) == 1
    assert store._calendar_facade_configuration == "CONFIGURED"


def test_borrowed_facade_is_never_reconfigured(monkeypatch, tmp_path):
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()

    def forbidden(**kwargs):
        pytest.fail("a borrowed facade must never be reconfigured")

    monkeypatch.setattr(api, "configure_trading_calendar_status", forbidden)
    store, _config_file = make_store(monkeypatch, tmp_path, tmp_path, api=api)
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: api)
    store._api = api
    store._started = store._connected = store._sdk_configured = True
    store._ensure_api_ready()
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"


def test_custom_api_factory_is_not_proven_exclusive(monkeypatch, tmp_path):
    fake = FakeApi()
    store, _config_file = make_store(monkeypatch, tmp_path, tmp_path, api_cls=lambda: fake)
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: fake)
    store._api = fake
    store._started = store._connected = store._sdk_configured = True
    store._ensure_api_ready()
    assert fake.configurations == []


def test_two_borrowed_stores_keep_their_own_calendar_roots(monkeypatch, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    api = BtApi(debug=False)
    api.exchange_feeds[ROUTE] = object()
    calls = []
    original = api.configure_trading_calendar_status

    def record(*, route_roots):
        calls.append(dict(route_roots))
        original(route_roots=route_roots)

    monkeypatch.setattr(api, "configure_trading_calendar_status", record)
    store_a, _ = make_store(monkeypatch, tmp_path, first, api=api)
    store_b, _ = make_store(monkeypatch, tmp_path, second, api=api)
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: api)
    for store in (store_a, store_b):
        store._api = api
        store._started = store._connected = store._sdk_configured = True
        store._ensure_api_ready()
    assert calls == []
    assert api.trading_calendar_status(ROUTE).reason == "ROUTE_UNCONFIGURED"
    assert store_a.trading_calendar_status()["routes"][ROUTE].publication_id == "p1"


def test_facade_configuration_failure_stays_local_and_finite(monkeypatch, tmp_path):
    store, _config_file = make_store(monkeypatch, tmp_path, tmp_path)
    fake = FakeApi()

    def broken(**_kwargs):
        raise OSError("/private/secret")

    fake.configure_trading_calendar_status = broken
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: fake)
    store._api = fake
    store._started = store._connected = store._sdk_configured = True
    store._ensure_api_ready()
    assert store._calendar_facade_configuration == "FAILED"
    result = store.trading_calendar_status()
    assert result["status"] == "OBSERVED"
    assert result["sources"] == {ROUTE: "LOCAL_CONFIG"}
    assert "/private/secret" not in repr(result)
