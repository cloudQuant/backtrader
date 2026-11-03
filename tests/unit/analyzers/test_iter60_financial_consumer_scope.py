"""Strategy-bound analyzers must never publish account-wide broker values."""

import json
import math
from collections import deque
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.analyzers._strategy_scope import cash_value, fund_shares, portfolio_value
from backtrader.analyzers.annualreturn import AnnualReturn
from backtrader.analyzers.drawdown import DrawDown
from backtrader.analyzers.leverage import GrossLeverage
from backtrader.analyzers.logreturnsrolling import LogReturnsRolling
from backtrader.analyzers.positions import PositionsValue
from backtrader.analyzers.periodstats import PeriodStats
from backtrader.analyzers.returns import Returns
from backtrader.analyzers.timereturn import TimeReturn
from backtrader.analyzers.total_value import TotalValue
from backtrader.analyzers.vwr import VWR
from backtrader.analyzers.calmar import Calmar
from backtrader.observers.broker import Broker as BrokerObserver
from backtrader.observers.trade_logger import TradeLogger
from backtrader.service.service_strategy_account_book import ServiceStrategyAccountBookError


class _Broker:
    fundvalue = 8888
    fundshares = 4444

    def __init__(self):
        self.reads = []

    def getvalue(self):
        self.reads.append("value")
        return 9999

    def getcash(self):
        self.reads.append("cash")
        return 7777

    def get_cash(self):
        self.reads.append("cash_alias")
        return 7777

    def get_value(self, datas):
        self.reads.append("position")
        return 6666


class _Book:
    def __init__(self, value, positions):
        self.value = value
        self.positions = positions

    def getvalue(self):
        return self.value

    def getcash(self, *, currency=None):
        if currency is None:
            raise ServiceStrategyAccountBookError("STRATEGY_CASH_CURRENCY_REQUIRED")
        raise AssertionError("consumer did not declare a currency")

    def getposition(self, data):
        return SimpleNamespace(size=self.positions.get(data, 0))


def _strategy(broker, book=None):
    return SimpleNamespace(broker=broker, account_book=book, _strategy_account_book=lambda: book)


def _unavailable_notifications(strategy):
    strategy._strategy_financial_unavailable = {
        "value": "STRATEGY_VALUE_UNAVAILABLE",
        "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
        "fundvalue": "STRATEGY_FUND_VALUE_UNAVAILABLE",
        "fundshares": "STRATEGY_FUND_SHARES_UNAVAILABLE",
    }


def test_two_strategies_do_not_use_unproven_values_and_keep_zero_position():
    broker = _Broker()
    a = _strategy(broker, _Book(200, {"x": 2}))
    b = _strategy(broker, _Book(300, {"x": 3}))
    for strategy in (a, b):
        _unavailable_notifications(strategy)
        analyzer = SimpleNamespace(
            strategy=strategy, data=SimpleNamespace(datetime=[1]), _dt_cache=[], _value_cache=[]
        )
        AnnualReturn.next(analyzer)
        assert math.isnan(analyzer._value_cache[0])

    analyzer = SimpleNamespace(
        strategy=a, datas=["absent"], p=SimpleNamespace(cash=False), _usedate=True, rets={}
    )
    a.datetime = SimpleNamespace(date=lambda: "today")
    PositionsValue.next(analyzer)
    assert analyzer.rets["today"] == [0.0]
    analyzer.datas = ["x"]
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_POSITION_VALUE_UNAVAILABLE"):
        PositionsValue.next(analyzer)
    assert broker.reads == []


