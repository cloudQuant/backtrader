"""Iteration 60 (60.11-A5, re-verification F6): a source-bound live valuation mark.

``BtApiFeed.valuation_mark()`` returns the close of the final bar that feed
itself published, only while that close is not older than its absolute max
age against the feed's wall clock. A ledger-bound strategy values live data
only through it (on any Broker); historical data keeps the BackBroker rules.
"""

from __future__ import annotations

import collections
import datetime as dt
import itertools
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    DirectStrategyAccountBookView,
)
from tests.unit import test_iter60_target_orders_scope as scope  # noqa: E402

T0 = dt.datetime(2026, 11, 3, 9, 0)  # bar open (UTC); closes at 09:01


class _Clock:
    def __init__(self, wall):
        self.wall = wall

    def time_ns(self):
        return int(self.wall.replace(tzinfo=dt.timezone.utc).timestamp() * 1_000_000_000)

    def monotonic_ns(self):
        return 1


def _feed(name="X", *, close=100.0, final=True, wall=T0 + dt.timedelta(minutes=1, seconds=1)):
    clock = _Clock(wall)
    feed = BtApiFeed(
        dataname=name, store=None, timeframe=bt.TimeFrame.Minutes, compression=1, clock=clock
    )
    feed._name = name
    feed.lines.datetime.forward()
    for line in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(feed.lines, line).forward()
    bar = {
        "datetime": T0,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
        "openinterest": 0.0,
        "bar_final": final,
    }
    feed._live = collections.deque([bar])
    feed._load()
    return feed, clock


def _code(call):
    with pytest.raises(ValueError) as raised:
        call()
    return getattr(raised.value, "code", str(raised.value))


# -- the feed contract -----------------------------------------------------------


def test_fresh_final_bar_is_an_eligible_mark():
    feed, _clock = _feed()
    price, as_of, source = feed.valuation_mark()
    assert price == Decimal("100.0") and source == "provider_bar"
    assert as_of == dt.datetime(2026, 11, 3, 9, 1, tzinfo=dt.timezone.utc)  # the bar close


def test_stale_mark_is_refused_by_absolute_age():
    feed, clock = _feed()
    clock.wall = T0 + dt.timedelta(minutes=5)  # bar closed 4 minutes ago (> 60 s + 2 s)
    assert _code(feed.valuation_mark) == "MARK_STALE"
    feed.valuation_mark_max_age = 600.0
    assert feed.valuation_mark()[0] == Decimal("100.0")


def test_mark_from_the_future_is_refused():
    feed, clock = _feed()
    clock.wall = T0  # the bar would close a minute from now
    assert _code(feed.valuation_mark) == "MARK_FROM_FUTURE"


def test_unfinished_or_unpublished_bars_give_no_mark():
    feed, _clock = _feed(final=False)  # the feed never publishes it
    assert _code(feed.valuation_mark) == "MARK_NOT_PUBLISHED"


def test_lines_not_holding_the_published_bar_give_no_mark():
    feed, _clock = _feed()
    feed.lines.close[0] = 999.0  # something else overwrote the line
    assert _code(feed.valuation_mark) == "MARK_NOT_PUBLISHED"


def test_tick_timeframe_has_no_valuation_mark():
    feed = BtApiFeed(dataname="X", store=None, timeframe=bt.TimeFrame.Ticks)
    assert _code(feed.valuation_mark) == "MARK_TIMEFRAME_UNSUPPORTED"


# -- strategy valuation on live data, any Broker -----------------------------------


def _live_strategy(ledger, totals, datas):
    broker = scope._AccountBroker()  # not BackBroker: provenance comes from the feeds
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = datas
    cerebro.datasbyname = {data._name: data for data in datas}
    with OwnerContext.set_owner(cerebro):
        strategy = scope._Strategy.__new__(scope._Strategy)
    strategy.datas = datas
    strategy.data = datas[0]
    strategy.account_book = DirectStrategyAccountBookView(
        ledger.reader("A", account_positions=lambda: scope._report(totals))
    )
    orders = []
    strategy.__dict__["buy"] = lambda **kw: orders.append(("buy", kw["size"])) or "order"
    strategy.__dict__["sell"] = lambda **kw: orders.append(("sell", kw["size"])) or "order"
    return strategy, orders


@pytest.fixture
def book(tmp_path):
    ledger, totals = scope._ledger(tmp_path, holdings={"A": {"X": 2}})
    try:
        yield ledger, totals
    finally:
        ledger.close()


def test_live_target_value_uses_the_feed_mark(book):
    feed, _clock = _feed()
    strategy, orders = _live_strategy(*book, [feed])
    strategy.order_target_value(data=feed, target=300.0)  # holds 2 * 100 = 200
    assert orders == [("buy", 1.0)]


def test_live_target_value_refuses_a_stale_feed_mark(book):
    feed, clock = _feed()
    clock.wall = T0 + dt.timedelta(hours=1)
    strategy, orders = _live_strategy(*book, [feed])
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_value(data=feed, target=300.0)
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_percent(data=feed, target=0.5)
    assert orders == []


def test_mixing_a_feed_without_the_contract_is_refused(tmp_path):
    ledger, totals = scope._ledger(tmp_path, holdings={"A": {"X": 2, "Y": 1}})
    try:
        feed, _clock = _feed("X")
        strategy, orders = _live_strategy(ledger, totals, [feed, scope._Data("Y")])
        with pytest.raises(ValueError, match="STRATEGY_MARK_PROVENANCE_UNAVAILABLE"):
            strategy.order_target_value(data=feed, target=300.0)
        assert orders == []
    finally:
        ledger.close()


def test_plain_live_feed_without_the_contract_is_still_refused(book):
    class _LiveData(scope._Data):
        def islive(self):
            return True

    strategy, orders = _live_strategy(*book, [_LiveData("X")])
    with pytest.raises(ValueError, match="STRATEGY_MARK_PROVENANCE_UNAVAILABLE"):
        strategy.order_target_value(data=strategy.data, target=300.0)
    assert orders == []
