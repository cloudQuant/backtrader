import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt


def make_frames():
    n = 38
    idx = pd.date_range("2024-01-01", periods=n, freq="min")
    closes = [100.0 + i for i in range(n)]
    closes[19] = math.nan
    common = {
        "open": [100.0] * n,
        "high": [200.0] * n,
        "low": [90.0] * n,
        "volume": [100.0] * n,
    }
    signal = pd.DataFrame({**common, "close": closes}, index=idx)
    execution = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [100.0] * n,
        },
        index=idx,
    )
    return execution, signal, closes


@pytest.mark.parametrize("runonce,exactbars", [(False, 0), (True, 0), (False, 1)])
@pytest.mark.parametrize("periods", [(2, 3), (3, 5)])
def test_window_means_and_invalid_color(runonce, exactbars, periods):
    _, frame, closes = make_frames()
    fast_period, slow_period = periods

    class Capture(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.TrendManagerIndicator(
                length1=fast_period, length2=slow_period
            )
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    len(self.data),
                    float(self.ind.fast_line[0]),
                    float(self.ind.slow_line[0]),
                    float(self.ind.color_state[0]),
                )
            )

    c = bt.Cerebro(stdstats=False, runonce=runonce, exactbars=exactbars)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Capture)
    s = c.run(preload=True)[0]
    assert s.rows[0][0] == max(periods) + 3
    for index, fast, slow, color in s.rows:

        def reference(period, end=index):
            vals = closes[end - period : end]
            return math.nan if any(math.isnan(x) for x in vals) else sum(vals) / period

        f, sl = reference(fast_period), reference(slow_period)
        for value, expected in ((fast, f), (slow, sl)):
            assert (
                math.isnan(value)
                if math.isnan(expected)
                else value == pytest.approx(expected)
            )
        if math.isnan(f) or math.isnan(sl):
            assert math.isnan(color), (index, fast, slow, color)
        else:
            assert color == (0.0 if f >= sl else 1.0)
    recovered = next(r for r in s.rows if r[0] == 20 + slow_period)
    assert recovered[3] == 0.0


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("scenario", ["false_sell", "false_buy_after_missing"])
def test_actual_strategy_no_false_flip_on_missing_and_window_recovery(
    runonce, scenario
):
    p = (
        Path(__file__).resolve().parents[3]
        / "tests/functional/strategies/mean_reversion/test_0081_0260_exp_trendmanager_tm_plus.py"
    )
    spec = importlib.util.spec_from_file_location("trend_manager_strategy_fixture", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)

    class Trace(m.ExpTrendManagerTmPlusStrategy):
        def __init__(self):
            super().__init__()
            self.signals = []

        def log(self, text):
            pass

        def _submit_entry(self, side, reason):
            self.signals.append((len(self.signal_data), side, reason))
            return super()._submit_entry(side, reason)

    execution, signal, _ = make_frames()
    if scenario == "false_buy_after_missing":
        values = (
            [120.0 - i for i in range(19)] + [math.nan] + [101.0 + i for i in range(18)]
        )
        signal.loc[:, "close"] = values
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=execution))
    c.adddata(bt.feeds.PandasData(dataname=signal))
    c.addstrategy(Trace, length1=2, length2=3, time_trade=False)
    s = c.run(preload=True)[0]
    assert s.signals == []
    assert not s.position


def test_single_feed_replay_same_bar_missing_then_revision():
    count = 72
    idx = pd.date_range("2024-01-01", periods=count, freq="min")
    closes = [100.0 + i for i in range(count)]
    closes[26] = math.nan
    frame = pd.DataFrame(
        {
            "open": [100.0] * count,
            "high": [200.0] * count,
            "low": [90.0] * count,
            "close": closes,
            "volume": [1.0] * count,
        },
        index=idx,
    )

    class Capture(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.TrendManagerIndicator(length1=2, length2=3)
            self.rows = []

        def next(self):
            window = list(self.data.close.get(size=3))
            self.rows.append(
                (
                    len(self.data),
                    window,
                    float(self.ind.fast_line[0]),
                    float(self.ind.slow_line[0]),
                    float(self.ind.color_state[0]),
                )
            )

    c = bt.Cerebro(stdstats=False)
    c.replaydata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=3,
    )
    c.addstrategy(Capture)
    s = c.run()[0]
    saw_nan = False
    saw_recovered = False
    for bar, window, fast, slow, color in s.rows:
        f = (
            math.nan
            if any(math.isnan(v) for v in window[-2:])
            else sum(window[-2:]) / 2
        )
        sl = math.nan if any(math.isnan(v) for v in window) else sum(window) / 3
        for v, exp in ((fast, f), (slow, sl)):
            assert math.isnan(v) if math.isnan(exp) else v == pytest.approx(exp)
        if math.isnan(f) or math.isnan(sl):
            assert math.isnan(color)
            if math.isnan(window[-1]):
                saw_nan = bar
        else:
            assert color == (0.0 if f >= sl else 1.0)
            if saw_nan and bar == saw_nan:
                saw_recovered = True
    assert saw_nan and saw_recovered