def test_cash_and_fund_inputs_fail_closed_without_currency_and_fund_contract():
    broker = _Broker()
    strategy = _strategy(broker, _Book(200, {}))
    _unavailable_notifications(strategy)
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_CASH_CURRENCY_REQUIRED"):
        cash_value(strategy)
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FUND_VALUE_UNAVAILABLE"):
        portfolio_value(strategy, fund=True)
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_FUND_SHARES_UNAVAILABLE"):
        fund_shares(strategy)
    analyzer = SimpleNamespace(strategy=strategy, _fundmode=False)
    GrossLeverage.notify_fund(analyzer, 7777, 9999, 8888, 4444)
    assert math.isnan(analyzer._cash)
    assert math.isnan(analyzer._value)
    analyzer._fundmode = True
    GrossLeverage.notify_fund(analyzer, 7777, 9999, 8888, 4444)
    assert math.isnan(analyzer._cash)
    assert math.isnan(analyzer._value)
    observer = SimpleNamespace(_owner=strategy, _fundmode=True, lines=SimpleNamespace(value=[None], cash=[None]))
    BrokerObserver.next(observer)
    assert math.isnan(observer.lines.value[0])
    assert observer._strategy_financial_unavailable == {
        "value": "STRATEGY_FUND_VALUE_UNAVAILABLE",
        "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
    }
    observer._fundmode = False
    BrokerObserver.next(observer)
    assert math.isnan(observer.lines.value[0])
    assert math.isnan(observer.lines.cash[0])
    assert observer._strategy_financial_unavailable == {
        "value": "STRATEGY_VALUE_UNAVAILABLE", "cash": "STRATEGY_CASH_CURRENCY_REQUIRED"
    }
    assert broker.reads == []


def test_fund_notifications_use_bound_book_and_preserve_data_only_returns():
    broker = _Broker()
    strategy = _strategy(broker, _Book(200, {}))
    _unavailable_notifications(strategy)
    drawdown = SimpleNamespace(strategy=strategy, _fundmode=False, _maxvalue=None)
    DrawDown.notify_fund(drawdown, 7777, 9999, 8888, 4444)
    assert math.isnan(drawdown._value)
    ret = SimpleNamespace(strategy=strategy, _fundmode=False, _p_data=None)
    TimeReturn.notify_fund(ret, 7777, 9999, 8888, 4444)
    assert math.isnan(ret._value)
    ret._p_data = [42]
    TimeReturn.notify_fund(ret, 7777, 9999, 8888, 4444)
    assert ret._value == 42
    assert broker.reads == []


def test_trade_logger_does_not_replace_unavailable_strategy_values_with_zero():
    owner = _strategy(_Broker(), _Book(200, {}))
    _unavailable_notifications(owner)
    logger = SimpleNamespace(_owner=owner)
    assert math.isnan(TradeLogger._get_broker_value(logger))
    assert math.isnan(TradeLogger._get_broker_cash(logger))
    assert logger._strategy_financial_unavailable == {
        "value": "STRATEGY_VALUE_UNAVAILABLE", "cash": "STRATEGY_CASH_CURRENCY_REQUIRED"
    }


def test_unavailable_strategy_equity_is_not_replaced_with_account_value():
    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    broker = _Broker()
    strategy = _strategy(broker, UnvaluedBook(None, {}))
    _unavailable_notifications(strategy)
    analyzer = SimpleNamespace(strategy=strategy, _fundmode=False, _maxvalue=None)
    DrawDown.notify_fund(analyzer, 7777, 9999, 8888, 4444)
    assert math.isnan(analyzer._value)
    with pytest.raises(ServiceStrategyAccountBookError, match="STRATEGY_VALUE_UNAVAILABLE"):
        portfolio_value(strategy)
    logger = SimpleNamespace(_owner=strategy)
    assert math.isnan(TradeLogger._get_broker_value(logger))
    assert logger._strategy_financial_unavailable == {"value": "STRATEGY_VALUE_UNAVAILABLE"}
    assert broker.reads == []


def test_notifications_never_reread_finite_book_getters_without_a_proven_cut():
    class BrokenBook(_Book):
        def getvalue(self):
            pytest.fail("must not reread book value")

        def getcash(self, *, currency=None):
            pytest.fail("must not reread book cash")

    strategy = _strategy(_Broker(), BrokenBook(200, {}))
    _unavailable_notifications(strategy)
    analyzer = SimpleNamespace(strategy=strategy, _fundmode=False)
    GrossLeverage.notify_fund(analyzer, 7777, 9999, 8888, 4444)
    assert math.isnan(analyzer._value) and math.isnan(analyzer._cash)
    assert analyzer._strategy_financial_unavailable == {
        "value": "STRATEGY_VALUE_UNAVAILABLE", "cash": "STRATEGY_CASH_CURRENCY_REQUIRED"
    }

    class FiniteBook(_Book):
        def getvalue(self):
            return 22

        def getcash(self, *, currency=None):
            return 11

    strategy = _strategy(_Broker(), FiniteBook(22, {}))
    _unavailable_notifications(strategy)
    analyzer = SimpleNamespace(strategy=strategy, _fundmode=False)
    GrossLeverage.notify_fund(analyzer, float("nan"), float("nan"), float("nan"), float("nan"))
    assert math.isnan(analyzer._value) and math.isnan(analyzer._cash)

    # The notification itself, not either independent getter, supplies the
    # values when Strategy has an explicitly available sanitized context.
    strategy._strategy_financial_unavailable = {}
    GrossLeverage.notify_fund(analyzer, 12, 34, 56, 78)
    assert analyzer._cash == 12 and analyzer._value == 34


