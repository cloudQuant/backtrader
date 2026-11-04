"""Iteration 60.11: target orders and Sizers use strategy scope, or refuse.

The book under test is the product chain, not a stand-in: an SDK
``SqliteStrategyLedger`` with strategy capital -> ``StrategyLedgerReader``
reconciled with an ``AccountPositionReport`` -> ``DirectStrategyAccountBookView``
bound to the Strategy. Spot instrument ``X`` quoted in CNY, multiplier 1,
price 100. The Broker's account value/cash is 1,000,000 and is never used for
a bound strategy (acceptance report 2026-11-03 F6 / G1, 60.11-A1..A7, A10).
"""

from __future__ import annotations

import itertools
import math
import time
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402
from backtrader.position import Position  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    DirectStrategyAccountBookView,
)
from backtrader.sizers.fixedsize import FixedSize  # noqa: E402
from backtrader.sizers.percents_sizer import (  # noqa: E402
    AllInSizer,
    AllInSizerInt,
    PercentSizer,
    PercentSizerInt,
)
from bt_api_py.strategy_ledger import (  # noqa: E402
    AccountPositionReport,
    InstrumentTerms,
    LedgerIntent,
    SqliteStrategyLedger,
    StrategyBudget,
    StrategyCapital,
)

ACCOUNT = "acct-60-11"
BAR = 739000.375  # one Backtrader bar time (days)


class _Line:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, index):
        return self.value


class _Data:
    def __init__(self, name, price=100.0, bar=BAR):
        self._name = name
        self.close = _Line(price)
        self.datetime = _Line(bar)

    def __len__(self):
        return 1

    def islive(self):
        return False


class _AccountBroker(bt.BrokerBase):
    """Account scope: 5 units of every instrument, 1,000,000 cash and value."""

    def __init__(self, *, stocklike=True, mult=1.0):
        super().__init__()
        self.setcommission(
            commission=0.0, stocklike=stocklike, mult=mult, margin=None if stocklike else 10.0
        )

    def getposition(self, data, side=None, **kwargs):
        return Position(size=5.0, price=100.0)

    @property
    def positions(self):
        return {}

    def getcash(self):
        return 1_000_000.0

    def getvalue(self, datas=None):
        return 1_000_000.0


class _Strategy(bt.Strategy):
    pass


class _CountingReader:
    def __init__(self, reader):
        self.reader = reader
        self.strategy_ref = reader.strategy_ref
        self.account_ref = reader.account_ref
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        return self.reader.snapshot()


def _ledger(tmp_path, *, holdings, capital="20000", terms=None, fee=None):
    """Ledger where each strategy bought ``holdings[ref][instrument]`` at 100."""

    terms = terms or {}
    instruments = {
        name: terms.get(name, InstrumentTerms(Decimal("1"), "CNY", "spot"))
        for held in holdings.values()
        for name in held
    }
    instruments.setdefault("X", InstrumentTerms(Decimal("1"), "CNY", "spot"))
    ledger = SqliteStrategyLedger(
        tmp_path / "ledger.sqlite3",
        account_ref=ACCOUNT,
        instruments=instruments,
        # Opening always needs a budget (G4); wide so other rules are tested.
        budgets={ref: StrategyBudget(Decimal("1000000000"), "CNY") for ref in holdings},
        capital=(
            {ref: StrategyCapital(Decimal(capital), "CNY") for ref in holdings}
            if capital is not None
            else None
        ),
    )
    totals = {}
    for ref, held in holdings.items():
        for name, units in held.items():
            intent = f"{ref}-{name}"
            ledger.reserve(LedgerIntent(intent, ref, name, "BUY", Decimal(units), Decimal("100")))
            ledger.apply_execution(
                intent,
                cumulative_quantity=Decimal(units),
                average_price=Decimal("100"),
                **(fee or {}),
            )
            totals[name] = totals.get(name, Decimal("0")) + Decimal(units)
    return ledger, totals


def _report(totals, **kwargs):
    return AccountPositionReport(
        ACCOUNT, "provider:sim", kwargs.get("observed_ns", time.time_ns()), True, totals
    )


