"""Iteration 67 G3: Store attaches the configured provider status port.

UNIT/FAKE only: a real Store, a real published fixture calendar and a fake SDK
coordinator whose port reads a synthetic provider view.  No account, network,
native callback or order is used.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
pytest.importorskip("bt_api_ctp", reason="needs the CTP provider")

from bt_api_ctp.instrument_status_observation import (  # noqa: E402
    RECEIVE_CLOCK_MONOTONIC_NS,
    InstrumentStatusLedger,
    InstrumentStatusSessionFacts,
    project_native_instrument_status,
)
from bt_api_py.bt_api import BtApi  # noqa: E402
from bt_api_py.instrument_status_composition import (  # noqa: E402
    STATE_TRADABLE,
    InstrumentStatusObservationPort,
)

from backtrader.stores import btapistore as store_module  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from tests.unit.feeds.test_btapifeed_trading_calendar import MONDAY, publish  # noqa: E402

ROUTE = "CTP___FUTURE"
OTHER = "OTHER___FUTURE"
VENUE = "XSH"
PRODUCT = "cu"
CONTRACT = "cu2601"
KIND = "future"
GENERATION = "1"
IN_WINDOW = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)


class FakeCoordinator:
    def __init__(self, ports):
        self._ports = ports
        self.calls = []

    def instrument_status_port(self, route):
        self.calls.append(route)
        return self._ports.get(route)


class FakeReader:
    def __init__(self, view=None, *, error=None):
        self.view = view
        self.error = error
        self.scopes = []

    def __call__(self, venue, symbol):
        self.scopes.append((venue, symbol))
        if self.error is not None:
            raise self.error
        return self.view


def current_view(status="2"):
    fields = {
        "ExchangeID": VENUE,
        "ExchangeInstID": CONTRACT,
        "InstrumentID": CONTRACT,
        "InstrumentStatus": status,
        "TradingSegmentSN": 1,
        "EnterTime": "09:00:00",
        "EnterReason": "1",
    }
    observation = project_native_instrument_status(
        fields,
        session=InstrumentStatusSessionFacts(
            session_generation=GENERATION,
            trading_day=MONDAY.strftime("%Y%m%d"),
            source_sequence=1,
            receive_clock_domain=RECEIVE_CLOCK_MONOTONIC_NS,
            receive_time=1001,
            source_available=True,
        ),
    )
    assert observation.accepted is True
    ledger = InstrumentStatusLedger(
        session_generation=GENERATION, trading_day=MONDAY.strftime("%Y%m%d")
    )
    assert ledger.observe(observation).applied is True
    return ledger.view(VENUE, CONTRACT)


def make_store(
    monkeypatch,
    tmp_path,
    *,
    routes=(ROUTE,),
    local_routes=(ROUTE,),
    with_calendar=True,
    ports=None,
    write_admission=True,
):
    root = tmp_path / "calendars/ctp"
    publish(root)
    api = BtApi(debug=False)
    api.exchange_feeds.update({route: object() for route in routes})
    coordinator = FakeCoordinator(
        ports
        if ports is not None
        else {
            route: InstrumentStatusObservationPort(FakeReader(current_view())) for route in routes
        }
    )
    monkeypatch.setattr(api, "direct_writes", lambda: coordinator)
    config = {"exchange_kwargs": {route: {} for route in routes}}
    if write_admission:
        config["write_admission"] = dict.fromkeys(routes, True)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"calendars": {"root": "calendars"}}), encoding="utf-8")
    kwargs = {}
    if with_calendar:
        kwargs = {
            "calendar_config_file": config_file,
            "calendar_config": {"calendars": {"root": "calendars"}},
            "calendar_ctp_routes": local_routes,
        }
    store = BtApiStore(api=api, config=config, **kwargs)
    monkeypatch.setattr(store_module, "_ensure_store_api_ready", lambda *a, **k: api)
    store._api = api
    store._started = store._connected = store._sdk_configured = True
    return store, api, coordinator


def scope(store, **overrides):
    values = {
        "route": ROUTE,
        "venue": VENUE,
        "kind": KIND,
        "product": PRODUCT,
        "instrument": CONTRACT,
        "trading_day": MONDAY,
        "session_generation": GENERATION,
        "at": IN_WINDOW,
    }
    values.update(overrides)
    return store.instrument_status(**values)


def test_configured_route_attaches_the_provider_port(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(monkeypatch, tmp_path)
    assert store.instrument_status_source_configured() is False
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is True
    assert coordinator.calls == [ROUTE]
    result = scope(store)
    assert (result.state, result.observation_state, result.source) == (
        STATE_TRADABLE,
        "CURRENT",
        "OBSERVATION",
    )
    assert result.authorizes_trading is False


def test_absent_calendar_configuration_keeps_the_gate_inert(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(monkeypatch, tmp_path, with_calendar=False)
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is False
    assert coordinator.calls == []


def test_mixed_configured_and_unconfigured_routes_do_not_half_attach(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(
        monkeypatch, tmp_path, routes=(ROUTE, OTHER), local_routes=(ROUTE,)
    )
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is False
    assert coordinator.calls == []


def test_provider_without_the_capability_keeps_the_gate_inert(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(monkeypatch, tmp_path, ports={ROUTE: None})
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is False
    assert coordinator.calls == [ROUTE]


def test_non_direct_write_store_does_not_construct_a_provider(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(monkeypatch, tmp_path, write_admission=False)
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is False
    assert coordinator.calls == []


def test_explicit_port_is_not_replaced_by_the_route_wiring(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(
        monkeypatch, tmp_path, ports={ROUTE: InstrumentStatusObservationPort(FakeReader(None))}
    )
    explicit = InstrumentStatusObservationPort(FakeReader(current_view("6")))
    store.configure_instrument_status_port(explicit)
    store._ensure_api_ready()
    assert coordinator.calls == []
    result = scope(store)
    assert (result.state, result.observation_state) == ("CLOSED", "CURRENT")


def test_a_port_that_cannot_answer_is_an_explicit_absence(monkeypatch, tmp_path):
    store, _api, _coordinator = make_store(
        monkeypatch,
        tmp_path,
        ports={ROUTE: InstrumentStatusObservationPort(FakeReader(error=RuntimeError("private")))},
    )
    store._ensure_api_ready()
    assert store.instrument_status_source_configured() is True
    result = scope(store)
    # Calendar alone may open the session, but never as an observation.
    assert result.observation_state == "ABSENT"
    assert result.source == "CALENDAR"


def test_wiring_is_idempotent_and_keeps_the_same_ports(monkeypatch, tmp_path):
    store, _api, coordinator = make_store(monkeypatch, tmp_path)
    store._ensure_api_ready()
    first = dict(store._instrument_status_ports)
    store._ensure_api_ready()
    assert coordinator.calls == [ROUTE]
    assert store._instrument_status_ports == first