def test_missing_sanitized_context_fails_closed_and_unexpected_failure_propagates():
    strategy = _strategy(_Broker(), _Book(200, {}))
    analyzer = SimpleNamespace(strategy=strategy, _fundmode=False)
    GrossLeverage.notify_fund(analyzer, 7777, 9999, 8888, 4444)
    assert math.isnan(analyzer._value) and math.isnan(analyzer._cash)
    assert analyzer._strategy_financial_unavailable["value"] == "STRATEGY_FINANCIAL_CONTEXT_UNAVAILABLE"

    def bad_lookup():
        raise RuntimeError("unexpected failure")

    strategy._strategy_account_book = bad_lookup
    with pytest.raises(RuntimeError, match="unexpected failure"):
        GrossLeverage.notify_fund(analyzer, 7777, 9999, 8888, 4444)


def test_bound_drawdown_and_leverage_publish_unknown_instead_of_zero():
    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    strategy = _strategy(_Broker(), UnvaluedBook(None, {}))
    _unavailable_notifications(strategy)
    drawdown = DrawDown.__new__(DrawDown)
    drawdown.create_analysis()
    drawdown.strategy = strategy
    drawdown._fundmode = False
    drawdown.notify_fund(7777, 9999, 8888, 4444)
    drawdown.next()
    assert math.isnan(drawdown.rets.drawdown)
    assert math.isnan(drawdown.rets.max.drawdown)
    assert drawdown._strategy_financial_unavailable["result"] == "STRATEGY_VALUE_UNAVAILABLE"

    leverage = GrossLeverage.__new__(GrossLeverage)
    leverage.strategy = strategy
    leverage._fundmode = False
    leverage.rets = {}
    leverage.data0 = SimpleNamespace(datetime=SimpleNamespace(datetime=lambda: "now"))
    leverage.notify_fund(7777, 9999, 8888, 4444)
    leverage.next()
    assert math.isnan(leverage.rets["now"])
    assert leverage._strategy_financial_unavailable["result"] == "STRATEGY_VALUE_UNAVAILABLE"


def test_bound_time_returns_do_not_turn_unknown_into_zero():
    strategy = _strategy(_Broker(), _Book(float("nan"), {}))
    for analyzer_cls in (TimeReturn, LogReturnsRolling):
        analyzer = analyzer_cls.__new__(analyzer_cls)
        analyzer.strategy = strategy
        analyzer._fundmode = False
        analyzer.p = SimpleNamespace(data=None)
        analyzer._p_data = None
        analyzer._value = float("nan")
        analyzer._value_start = 100.0
        analyzer._values = [100.0]
        analyzer.rets = {}
        analyzer.dtkey = "now"
        with patch.object(analyzer_cls.__mro__[1], "next", return_value=None):
            analyzer.next()
        assert math.isnan(analyzer.rets["now"])
        assert analyzer._strategy_financial_unavailable["result"] == "STRATEGY_FINANCIAL_INPUT_UNAVAILABLE"