def _make(ledger=None, totals=None, *, ref="A", datas=None, reconciled=True, **broker_kwargs):
    # The existing valuation tests exercise the built-in historical simulator,
    # not a fake live broker that cannot prove mark provenance.
    broker = bt.brokers.BackBroker()
    stocklike = broker_kwargs.get("stocklike", True)
    broker.setcommission(
        commission=0.0,
        stocklike=stocklike,
        mult=broker_kwargs.get("mult", 1.0),
        margin=None if stocklike else 10.0,
    )
    broker.getposition = lambda data, side=None, **kwargs: Position(size=5.0, price=100.0)
    broker.getcash = lambda: 1_000_000.0
    broker.getvalue = lambda datas=None: 1_000_000.0
    datas = datas or [_Data("X")]
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = datas
    cerebro.datasbyname = {data._name: data for data in datas}
    with OwnerContext.set_owner(cerebro):
        strategy = _Strategy.__new__(_Strategy)
    strategy.datas = datas
    strategy.data = datas[0]
    reader = None
    if ledger is not None:
        source = (lambda: _report(totals)) if reconciled else None
        reader = _CountingReader(ledger.reader(ref, account_positions=source))
        strategy.account_book = DirectStrategyAccountBookView(reader)
    orders = []
    strategy.__dict__["sell"] = lambda **kw: orders.append(("sell", kw["size"])) or "order"
    strategy.__dict__["buy"] = lambda **kw: orders.append(("buy", kw["size"])) or "order"
    return strategy, orders, reader


@pytest.fixture
def shared(tmp_path):
    """A owns 2, B owns 3 of X (account 5); each strategy has 20,000 capital."""

    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2}, "B": {"X": 3}})
    try:
        yield ledger, totals
    finally:
        ledger.close()


# -- A1/A2: target value --------------------------------------------------------------


def test_target_value_uses_the_strategy_position_value(shared):
    a, orders, _ = _make(*shared)
    a.order_target_value(data=a.data, target=300.0)  # A holds 2 * 100 = 200
    assert orders == [("buy", 1.0)]  # not "sell 2" from the account's 500


def test_target_value_reduces_only_the_strategy_position(shared):
    a, orders, _ = _make(*shared)
    a.order_target_value(data=a.data, target=100.0)
    assert orders == [("sell", 1.0)]


def test_zero_target_closes_only_the_strategy_position(shared, tmp_path):
    a, orders, _ = _make(*shared)
    a.order_target_value(data=a.data, target=0.0)
    assert orders == [("sell", 2.0)]
    # A flat while B holds 3: nothing to close, no valuation needed.
    flat, flat_orders, _ = _make(*shared, ref="C")
    assert flat.order_target_value(data=flat.data, target=0.0) is None
    assert flat.order_target_percent(data=flat.data, target=0.0) is None
    assert flat_orders == []


def test_target_size_is_strategy_scoped(shared):
    a, orders, _ = _make(*shared)
    a.order_target_size(data=a.data, target=0)
    assert orders == [("sell", 2.0)]


# -- A3/A6: target percent on proven strategy equity ---------------------------------


def test_target_percent_uses_strategy_equity(tmp_path):
    # A: capital 200,000, bought 100 at 100 -> cash 190,000 + value 10,000.
    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 100}}, capital="200000")
    try:
        a, orders, reader = _make(ledger, totals)
        a.order_target_percent(data=a.data, target=0.10)  # 20,000 target
        assert orders == [("buy", 100.0)]  # 10,000 more at 100, not 1,000,000 * 10%
        assert reader.calls == 1  # equity and position value from one snapshot (A10)
    finally:
        ledger.close()


def test_target_percent_never_uses_budget_or_account_value(shared):
    a, orders, _ = _make(*shared, reconciled=False)
    with pytest.raises(ValueError, match="STRATEGY_BOOK_UNRECONCILED"):
        a.order_target_percent(data=a.data, target=0.10)
    assert orders == []


# -- A5/A10: missing or conflicting valuation inputs never order ---------------------


