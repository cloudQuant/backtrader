"""CTP orders carry the venue the host configured (iteration 62, SimNow 2026-11-06).

On SimNow a restored waiting order was refused ``ctp_direct_exchange_id_required``:
on a flat account the Broker knew no venue yet, and the provider's catalog lookup
did not finish inside the order path. A venue configured in the Store's
``contract_metadata`` is now used until the venue reports one. UNIT/FAKE.
"""

import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import SYMBOL, T0, crash, window

HOUR = dt.timedelta(hours=1)


def _configure(env, **entry):
    env.store.contract_metadata = {SYMBOL: dict(entry, price_tick=1.0, multiplier=10)}


def _instrument_key(venue="SHFE"):
    return MarketInstrumentKey("ctp", venue, "demo", "future", SYMBOL, SYMBOL)


def _buy(env, broker):
    return broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def test_configured_instrument_key_venue_is_sent_before_the_venue_reports_one(env):
    _configure(env, instrument_key=_instrument_key())
    broker = env.start(first_init=True)
    assert broker.get_closable(env.feed, "long")["venue"] == "SHFE"  # close split known at once
    order = _buy(env, broker)
    assert order.status == bt.Order.Submitted, order.info.get("error_code")
    assert env.api.place_calls[-1].request.exchange_id == "SHFE"


def test_configured_exchange_entry_is_normalized(env):
    _configure(env, exchange="shfe")
    broker = env.start(first_init=True)
    _buy(env, broker)
    assert env.api.place_calls[-1].request.exchange_id == "SHFE"


def test_without_a_configured_venue_the_provider_still_resolves_it(env):
    broker = env.start(first_init=True)
    _buy(env, broker)
    assert env.api.place_calls[-1].request.exchange_id is None


def test_routes_without_offsets_are_not_seeded(env):
    _configure(env, instrument_key=_instrument_key())
    broker = env.start(first_init=True, require_offset=False)
    assert broker.get_closable(env.feed, "long")["venue"] is None
    broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit)
    assert env.api.place_calls[-1].request.exchange_id is None


def test_restored_waiting_order_is_dispatched_with_the_configured_venue(env, clock):
    _configure(env, instrument_key=_instrument_key())
    first = env.start(first_init=True)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + HOUR, T0 + 3 * HOUR)
    original = _buy(env, first)
    assert env.api.place_calls == []  # waiting for the next session
    crash(first)

    broker = env.start()  # a restart on a flat account: no venue report yet
    (restored,) = broker.get_restored_orders()
    assert restored.info["local_seq"] == original.info["local_seq"]
    broker.take_over_restored_orders(env.strategy)
    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    broker.next()
    (call,) = env.api.place_calls
    assert call.request.exchange_id == "SHFE"
    assert call.summary["local_seq"] == original.info["local_seq"]