def test_bound_returns_vwr_and_calmar_preserve_unknown_results():
    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    strategy = _strategy(_Broker(), UnvaluedBook(None, {}))
    returns = Returns.__new__(Returns)
    returns.strategy = strategy
    returns._fundmode = False
    returns._value_start = float("nan")
    returns.rets = {}
    with patch.object(Returns.__mro__[1], "stop", return_value=None):
        returns.stop()
    assert all(math.isnan(returns.rets[key]) for key in ("rtot", "ravg", "rnorm", "rnorm100"))

    vwr = VWR.__new__(VWR)
    vwr.strategy = strategy
    vwr._pis = [float("nan")]
    vwr._pns = [float("nan")]
    vwr._returns = SimpleNamespace(get_analysis=lambda: {"ravg": float("nan"), "rnorm100": float("nan")})
    vwr.rets = {}
    with patch.object(VWR.__mro__[1], "stop", return_value=None):
        vwr.stop()
    assert math.isnan(vwr.rets["vwr"])

    calmar = Calmar.__new__(Calmar)
    calmar.strategy = strategy
    calmar._fundmode = False
    calmar._values = deque([100.0], maxlen=2)
    calmar._mdd = 1.0
    calmar._maxdd = SimpleNamespace(maxdd=1.0)
    calmar.rets = {}
    calmar.dtkey = "now"
    calmar.on_dt_over()
    assert math.isnan(calmar.rets["now"])


def test_bound_annual_and_period_statistics_do_not_turn_unknown_into_zero():
    strategy = _strategy(_Broker(), _Book(float("nan"), {}))
    annual = AnnualReturn.__new__(AnnualReturn)
    annual.strategy = strategy
    assert math.isnan(annual._scoped_annual_return(float("nan"), 100.0))
    assert annual._strategy_financial_unavailable["result"] == "STRATEGY_FINANCIAL_INPUT_UNAVAILABLE"

    periods = PeriodStats.__new__(PeriodStats)
    periods.strategy = strategy
    periods._tr = SimpleNamespace(get_analysis=lambda: {"year": float("nan")})
    periods.rets = {}
    periods.stop()
    assert all(math.isnan(periods.rets[key]) for key in (
        "average", "stddev", "positive", "negative", "nochange", "best", "worst"
    ))
    periods._tr = SimpleNamespace(get_analysis=dict)
    periods.rets = {}
    periods.stop()
    assert math.isnan(periods.rets["average"])


@pytest.mark.parametrize("book_value", [float("nan"), float("inf"), Decimal("NaN"), 22])
def test_bound_total_value_cannot_turn_unknown_or_unproven_value_into_zero(book_value):
    broker = _Broker()
    strategy = _strategy(broker, _Book(book_value, {}))
    _unavailable_notifications(strategy)
    analyzer = TotalValue.__new__(TotalValue)
    analyzer.strategy = strategy
    analyzer._broker = broker
    analyzer.datas = [SimpleNamespace(datetime=SimpleNamespace(datetime=lambda: "now"))]
    analyzer.rets = {}
    with patch.object(TotalValue.__mro__[1], "next", return_value=None):
        analyzer.next()
    assert math.isnan(analyzer.rets["now"])
    assert analyzer._strategy_financial_unavailable["result"] == "STRATEGY_VALUE_UNAVAILABLE"
    assert broker.reads == []
    strategy.account_book = None
    with patch.object(TotalValue.__mro__[1], "next", return_value=None):
        analyzer.next()
    assert analyzer.rets["now"] == 9999
    assert analyzer._strategy_financial_unavailable == {}


def test_trade_logger_emits_unavailable_metrics_without_stopping_or_account_fallback():
    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    broker = _Broker()
    logger = SimpleNamespace(
        _owner=_strategy(broker, UnvaluedBook(None, {})),
        _value_logger=object(),
        _log_time_str=lambda: "now",
        _get_datetime_str=lambda: "now",
        _get_strategy_name=lambda: "A",
    )
    _unavailable_notifications(logger._owner)
    logger._get_broker_value = lambda: TradeLogger._get_broker_value(logger)
    logger._get_broker_cash = lambda: TradeLogger._get_broker_cash(logger)
    written = []
    logger._emit_payload = lambda _target, payload, **_kwargs: written.append(payload)

    TradeLogger._log_value(logger)

    assert len(written) == 1
    assert math.isnan(written[0]["broker_value"])
    assert math.isnan(written[0]["broker_cash"])
    assert logger._strategy_financial_unavailable == {
        "value": "STRATEGY_VALUE_UNAVAILABLE",
        "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
    }
    assert broker.reads == []