def _refused(strategy, orders, match, *, target=300.0, call="order_target_value", **kwargs):
    with pytest.raises(ValueError, match=match):
        getattr(strategy, call)(data=strategy.data, target=target, **kwargs)
    assert orders == []


def test_report_reproduction_inputs_without_eligibility_are_refused(shared):
    """F6: a book without a reconciled financial cut gives no target order."""

    _refused(*_make(*shared, reconciled=False)[:2], "STRATEGY_BOOK_UNRECONCILED")


@pytest.mark.parametrize("call", ["order_target_value", "order_target_percent"])
@pytest.mark.parametrize("bar", [1.0, BAR])
def test_bound_unknown_broker_refuses_unproven_mark(shared, call, bar):
    # A timestamp and self-reported flags do not prove a live mark's source.
    a, orders, _ = _make(*shared, datas=[_Data("X", bar=bar)])
    a.data.execution_eligible = True
    a.data.freshness_verified = True
    a.broker = _AccountBroker()
    _refused(a, orders, "STRATEGY_MARK_PROVENANCE_UNAVAILABLE", call=call)


@pytest.mark.parametrize("call", ["order_target_value", "order_target_percent"])
def test_bound_btapi_broker_refuses_unproven_mark(shared, call):
    a, orders, _ = _make(*shared)
    a.broker = bt.brokers.BtApiBroker()
    a.broker.setcommission(commission=0.0, stocklike=True, mult=1.0)
    _refused(a, orders, "STRATEGY_MARK_PROVENANCE_UNAVAILABLE", call=call, price=100.0)


@pytest.mark.parametrize("flag", ["live", "unknown", "raises"])
def test_bound_historical_broker_rejects_nonhistorical_feed(shared, flag):
    a, orders, _ = _make(*shared)
    if flag == "live":
        a.data.islive = lambda: True
    elif flag == "unknown":
        a.data.islive = None
    else:
        def raises():
            raise RuntimeError("feed state unavailable")

        a.data.islive = raises
    _refused(a, orders, "STRATEGY_MARK_PROVENANCE_UNAVAILABLE")


def test_bound_historical_broker_rejects_live_cerebro(shared):
    a, orders, _ = _make(*shared)
    a.cerebro._dolive = True
    _refused(a, orders, "STRATEGY_MARK_PROVENANCE_UNAVAILABLE")


def test_bound_valuation_checks_every_held_feed(tmp_path):
    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2, "Y": 1}})
    try:
        other = _Data("Y")
        other.islive = lambda: True
        a, orders, _ = _make(ledger, totals, datas=[_Data("X"), other])
        _refused(a, orders, "STRATEGY_MARK_PROVENANCE_UNAVAILABLE")
    finally:
        ledger.close()


def test_zero_target_still_closes_strategy_position_without_mark(shared):
    a, orders, _ = _make(*shared, datas=[_Data("X", bar=1.0)])
    a.broker = _AccountBroker()
    a.order_target_value(data=a.data, target=0.0)
    assert orders == [("sell", 2.0)]


def test_bound_historical_backtest_can_use_actual_feed(tmp_path):
    import pandas as pd

    ledger, totals = _ledger(tmp_path, holdings={"A": {}})

    class HistoricalStrategy(bt.Strategy):
        def __init__(self):
            self.account_book = DirectStrategyAccountBookView(
                ledger.reader("A", account_positions=lambda: _report(totals))
            )
            self.target_order = None
            self.statuses = []

        def next(self):
            if self.target_order is None:
                self.target_order = self.order_target_value(target=300.0)

        def notify_order(self, order):
            self.statuses.append(order.status)

    frame = pd.DataFrame(
        {"open": [100.0] * 3, "high": [100.0] * 3, "low": [100.0] * 3,
         "close": [100.0] * 3, "volume": [1] * 3},
        index=pd.date_range("2020-01-01", periods=3),
    )
    try:
        cerebro = bt.Cerebro()
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="X")
        cerebro.addstrategy(HistoricalStrategy)
        strategy = cerebro.run()[0]
        assert strategy.target_order.created.size == 3
        assert strategy.target_order.Completed in strategy.statuses
    finally:
        ledger.close()


