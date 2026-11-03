"""Observer dispatch in historical runs with one or more data feeds."""

import datetime as dt

import pandas as pd
import pytest

import backtrader as bt


class CountingObserver(bt.Observer):
    lines = ("seen",)

    def __init__(self):
        self.owner_at_init = self._owner
        self.owner_length_at_init = len(self._owner)
        self.started = 0
        self.stopped = 0
        self.calls = []

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def prenext(self):
        self.calls.append(("prenext", len(self._owner)))
        self.lines.seen[0] = len(self._owner)

    def nextstart(self):
        self.calls.append(("nextstart", len(self._owner)))
        self.lines.seen[0] = len(self._owner)

    def next(self):
        self.calls.append(("next", len(self._owner)))
        self.lines.seen[0] = len(self._owner)


class HistoricalStrategy(bt.Strategy):
    def __init__(self):
        # Force prenext and nextstart so all scheduler branches are exercised.
        self.sma = bt.indicators.SimpleMovingAverage(self.data, period=2)


def _run(*, runonce, multi, stdstats):
    dates = pd.date_range(dt.datetime(2020, 1, 1), periods=4)
    values = pd.DataFrame(
        {"open": [1, 2, 3, 4], "high": [1, 2, 3, 4], "low": [1, 2, 3, 4],
         "close": [1, 2, 3, 4], "volume": [1, 1, 1, 1]}, index=dates
    )
    cerebro = bt.Cerebro(stdstats=stdstats, maxcpus=1)
    cerebro.adddata(bt.feeds.PandasData(dataname=values.copy()), name="first")
    if multi:
        cerebro.adddata(bt.feeds.PandasData(dataname=values.copy()), name="second")
        cerebro.addobservermulti(CountingObserver)
    else:
        cerebro.addobserver(CountingObserver)
    cerebro.addstrategy(HistoricalStrategy)
    return cerebro.run(runonce=runonce, preload=runonce)[0]


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("stdstats", [False, True])
def test_observers_execute_once_per_bar_with_lifecycle(runonce, multi, stdstats):
    strategy = _run(runonce=runonce, multi=multi, stdstats=stdstats)
    registered = strategy.stats.countingobserver
    observers = registered if multi else [registered]
    assert len(observers) == (2 if multi else 1)
    if multi:
        assert all(
            observer.data is data and len(observer.datas) == 1
            and observer.datas[0] is data and data in observer.ddatas
            for observer, data in zip(observers, strategy.datas)
        )
    for observer in observers:
        assert observer.owner_at_init is strategy
        assert observer.owner_length_at_init == 0
        assert observer.started == observer.stopped == 1
        assert [n for _, n in observer.calls] == [1, 2, 3, 4]
        expected = ["prenext", "nextstart", "next", "next"]
        assert [phase for phase, _ in observer.calls] == expected
    if stdstats:
        assert list(strategy.stats.broker.lines.cash.array) == [10000.0] * 4
        assert list(strategy.stats.broker.lines.value.array) == [10000.0] * 4
        if multi:
            plotlines = strategy.stats.datatrades.plotlines
            assert plotlines["data0"]["marker"] == "o"
            assert plotlines["data1"]["marker"] == "v"


@pytest.mark.parametrize("runonce", [False, True])
def test_trade_logger_is_dispatched_once_per_bar(monkeypatch, runonce):
    from backtrader.observers.trade_logger import TradeLogger

    calls = []
    monkeypatch.setattr(TradeLogger, "_init_loggers", lambda self: None)
    monkeypatch.setattr(TradeLogger, "_emit_payload", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(TradeLogger, "next", lambda self: calls.append(len(self._owner)))
    values = pd.DataFrame(
        {"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
         "close": [1, 2, 3], "volume": [1, 1, 1]},
        index=pd.date_range(dt.datetime(2020, 1, 1), periods=3),
    )
    cerebro = bt.Cerebro(stdstats=True, maxcpus=1)
    cerebro.adddata(bt.feeds.PandasData(dataname=values))
    cerebro.addobserver(TradeLogger, log_dir="unused-test-sink", mysql_enabled=False)
    cerebro.addstrategy(bt.Strategy)
    cerebro.run(runonce=runonce, preload=runonce)
    assert calls == [1, 2, 3]


@pytest.mark.parametrize("runonce", [False, True])
def test_observer_dependent_analyzer_has_owner_and_runs(runonce):
    values = pd.DataFrame(
        {"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
         "close": [1, 2, 3], "volume": [1, 1, 1]},
        index=pd.date_range(dt.datetime(2020, 1, 1), periods=3),
    )
    cerebro = bt.Cerebro(stdstats=True, maxcpus=1)
    cerebro.adddata(bt.feeds.PandasData(dataname=values))
    cerebro.addobserver(bt.observers.DrawDown)
    cerebro.addstrategy(HistoricalStrategy)
    strategy = cerebro.run(runonce=runonce, preload=runonce)[0]
    assert strategy.sma._owner is strategy
    observer = strategy.stats.drawdown
    assert observer._owner is strategy
    assert observer._dd is not None
    assert len(observer.lines.drawdown.array) == 3
    assert observer.lines.drawdown.array[-1] == 0.0


@pytest.mark.parametrize("runonce", [False, True])
def test_datatrades_matches_closed_trades_to_their_feeds(monkeypatch, runonce):
    observed = []
    original_next = bt.observers.DataTrades.next

    def capture(observer):
        original_next(observer)
        observed.append(tuple(line[0] for line in observer.lines.lines[:2]))

    monkeypatch.setattr(bt.observers.DataTrades, "next", capture)

    class TwoInstrumentStrategy(bt.Strategy):
        def next(self):
            if len(self) == 1:
                for data in self.datas:
                    self.buy(data=data, size=1)
            elif len(self) == 2:
                for data in self.datas:
                    self.close(data=data)

    dates = pd.date_range(dt.datetime(2020, 1, 1), periods=4)
    cerebro = bt.Cerebro(stdstats=True, maxcpus=1)
    for prices in ([100, 101, 105, 106], [50, 51, 48, 47]):
        frame = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices,
             "close": prices, "volume": [1] * 4}, index=dates
        )
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(TwoInstrumentStrategy)
    strategy = cerebro.run(runonce=runonce, preload=runonce)[0]
    observer = strategy.stats.datatrades
    assert all(data in observer.ddatas for data in strategy.datas)
    assert (4.0, -3.0) in observed
    first, second = strategy.stats.buysell
    assert first.data is strategy.datas[0]
    assert second.data is strategy.datas[1]
    assert first.lines.buy.array[1] == pytest.approx(101.0 * 0.985)
    assert first.lines.sell.array[2] == pytest.approx(105.0 * 1.015)
    assert second.lines.buy.array[1] == pytest.approx(51.0 * 0.985)
    assert second.lines.sell.array[2] == pytest.approx(48.0 * 1.015)


