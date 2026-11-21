"""Real MUV strategy must not trade from unavailable or stale cloud signals."""

import datetime as dt
import math

import backtrader as bt
import pytest

from tests.functional.strategies.trend_following.test_0311_1259_muv_nordiff_cloud import (
    MUVNorDiffCloudStrategy,
)


class _Feed(bt.feed.DataBase):
    params = (("gap", None),)

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == 48:
            return False
        self.datetime[0] = bt.date2num(dt.datetime(2020, 1, 1) + dt.timedelta(days=self.index))
        self.open[0], self.high[0], self.low[0] = 100.0, 101.0, 99.0
        self.close[0] = math.nan if self.index == self.p.gap else 100.0
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        self.index += 1
        return True


def _run(seed, runonce, *, gap=None, scenario=None, signal_bar=1):
    class Probe(MUVNorDiffCloudStrategy):
        def __init__(self):
            super().__init__()
            self.actions = []
            self.completed = []

        def log(self, text):
            pass

        def buy(self, *args, **kwargs):
            self.actions.append((len(self.data), "buy"))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.actions.append((len(self.data), "sell"))
            return super().sell(*args, **kwargs)

        def close(self, *args, **kwargs):
            self.actions.append((len(self.data), "close"))
            return super().close(*args, **kwargs)

        def notify_order(self, order):
            if order.status == order.Completed:
                self.completed.append(order.executed.size)

        def next(self):
            bar = len(self.data)
            if scenario is not None:
                # Set controlled cloud observations on the actual indicator
                # lines to exercise a recovered boundary despite EMA's
                # documented no-reseed behavior after missing data.
                self.indicator.buy[0] = self.indicator.sell[0] = 0.0
                self.indicator.sma_res[0] = self.indicator.ema_res[0] = 1.0
                if scenario == "boundary":
                    if bar == 39:
                        if seed == "long":
                            self.indicator.sell[0] = -100.0
                        else:
                            self.indicator.buy[0] = 100.0
                    elif bar == 40:
                        self.indicator.sma_res[0] = math.nan
                elif scenario == "continuous" and bar == 36:
                    self.indicator.sell[0] = -100.0
                elif scenario == "nan_signal" and bar == 39:
                    self.indicator.buy[0] = math.nan
                elif scenario == "opposite_signal_gap":
                    if bar == 37:
                        if seed == "long":
                            self.indicator.sell[0] = -100.0
                        else:
                            self.indicator.buy[0] = 100.0
                    elif bar == 38:
                        if seed == "long":
                            self.indicator.buy[0] = math.nan
                        else:
                            self.indicator.sell[0] = math.nan
            if bar == 34:
                if seed == "long":
                    self.buy(size=1.0)
                elif seed == "short":
                    self.sell(size=1.0)
                return
            if scenario == "continuous" and bar < 38:
                return
            if scenario == "opposite_signal_gap" and bar < 40:
                return
            super().next()

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(_Feed(gap=gap))
    engine.addstrategy(Probe, signal_bar=signal_bar)
    return engine.run(runonce=runonce, preload=True)[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("seed", ["flat", "long", "short"])
def test_actual_missing_close_does_not_open_close_or_reverse(seed, runonce):
    result = _run(seed, runonce, gap=34)
    expected = {"flat": [], "long": [(34, "buy")], "short": [(34, "sell")]}
    assert result.actions == expected[seed]
    assert result.completed == {"flat": [], "long": [1.0], "short": [-1.0]}[seed]
    assert result.position.size == {"flat": 0, "long": 1.0, "short": -1.0}[seed]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("seed", ["long", "short"])
@pytest.mark.parametrize("signal_bar", [1, 2])
def test_recovered_cloud_does_not_scan_across_missing_boundary(seed, signal_bar, runonce):
    result = _run(seed, runonce, scenario="boundary", signal_bar=signal_bar)
    assert result.actions == [(34, "buy" if seed == "long" else "sell")]
    assert result.completed == [1.0 if seed == "long" else -1.0]
    assert result.position.size == (1.0 if seed == "long" else -1.0)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_nonfinite_signal_is_not_a_trade_signal(runonce):
    result = _run("flat", runonce, scenario="nan_signal")
    assert result.actions == []
    assert result.completed == []


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("seed", ["long", "short"])
@pytest.mark.parametrize("signal_bar", [1, 2])
def test_historical_scan_stops_on_nonfinite_opposite_signal(seed, signal_bar, runonce):
    result = _run(seed, runonce, scenario="opposite_signal_gap", signal_bar=signal_bar)
    assert result.actions == [(34, "buy" if seed == "long" else "sell")]
    assert result.completed == [1.0 if seed == "long" else -1.0]
    assert result.position.size == (1.0 if seed == "long" else -1.0)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_recent_signal_within_continuously_valid_cloud_still_closes(runonce):
    result = _run("long", runonce, scenario="continuous")
    assert result.actions == [(34, "buy"), (38, "close"), (38, "sell")]
    assert result.completed == [1.0, -1.0]
    assert result.position.size == 0.0