def test_strategy_without_capital_has_no_valuation(tmp_path):
    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2}}, capital=None)
    try:
        _refused(*_make(ledger, totals)[:2], "STRATEGY_CAPITAL_UNCONFIGURED")
    finally:
        ledger.close()


def test_residual_or_incomplete_account_report_is_refused(shared):
    ledger, totals = shared
    _refused(*_make(ledger, {"X": Decimal("6")})[:2], "RECONCILIATION_RESIDUAL")


@pytest.mark.parametrize("price", [math.nan, 0.0, math.inf])
def test_target_value_refuses_unusable_prices(shared, price):
    _refused(*_make(*shared)[:2], "finite positive price", price=price)


@pytest.mark.parametrize("target", [math.nan, -1.0, math.inf])
def test_target_value_refuses_unusable_targets(shared, target):
    _refused(*_make(*shared)[:2], "non-negative", target=target)


def test_mark_must_be_eligible(shared):
    ledger, totals = shared
    _refused(*_make(ledger, totals, datas=[_Data("X", price=math.nan)])[:2], "MARK_UNAVAILABLE")
    _refused(*_make(ledger, totals, datas=[_Data("X", price=0.0)])[:2], "MARK_UNAVAILABLE")


def test_held_instrument_without_a_feed_has_no_mark(tmp_path):
    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2, "Y": 1}})
    try:
        _refused(*_make(ledger, totals)[:2], "STRATEGY_MARK_UNAVAILABLE")
    finally:
        ledger.close()


def test_marks_from_different_bars_are_stale_unless_allowed(tmp_path):
    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2, "Y": 1}})
    try:
        datas = [_Data("X"), _Data("Y", bar=BAR - 1.0 / 24)]  # one hour older
        a, orders, _ = _make(ledger, totals, datas=datas)
        _refused(a, orders, "STRATEGY_MARK_STALE")
        a.strategy_mark_max_age = 3600.0
        a.order_target_value(data=a.data, target=300.0)  # X 200 of the 300 equity in X
        assert orders == [("buy", 1.0)]
    finally:
        ledger.close()


@pytest.mark.parametrize("max_age", [float("nan"), float("inf"), -1.0, "invalid"])
def test_invalid_mark_max_age_is_refused(shared, max_age):
    a, orders, _ = _make(*shared)
    a.strategy_mark_max_age = max_age
    _refused(a, orders, "STRATEGY_MARK_AGE_INVALID")


def test_multiplier_conflict_with_the_book_is_refused(shared):
    _refused(*_make(*shared, mult=10.0)[:2], "STRATEGY_INSTRUMENT_TERMS_CONFLICT")


def test_futures_like_instruments_are_refused(shared):
    _refused(*_make(*shared, stocklike=False)[:2], "futures-like")


def test_futures_terms_in_the_book_are_not_valued(tmp_path):
    ledger, totals = _ledger(
        tmp_path,
        holdings={"A": {"X": 2}},
        capital=None,
        terms={"X": InstrumentTerms(Decimal("1"), "CNY", "futures")},
    )
    try:
        _refused(*_make(ledger, totals)[:2], "STRATEGY_CAPITAL_UNCONFIGURED")
    finally:
        ledger.close()


def test_a_short_position_is_refused_before_it_can_be_valued(tmp_path):
    """Spot-cost valuation has no borrow/margin facts: a short is never netted.

    The SDK ledger refuses opening a short in a capital book; a snapshot that
    carries one anyway (another host's model) is refused by the valuation.
    """

    import dataclasses

    from backtrader.service.service_strategy_account_book import (
        ServiceStrategyAccountBookError,
        value_strategy_book,
    )

    ledger, totals = _ledger(tmp_path, holdings={"A": {"X": 2}})
    try:
        with pytest.raises(Exception, match="POSITION_FLIP_REFUSED"):
            ledger.reserve(LedgerIntent("A-X-flip", "A", "X", "SELL", Decimal("5"), Decimal("100")))
        snapshot = ledger.reader("A", account_positions=lambda: _report(totals)).snapshot()
        shorted = dataclasses.replace(snapshot, positions={"X": Decimal("-2")})
        with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_SHORT_POSITION_UNSUPPORTED"):
            value_strategy_book(shorted, marks={"X": Decimal("100")}, multipliers={"X": 1.0})
    finally:
        ledger.close()