def test_trade_logger_json_encodes_unavailable_as_null_with_reasons():
    messages = []
    logger = SimpleNamespace(
        p=SimpleNamespace(log_format="json"),
        _strategy_financial_unavailable={
            "value": "STRATEGY_VALUE_UNAVAILABLE",
            "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
        },
    )
    payload = {"broker_value": float("nan"), "broker_cash": float("nan")}
    TradeLogger._emit_payload(logger, SimpleNamespace(info=messages.append), payload)

    decoded = json.loads(messages[0], parse_constant=lambda _value: pytest.fail("invalid JSON"))
    assert decoded == {
        "broker_value": None,
        "broker_cash": None,
        "strategy_financial_unavailable": {
            "broker_value": "STRATEGY_VALUE_UNAVAILABLE",
            "broker_cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
        },
    }
    assert math.isnan(payload["broker_value"])  # the caller's payload remains unchanged


def test_trade_logger_clears_unavailability_reasons_when_book_is_unbound():
    broker = _Broker()
    strategy = _strategy(broker, _Book(200, {}))
    _unavailable_notifications(strategy)
    logger = SimpleNamespace(_owner=strategy)
    assert math.isnan(TradeLogger._get_broker_cash(logger))
    assert logger._strategy_financial_unavailable == {"cash": "STRATEGY_CASH_CURRENCY_REQUIRED"}

    strategy.account_book = None
    assert TradeLogger._get_broker_cash(logger) == 7777
    assert logger._strategy_financial_unavailable == {}


def test_unbound_strategy_retains_account_broker_semantics():
    broker = _Broker()
    strategy = _strategy(broker)
    assert portfolio_value(strategy) == 9999
    assert portfolio_value(strategy, fund=True) == 8888
    assert cash_value(strategy) == 7777
    assert fund_shares(strategy) == 4444
    assert broker.reads == ["value", "cash"]


def test_cerebro_default_broker_observer_handles_unavailable_book(tmp_path):
    import backtrader as bt

    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    class BoundStrategy(bt.Strategy):
        def __init__(self):
            self.account_book = UnvaluedBook(None, {})

    csv = tmp_path / "bars.csv"
    csv.write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-01,1,1,1,1,100\n"
        "2026-01-02,2,2,2,2,200\n",
        encoding="utf-8",
    )
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.addstrategy(BoundStrategy)
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=str(csv), dtformat="%Y-%m-%d", datetime=0,
        open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
    ))
    (strategy,) = cerebro.run(runonce=False)
    observer = strategy.observers.broker
    assert len(strategy) == 2
    # The current engine does not automatically schedule this default
    # observer through _next_observers; exercise its actual instance directly.
    observer.forward()
    observer.next()
    assert observer._strategy_financial_unavailable == {
        "value": "STRATEGY_FINANCIAL_CONTEXT_UNAVAILABLE",
        "cash": "STRATEGY_FINANCIAL_CONTEXT_UNAVAILABLE",
    }
    assert any(math.isnan(value) for value in observer.lines.value.array)
    assert any(math.isnan(cash) for cash in observer.lines.cash.array)


def test_cerebro_analyzers_keep_running_with_unavailable_strategy_metrics(tmp_path):
    import backtrader as bt

    class UnvaluedBook(_Book):
        def getvalue(self):
            raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")

    class BoundStrategy(bt.Strategy):
        def __init__(self):
            self.account_book = UnvaluedBook(None, {})

    csv = tmp_path / "bars.csv"
    csv.write_text(
        "date,open,high,low,close,volume\n"
        "2026-01-01,1,1,1,1,100\n"
        "2026-01-02,2,2,2,2,200\n",
        encoding="utf-8",
    )
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.addstrategy(BoundStrategy)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name="leverage")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="returns")
    cerebro.adddata(bt.feeds.GenericCSVData(
        dataname=str(csv), dtformat="%Y-%m-%d", datetime=0,
        open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
    ))
    (strategy,) = cerebro.run(runonce=False)
    assert len(strategy) == 2
    assert math.isnan(strategy.analyzers.dd.get_analysis().drawdown)
    assert all(math.isnan(value) for value in strategy.analyzers.leverage.get_analysis().values())
    assert all(math.isnan(value) for value in strategy.analyzers.returns.get_analysis().values())