def test_observer_notifications_flatten_and_deduplicate_in_registration_order():
    events = []

    class Recorder:
        def __init__(self, name):
            self.name = name

        def log_signal(self, *args):
            events.append((self.name, "signal", args))

        def notify_order(self, *args):
            events.append((self.name, "order", args))

        def notify_trade(self, *args):
            events.append((self.name, "trade", args))

        def notify_store_event(self, *args, **kwargs):
            events.append((self.name, "store", args))

        def notify_data_event(self, *args, **kwargs):
            events.append((self.name, "data", args))

        def notify_tick_event(self, *args):
            events.append((self.name, "tick", args))

        def notify_bar_event(self, *args):
            events.append((self.name, "bar", args))

    first, second = Recorder("first"), Recorder("second")
    strategy = object.__new__(bt.Strategy)
    strategy.stats = [first, [second, first]]
    marker = object()
    strategy._notify_signal_to_observers("buy", 1, 10)
    strategy._notify_order_to_observers(marker)
    strategy._notify_trade_to_observers(marker)
    strategy._notify_store_to_observers("store")
    strategy._notify_data_to_observers(marker, "live")
    strategy._notify_tick_to_observers(marker)
    strategy._notify_bar_to_observers(marker)
    assert [(name, kind) for name, kind, _ in events] == [
        (name, kind)
        for kind in ("signal", "order", "trade", "store", "data", "tick", "bar")
        for name in ("first", "second")
    ]


def test_observer_notification_exceptions_keep_original_stop_semantics():
    events = []

    class Failing:
        def notify_order(self, order):
            events.append("first")
            raise RuntimeError("observer failed")

    class Later:
        def notify_order(self, order):
            events.append("second")

    strategy = object.__new__(bt.Strategy)
    strategy.stats = [[Failing(), Later()]]
    with pytest.raises(RuntimeError, match="observer failed"):
        strategy._notify_order_to_observers(object())
    assert events == ["first"]


@pytest.mark.parametrize("runonce", [False, True])
def test_single_and_multi_observers_receive_same_order_and_trade_events(runonce):
    class SingleObserver(bt.Observer):
        lines = ("value",)

        def __init__(self):
            self.events = []
            self.started = self.stopped = 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1

        def notify_order(self, order):
            self.events.append(("order", order.ref, order.status, order.data._name))

        def notify_trade(self, trade):
            self.events.append(("trade", trade.ref, trade.status, trade.data._name))

        def next(self):
            self.lines.value[0] = 0.0

    class MultiObserver(SingleObserver):
        pass

    class TradingStrategy(bt.Strategy):
        def next(self):
            if len(self) == 1:
                for data in self.datas:
                    self.buy(data=data, size=1)
            elif len(self) == 2:
                for data in self.datas:
                    self.close(data=data)

    dates = pd.date_range(dt.datetime(2020, 1, 1), periods=4)
    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    for name, prices in (("first", [100, 101, 105, 106]), ("second", [50, 51, 48, 47])):
        frame = pd.DataFrame(
            {"open": prices, "high": prices, "low": prices,
             "close": prices, "volume": [1] * 4}, index=dates
        )
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=name)
    cerebro.addobserver(SingleObserver)
    cerebro.addobservermulti(MultiObserver)
    cerebro.addstrategy(TradingStrategy)
    strategy = cerebro.run(runonce=runonce, preload=runonce)[0]
    single = strategy.stats.singleobserver
    multi = strategy.stats.multiobserver
    assert len(multi) == 2
    assert single.started == single.stopped == 1
    assert all(observer.started == observer.stopped == 1 for observer in multi)
    assert {event[0] for event in single.events} == {"order", "trade"}
    assert {event[3] for event in single.events} == {"first", "second"}
    assert all(observer.events == single.events for observer in multi)