def test_second_cash_currency_without_fx_is_refused(tmp_path):
    ledger, totals = _ledger(
        tmp_path, holdings={"A": {"X": 2}}, fee={"fee": "0.01", "fee_currency": "BNB"}
    )
    try:
        _refused(*_make(ledger, totals)[:2], "STRATEGY_CURRENCY_AMBIGUOUS")
        a, orders, _ = _make(ledger, totals)
        sizer = PercentSizer(percents=20)
        sizer.set(a, a.broker)
        with pytest.raises(ValueError, match="STRATEGY_FX_UNAVAILABLE"):
            sizer.getsizing(a.data, True)
    finally:
        ledger.close()


def test_view_bound_to_another_strategy_is_refused(shared):
    ledger, totals = shared
    a, orders, _ = _make(ledger, totals)
    a.account_book = DirectStrategyAccountBookView(ledger.reader("B", account_positions=lambda: _report(totals)))
    a.p.strategy_ref = "A"
    # The Strategy reads whatever book is bound; the sizer refuses a mismatched owner.
    from backtrader.sizers.strategy_account_book import StrategyAccountBookPercentSizer

    sizer = StrategyAccountBookPercentSizer(currency="CNY")
    sizer.set(a, a.broker)
    with pytest.raises(ValueError, match="matching strategy-owned account book"):
        sizer.getsizing(a.data, True)


# -- A4/A7: Sizers size from strategy cash -------------------------------------------


@pytest.mark.parametrize(
    "sizer_cls, expected",
    [(PercentSizer, 200.0), (AllInSizer, 1000.0), (PercentSizerInt, 200), (AllInSizerInt, 1000)],
)
def test_cash_sizers_use_the_strategy_cash(tmp_path, sizer_cls, expected):
    # A has 100,000 of its own cash; the account has 1,000,000.
    ledger, totals = _ledger(tmp_path, holdings={"A": {}, "B": {"X": 3}}, capital="100000")
    try:
        a, _orders, _ = _make(ledger, totals)
        sizer = sizer_cls()
        sizer.set(a, a.broker)
        size = sizer.getsizing(a.data, True)
        assert size == expected and type(size) is type(expected)
    finally:
        ledger.close()


def test_custom_cash_sizer_receives_strategy_cash_and_stake_sizers_still_work(tmp_path):
    class _Custom(bt.Sizer):
        def _getsizing(self, comminfo, cash, data, isbuy):
            return cash / 100

    ledger, totals = _ledger(tmp_path, holdings={"A": {}}, capital="50000")
    try:
        a, _orders, _ = _make(ledger, totals)
        custom = _Custom()
        custom.set(a, a.broker)
        assert custom.getsizing(a.data, True) == 500.0
        fixed = FixedSize(stake=3)
        fixed.set(a, a.broker)
        assert fixed.getsizing(a.data, True) == 3
    finally:
        ledger.close()


def test_cash_sizer_refuses_instead_of_using_account_cash(shared):
    a, _orders, _ = _make(*shared, reconciled=False)
    sizer = PercentSizer(percents=20)
    sizer.set(a, a.broker)
    with pytest.raises(ValueError, match="STRATEGY_BOOK_UNRECONCILED"):
        sizer.getsizing(a.data, True)
    futures, _orders, _ = _make(*shared, stocklike=False)
    sizer.set(futures, futures.broker)
    with pytest.raises(ValueError, match="futures-like"):
        sizer.getsizing(futures.data, True)


# -- A11: unbound strategies keep Broker semantics --------------------------------------


def test_unbound_strategy_keeps_account_semantics():
    strategy, orders, _ = _make(None)
    strategy.order_target_percent(data=strategy.data, target=0.001)  # 1,000 of 1,000,000
    assert orders  # unchanged legacy path ran on the account value
    sizer = PercentSizer(percents=20)
    sizer.set(strategy, strategy.broker)
    assert sizer.getsizing(strategy.data, False) == 5.0  # existing position, account scope
