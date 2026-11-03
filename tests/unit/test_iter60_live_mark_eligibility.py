"""Iteration 60 (60.11-A5, re-verification F6): the trusted live valuation mark.

Contract (BT consumes SDK/Base facts only):

* every feed in the valuation offers ``valuation_mark()`` (``BtApiFeed``) and is
  bound to the same Store - the same account/provider route - as the
  strategy's Broker (``STRATEGY_MARK_ROUTE_UNBOUND``);
* the value on the lines is a provider-final bar (``bar_final=True``), a bar
  this feed closed from typed, quality-checked ticks, or, on a Tick
  timeframe, one eligible typed tick; replayed bars and values built from
  legacy (untyped) ticks are refused (``MARK_SOURCE_UNTRUSTED``);
* it carries its provider event time (bar close / tick event time) and
  ``now - event time <= Strategy.strategy_mark_max_age_seconds`` (default
  5 s), with ``now`` from the feed's injected clock (``MARK_STALE``,
  ``MARK_FROM_FUTURE``).

Historical data on a BackBroker keeps its previous rules (other module).
"""

from __future__ import annotations

import collections
import datetime as dt
import itertools
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed, _tick_mark_source  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    DirectStrategyAccountBookView,
)
from tests.unit import test_iter60_target_orders_scope as scope  # noqa: E402

T0 = dt.datetime(2026, 11, 3, 9, 0)  # bar open (UTC); closes at 09:01
CLOSE = T0 + dt.timedelta(minutes=1)


class _Store:
    """Stands for one Store (account/provider route); never started here."""

    def poll_live(self, *_args, **_kwargs):
        return None

    def has_pending_live_bar(self, *_args):
        return False


ROUTE = _Store()


class _Clock:
    def __init__(self, wall):
        self.wall = wall

    def time_ns(self):
        return int(self.wall.replace(tzinfo=dt.timezone.utc).timestamp() * 1_000_000_000)

    def monotonic_ns(self):
        return 1


def _new_feed(name, timeframe, wall, store):
    clock = _Clock(wall)
    feed = BtApiFeed(dataname=name, store=None, timeframe=timeframe, compression=1, clock=clock)
    feed.store = store  # bound route; the feed is never started in these tests
    feed._name = name
    feed.lines.datetime.forward()
    for line in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(feed.lines, line).forward()
    return feed, clock


def _feed(
    name="X",
    *,
    close=100.0,
    final=True,
    when=T0,
    wall=CLOSE + dt.timedelta(seconds=1),
    store=ROUTE,
    source=None,
):
    feed, clock = _new_feed(name, bt.TimeFrame.Minutes, wall, store)
    bar = {
        "datetime": when,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
        "openinterest": 0.0,
        "bar_final": final,
    }
    if source is not None:
        bar["bar_source"] = source
    feed._live = collections.deque([bar])
    feed._load()
    return feed, clock


def _tick(quality="GOOD", flags=(), when=T0):
    return SimpleNamespace(
        price=101.0,
        volume=2.0,
        timestamp=when.replace(tzinfo=dt.timezone.utc).timestamp(),
        datetime=when.replace(tzinfo=dt.timezone.utc),
        bar_eligible=True,
        quality=quality,
        quality_flags=tuple(flags),
    )


def _tick_feed(tick, *, wall=T0 + dt.timedelta(seconds=1), store=ROUTE):
    feed, clock = _new_feed("X", bt.TimeFrame.Ticks, wall, store)
    feed.p.dispatch_bars = False
    feed._ingest_tick(tick)
    assert feed._load() is True
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
    assert as_of == CLOSE.replace(tzinfo=dt.timezone.utc)  # the bar close (event time)


def test_stale_mark_is_refused_by_absolute_age():
    feed, clock = _feed()
    clock.wall = T0 + dt.timedelta(minutes=5)  # bar closed 4 minutes ago (> 60 s + 2 s)
    assert _code(feed.valuation_mark) == "MARK_STALE"
    feed.valuation_mark_max_age = 600.0
    assert feed.valuation_mark()[0] == Decimal("100.0")


