"""Orders on data that cannot report a trade qualification are never sent (iteration 62).

The direct Broker reads ``data.trade_qualification()`` (BtApiFeed contract,
D62-15a/15b/21/27) before it dispatches an order.  A data object without that
contract -- e.g. the example strategies' ``PlaceholderData`` used while a feed
has no line yet, which since 2026-11-06 is priced from the strategy's tracked
tick price -- proves nothing about LIVE status or clock quality, so its order
is refused locally instead of being sent unchecked.  UNIT/FAKE.
"""

import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import SYMBOL, T0, make_feed, not_qualified, window

HOUR = dt.timedelta(hours=1)


class _UnqualifiableData:
    """A data stand-in with a symbol and a current bar but no trade qualification."""

    def __init__(self, symbol, feed):
        self._name = str(symbol)
        self._feed = feed

    def __len__(self):
        return len(self._feed)

    def __getattr__(self, name):
        if name in ("trade_qualification", "historical_warmup_active"):
            raise AttributeError(name)
        return getattr(self._feed, name)


def _buy(env, broker, data):
    return broker.buy(
        env.strategy, data, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def test_data_without_trade_qualification_is_refused_locally(env):
    broker = env.start(first_init=True)
    not_qualified(env.feed)  # the real feed of the same instrument is not tradable
    order = _buy(env, broker, _UnqualifiableData(SYMBOL, env.feed))
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "target_data_unqualified"
    assert env.api.place_calls == []


def test_a_plain_feed_without_the_contract_is_refused_locally(env):
    broker = env.start(first_init=True)
    plain = make_feed()
    del plain.trade_qualification  # make_feed attaches the BtApiFeed contract
    order = _buy(env, broker, plain)
    assert order.info["error_code"] == "target_data_unqualified"
    assert env.api.place_calls == []


def test_a_missing_qualification_object_is_refused_locally(env):
    broker = env.start(first_init=True)
    env.feed.trade_qualification = lambda: None
    order = _buy(env, broker, env.feed)
    assert order.info["error_code"] == "target_data_unqualified"
    assert env.api.place_calls == []


def test_unqualifiable_data_never_creates_a_waiting_order(env):
    broker = env.start(first_init=True)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + HOUR, T0 + 3 * HOUR)
    order = _buy(env, broker, _UnqualifiableData(SYMBOL, env.feed))
    assert order.info["error_code"] == "target_data_unqualified"
    assert env.state().waiting.active() == []


def test_waiting_order_is_not_dispatched_once_its_data_reports_no_qualification(env, clock):
    broker = env.start(first_init=True)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + HOUR, T0 + 3 * HOUR)
    order = _buy(env, broker, env.feed)
    assert order.info["waiting_session"] is True
    env.feed.trade_qualification = lambda: None  # no qualification object at dispatch time
    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    broker.next()
    assert env.api.place_calls == []  # still waiting, never sent unchecked
    assert order.status == bt.Order.Submitted


def test_qualified_feed_is_still_sent(env):
    broker = env.start(first_init=True)
    order = _buy(env, broker, env.feed)
    assert order.status == bt.Order.Submitted
    assert len(env.api.place_calls) == 1
