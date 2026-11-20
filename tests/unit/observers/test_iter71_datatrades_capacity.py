"""Regression tests for DataTrades' fixed per-feed line capacity."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest


def _trade_frame():
    index = pd.date_range("2025-01-01", periods=5, freq="D")
    prices = [10.0, 11.0, 12.0, 13.0, 14.0]
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [100] * len(prices),
        },
        index=index,
    )


class _TradeOnFeed(bt.Strategy):
    params = (("target_index", 0),)

    def __init__(self):
        self.trade_events = []

    def next(self):
        target = self.datas[self.p.target_index]
        if len(self) == 1:
            self.buy(data=target, size=1)
        elif len(self) == 2 and self.getposition(target).size:
            self.close(data=target)

    def notify_trade(self, trade):
        self.trade_events.append((trade.data, trade.data._id, trade.isclosed, trade.pnl))


def _run_trade(feed_count, target_index):
    cerebro = bt.Cerebro(runonce=False)
    frame = _trade_frame()
    for index in range(feed_count):
        cerebro.adddata(bt.feeds.PandasData(dataname=frame.copy()), name="feed{}".format(index))
    cerebro.addstrategy(_TradeOnFeed, target_index=target_index)

    strategy = cerebro.run()[0]
    observer = next(
        item for item in strategy.stats.items if isinstance(item, bt.observers.DataTrades)
    )
    return strategy, observer


@pytest.mark.parametrize("runonce", [True, False])
def test_datatrades_rejects_more_feeds_than_declared_lines_in_cerebro(runonce):
    cerebro = bt.Cerebro(runonce=runonce)
    frame = _trade_frame()
    for index in range(11):
        cerebro.adddata(bt.feeds.PandasData(dataname=frame.copy()), name="feed{}".format(index))
    cerebro.addstrategy(_TradeOnFeed, target_index=10)

    # Cerebro's default multi-feed stdstats setup creates DataTrades. The
    # observer must reject this configuration before the strategy can trade,
    # rather than silently losing feed 11's closed-trade PnL.
    with pytest.raises(ValueError, match=r"DataTrades supports at most 10 data feeds; got 11"):
        cerebro.run()


def test_more_than_ten_feeds_can_run_without_standard_observers():
    cerebro = bt.Cerebro(runonce=False, stdstats=False)
    frame = _trade_frame()
    for index in range(11):
        cerebro.adddata(bt.feeds.PandasData(dataname=frame.copy()), name="feed{}".format(index))
    cerebro.addstrategy(_TradeOnFeed, target_index=10)

    strategy = cerebro.run()[0]

    closed_trade = next(event for event in strategy.trade_events if event[2])
    assert closed_trade[0] is strategy.datas[10]
    assert closed_trade[3] == pytest.approx(1.0)
    assert not any(isinstance(item, bt.observers.DataTrades) for item in strategy.stats.items)


def test_datatrades_uses_local_feed_slots_across_cerebro_instances():
    first_strategy, first_observer = _run_trade(feed_count=10, target_index=9)
    second_strategy, second_observer = _run_trade(feed_count=2, target_index=1)

    assert [data._id for data in first_strategy.datas] == list(range(1, 11))
    # Cerebro owns its data counter; a new instance starts again at one.
    assert [data._id for data in second_strategy.datas] == [1, 2]

    for strategy, observer, target_index in (
        (first_strategy, first_observer, 9),
        (second_strategy, second_observer, 1),
    ):
        target = strategy.datas[target_index]
        closed_trade = next(event for event in strategy.trade_events if event[2])
        assert closed_trade[0] is target
        assert closed_trade[1] == target._id
        assert closed_trade[3] == pytest.approx(1.0)

        assert len(observer.lines) == 10
        values = list(observer.lines[target_index].array)
        assert [value for value in values if math.isfinite(value)] == [1.0]
        for index in range(len(observer.lines)):
            if index != target_index:
                assert all(math.isnan(value) for value in observer.lines[index].array)


def test_datatrades_maps_by_feed_identity_instead_of_feed_id():
    class FakeFeed:
        def __init__(self, feed_id):
            self._id = feed_id

    data0 = FakeFeed(40)
    data1 = FakeFeed(90)
    observer = object.__new__(bt.observers.DataTrades)
    observer._owner = SimpleNamespace(
        _tradespending=[
            SimpleNamespace(data=data1, isclosed=True, pnl=12.5),
        ]
    )
    observer.datas = [data0, data1]
    observer.ddatas = dict.fromkeys(observer.datas)
    observer._data_line_indices = {id(data0): 0, id(data1): 1}
    observer.lines = [[float("nan")], [float("nan")]]

    observer.next()

    assert math.isnan(observer.lines[0][0])
    assert observer.lines[1][0] == pytest.approx(12.5)