def test_caller_bound_only_tightens_the_feed_bound():
    feed, clock = _feed()
    clock.wall = CLOSE + dt.timedelta(seconds=10)
    assert feed.valuation_mark()[0] == Decimal("100.0")  # feed default: 62 s
    assert _code(lambda: feed.valuation_mark(max_age=5.0)) == "MARK_STALE"
    assert feed.valuation_mark(max_age=3600.0)[0] == Decimal("100.0")
    clock.wall = CLOSE + dt.timedelta(seconds=120)
    assert _code(lambda: feed.valuation_mark(max_age=3600.0)) == "MARK_STALE"
    for bad in (-1.0, float("nan"), float("inf"), True, "x"):
        assert _code(lambda: feed.valuation_mark(max_age=bad)) == "MARK_AGE_INVALID"


def test_mark_from_the_future_is_refused():
    feed, clock = _feed()
    clock.wall = T0  # the bar would close a minute from now
    assert _code(feed.valuation_mark) == "MARK_FROM_FUTURE"


def test_unfinished_or_unknown_finality_bars_give_no_mark():
    feed, _clock = _feed(final=False)  # the feed never publishes it
    assert _code(feed.valuation_mark) == "MARK_NOT_PUBLISHED"
    feed, _clock = _feed(final=None)  # no completion claim: not published either
    assert _code(feed.valuation_mark) == "MARK_NOT_PUBLISHED"
    assert feed.bar_integrity_counts()["unknown_finality"] == 1


def test_lines_not_holding_the_published_bar_give_no_mark():
    feed, _clock = _feed()
    feed.lines.close[0] = 999.0  # something else overwrote the line
    assert _code(feed.valuation_mark) == "MARK_NOT_PUBLISHED"


@pytest.mark.parametrize("source", ["replay", "local_aggregation_legacy", "legacy_tick", "other"])
def test_untrusted_line_sources_give_no_mark(source):
    feed, _clock = _feed(source=source)
    assert _code(feed.valuation_mark) == "MARK_SOURCE_UNTRUSTED"


def test_local_bar_source_follows_tick_typing_and_replay():
    from backtrader.feeds.btapifeed import _local_bar_source

    good = SimpleNamespace(quality="GOOD", quality_flags=())
    legacy = SimpleNamespace(quality="GOOD", quality_flags=("LEGACY_SCHEMA",))
    replay = SimpleNamespace(replay_bar_status="fixture_projection")
    assert _local_bar_source(good) == "local_aggregation"
    assert _local_bar_source(legacy) == "local_aggregation_legacy"
    assert _local_bar_source(SimpleNamespace()) == "local_aggregation_legacy"
    assert _local_bar_source(replay) == "replay"


def test_eligible_typed_tick_is_a_mark_at_its_event_time():
    feed, clock = _tick_feed(_tick())
    price, as_of, source = feed.valuation_mark(max_age=5.0)
    assert (price, source) == (Decimal("101.0"), "market_tick")
    assert as_of == T0.replace(tzinfo=dt.timezone.utc)
    clock.wall = T0 + dt.timedelta(seconds=6)
    assert _code(lambda: feed.valuation_mark(max_age=5.0)) == "MARK_STALE"


@pytest.mark.parametrize(
    "quality,flags", [("GOOD", ("LEGACY_SCHEMA",)), ("INVALID", ()), (None, ())]
)
def test_legacy_or_unqualified_tick_is_not_a_mark(quality, flags):
    assert _tick_mark_source(_tick(quality, flags)) == "legacy_tick"
    feed, _clock = _tick_feed(_tick(quality, flags))
    assert _code(feed.valuation_mark) == "MARK_SOURCE_UNTRUSTED"


# -- strategy valuation on live data, any Broker -----------------------------------


def _live_strategy(ledger, totals, datas, *, route=ROUTE):
    broker = scope._AccountBroker()  # not BackBroker: provenance comes from the feeds
    broker.store = route
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


def test_live_target_value_uses_a_fresh_final_bar(book):
    feed, _clock = _feed()
    strategy, orders = _live_strategy(*book, [feed])
    strategy.order_target_value(data=feed, target=300.0)  # holds 2 * 100 = 200
    assert orders == [("buy", 1.0)]


