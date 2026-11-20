"""Channel runs must not leave a temporary quicknotify override behind."""

from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt


class QuicknotifyProbe(bt.Strategy):
    """Expose the value captured by each strategy run."""

    def __init__(self):
        self.ticks = []
        self.orders = []

    def notify_tick(self, tick):
        self.ticks.append(tick)

    def notify_order(self, order):
        self.orders.append(order)


def _regular_data():
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [10.0, 11.0, 12.0],
            "low": [10.0, 11.0, 12.0],
            "close": [10.0, 11.0, 12.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=index,
    )


@pytest.mark.parametrize("initial_quicknotify", [False, True])
@pytest.mark.parametrize("channel_exit", ["normal", "exception", "early"])
def test_channel_run_restores_quicknotify_before_reusing_cerebro(
    initial_quicknotify, channel_exit
):
    cerebro = bt.Cerebro(stdstats=False, quicknotify=initial_quicknotify)
    cerebro.addstrategy(QuicknotifyProbe)

    if channel_exit == "normal":
        channel_strategies = cerebro.run(channel=[])
    elif channel_exit == "exception":
        with pytest.raises(AttributeError, match="channel_type"):
            cerebro.run(channel=[SimpleNamespace()])
        channel_strategies = cerebro.runstrats[0]
    else:
        channel_strategies = cerebro.run(channel=True)
        assert cerebro._run_active

    assert cerebro.p.quicknotify is initial_quicknotify
    assert channel_strategies[0]._quicknotify is True

    if channel_exit == "early":
        assert cerebro.close_channel() is True

    cerebro.adddata(bt.feeds.PandasData(dataname=_regular_data()))
    regular_strategies = cerebro.run()

    assert len(regular_strategies) == 1
    assert regular_strategies[0]._quicknotify is initial_quicknotify
    assert cerebro.p.quicknotify is initial_quicknotify


def test_channel_run_preserves_quicknotify_run_override():
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.addstrategy(QuicknotifyProbe)

    cerebro.run(channel=[], quicknotify=False)

    assert cerebro.p.quicknotify is False
    cerebro.adddata(bt.feeds.PandasData(dataname=_regular_data()))
    regular_strategies = cerebro.run()
    assert regular_strategies[0]._quicknotify is False


def test_channel_true_keeps_quicknotify_for_external_dispatch_and_notifications():
    cerebro = bt.Cerebro(stdstats=False, quicknotify=False)
    cerebro.addstrategy(QuicknotifyProbe)
    strategy = cerebro.run(channel=True)[0]

    assert cerebro.p.quicknotify is False
    assert strategy._quicknotify is True

    tick = SimpleNamespace(symbol="X", timestamp=1.0, price=10.0, volume=1.0)
    cerebro.dispatch_channel_event(SimpleNamespace(channel_type="tick", data=tick))
    assert strategy.ticks == [tick]

    order = SimpleNamespace(exectype=1, Historical=0, histnotify=True)
    strategy._notify(qorders=[order], qtrades=[])
    assert strategy.orders == [order]

    assert cerebro.close_channel() is True
    assert cerebro.p.quicknotify is False