def test_live_target_percent_uses_a_fresh_eligible_tick(book):
    feed, _clock = _tick_feed(_tick())
    strategy, orders = _live_strategy(*book, [feed])
    # Equity = cash 19800 + 2 * 101; 10 % of it = 2000.2; holds 202 -> buy 17 (rounded).
    strategy.order_target_percent(data=feed, target=0.1)
    assert len(orders) == 1 and orders[0][0] == "buy"
    assert orders[0][1] == pytest.approx((0.1 * (19800 + 202) - 202) / 101, abs=1)


def test_f6_counterexample_single_very_old_bar_is_refused(book):
    """Re-verification F6: one ancient synthetic bar must never produce an order."""

    old = dt.datetime(2001, 1, 2, 9, 0)
    feed, _clock = _feed(when=old)  # published, final, but 25 years old against the clock
    strategy, orders = _live_strategy(*book, [feed])
    for call in (
        lambda: strategy.order_target_value(data=feed, target=300.0),
        lambda: strategy.order_target_percent(data=feed, target=0.5),
    ):
        with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
            call()
    assert orders == []


def test_default_strategy_bound_is_tighter_than_one_bar(book):
    feed, clock = _feed()
    clock.wall = CLOSE + dt.timedelta(seconds=30)  # within the feed's 62 s, beyond 5 s
    strategy, orders = _live_strategy(*book, [feed])
    assert strategy.strategy_mark_max_age_seconds == 5.0
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_value(data=feed, target=300.0)
    strategy.strategy_mark_max_age_seconds = 60.0  # explicit opt-in to slower data
    strategy.order_target_value(data=feed, target=300.0)
    assert orders == [("buy", 1.0)]


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), None, True, "5"])
def test_invalid_live_mark_age_is_refused(book, bad):
    feed, _clock = _feed()
    strategy, orders = _live_strategy(*book, [feed])
    strategy.strategy_mark_max_age_seconds = bad
    with pytest.raises(ValueError, match="STRATEGY_MARK_AGE_INVALID"):
        strategy.order_target_value(data=feed, target=300.0)
    assert orders == []


def test_live_target_value_refuses_a_stale_feed_mark(book):
    feed, clock = _feed()
    clock.wall = T0 + dt.timedelta(hours=1)
    strategy, orders = _live_strategy(*book, [feed])
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_value(data=feed, target=300.0)
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_percent(data=feed, target=0.5)
    assert orders == []


@pytest.mark.parametrize("feed_route,broker_route", [(None, ROUTE), (ROUTE, None), (ROUTE, "x")])
def test_feed_not_bound_to_the_broker_route_is_refused(book, feed_route, broker_route):
    feed, _clock = _feed(store=feed_route)
    strategy, orders = _live_strategy(*book, [feed], route=broker_route)
    with pytest.raises(ValueError, match="STRATEGY_MARK_ROUTE_UNBOUND"):
        strategy.order_target_value(data=feed, target=300.0)
    assert orders == []


def test_second_feed_on_another_route_is_refused(tmp_path):
    ledger, totals = scope._ledger(tmp_path, holdings={"A": {"X": 2, "Y": 1}})
    try:
        x, _ = _feed("X")
        y, _ = _feed("Y", store=_Store())
        strategy, orders = _live_strategy(ledger, totals, [x, y])
        with pytest.raises(ValueError, match="STRATEGY_MARK_ROUTE_UNBOUND"):
            strategy.order_target_value(data=x, target=300.0)
        assert orders == []
    finally:
        ledger.close()


def test_untrusted_source_is_refused_by_the_strategy(book):
    feed, _clock = _feed(source="replay")
    strategy, orders = _live_strategy(*book, [feed])
    with pytest.raises(ValueError, match="STRATEGY_MARK_SOURCE_UNTRUSTED"):
        strategy.order_target_value(data=feed, target=300.0)
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


def test_zero_target_still_closes_without_any_mark(book):
    feed, clock = _feed()
    clock.wall = T0 + dt.timedelta(days=30)
    strategy, orders = _live_strategy(*book, [feed])
    strategy.__dict__["close"] = lambda **kw: orders.append(("close", None)) or "order"
    strategy.order_target_value(data=feed, target=0.0)
    assert orders == [("close", None)]
