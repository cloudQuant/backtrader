"""I4DRF requires a complete finite price window before publishing a color."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.i4_drfv2 import I4DRFV2
from backtrader.indicators.contrib.i4_drfv3 import I4DRFV3
from tests.functional.strategies.trend_following.test_0247_0819_i4_drf_v2 import (
    ExpI4DRFV2Strategy,
)
from tests.functional.strategies.trend_following.test_0246_0816_i4_drf_v3 import (
    ExpI4DRFV3Strategy,
)


def _frame(count=90, *, bad_index=None, bad_value=math.nan, every="min", trend=False):
    close = [100.0 + i + (0 if trend else 2 * math.sin(0.7 * i)) for i in range(count)]
    if bad_index is not None:
        close[bad_index] = bad_value
    return pd.DataFrame(
        {"open": close, "high": [v + 1 for v in close], "low": [v - 1 for v in close],
         "close": close, "volume": [100.0] * count},
        index=pd.date_range("2024-01-01", periods=count, freq=every),
    )


def _expected(frame, index, cls, period):
    if index < period + 1:
        return math.nan, math.nan
    window = frame.iloc[index - period:index + 1]
    fields = ("close",) if cls is I4DRFV2 else ("high", "low")
    if not all(math.isfinite(float(v)) for field in fields for v in window[field]):
        return math.nan, math.nan
    total = 0.0
    for offset in range(period):
        now, prev = frame.iloc[index - offset], frame.iloc[index - offset - 1]
        if cls is I4DRFV2:
            total += 1.0 if now.close - prev.close > 0 else -1.0
        else:
            total += 1.0 if now.high - prev.high > 0 else 0.0
            total -= 1.0 if now.low - prev.low < 0 else 0.0
    value = total / period * 100.0
    return value, 1.0 if value > 0 else 0.0


def _run(cls, frame, *, runonce, period, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = cls(self.datas[-1], period=period)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        cerebro.adddata(bt.feeds.PandasData(dataname=primary))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].indicator


def _assert_expected(indicator, frame, cls, period):
    assert indicator._minperiod == period + 2
    assert len(indicator.value.array) == len(indicator.color.array) == len(frame)
    for index, (value, color) in enumerate(zip(indicator.value.array, indicator.color.array)):
        expected_value, expected_color = _expected(frame, index, cls, period)
        if math.isnan(expected_value):
            assert math.isnan(value), index
            assert math.isnan(color), index
        else:
            assert value == pytest.approx(expected_value), index
            assert color == expected_color, index


@pytest.mark.parametrize("cls", [I4DRFV2, I4DRFV3], ids=["v2", "v3"])
@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("period", [1, 3])
def test_missing_window_is_invalid_until_all_comparisons_recover(cls, runonce, period):
    frame = _frame(bad_index=20)
    indicator = _run(cls, frame, runonce=runonce, period=period)
    _assert_expected(indicator, frame, cls, period)
    assert all(math.isnan(v) for v in indicator.value.array[20:21 + period])
    assert all(math.isnan(v) for v in indicator.color.array[20:21 + period])
    assert math.isfinite(indicator.value.array[21 + period])


@pytest.mark.parametrize("cls", [I4DRFV2, I4DRFV3], ids=["v2", "v3"])
@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_finite_equal_prices_keep_original_direction_rules(cls, runonce):
    frame = _frame(40)
    frame.loc[:, "open"] = 100.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 99.0
    frame.loc[:, "close"] = 100.0
    indicator = _run(cls, frame, runonce=runonce, period=3)
    _assert_expected(indicator, frame, cls, 3)
    expected = -100.0 if cls is I4DRFV2 else 0.0
    assert all(v == expected for v in indicator.value.array[4:])
    assert all(v == 0.0 for v in indicator.color.array[4:])


@pytest.mark.parametrize("cls", [I4DRFV2, I4DRFV3], ids=["v2", "v3"])
@pytest.mark.parametrize("current,previous", [(math.inf, 100.0), (-math.inf, 100.0),
                                               (1e308, -1e308)],
                         ids=["positive_inf", "negative_inf", "finite_diff_overflow"])
def test_visible_infinite_price_or_difference_is_not_directional_signal(cls, current, previous):
    # Normal Feed LineBuffer writes may replace Inf with a finite default before
    # it reaches an indicator. Inject directly to test values visible here.
    line = {0: current, -1: previous}
    owner = SimpleNamespace(data=SimpleNamespace(close=line, high=line, low=line),
                            p=SimpleNamespace(period=1),
                            lines=SimpleNamespace(value=[0.0], color=[0.0]))
    cls.next(owner)
    assert math.isnan(owner.lines.value[0])
    assert math.isnan(owner.lines.color[0])


@pytest.mark.parametrize("cls", [I4DRFV2, I4DRFV3], ids=["v2", "v3"])
@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_feed_uses_complete_window_on_own_clock(cls, runonce):
    frame = _frame(bad_index=20, every="3min")
    indicator = _run(cls, frame, runonce=runonce, period=3, primary=_frame(270))
    _assert_expected(indicator, frame, cls, 3)


@pytest.mark.parametrize("cls", [I4DRFV2, I4DRFV3], ids=["v2", "v3"])
def test_replay_checks_each_revision_of_current_window(cls):
    class InjectUnavailableAfterReplay:
        """Simulate unavailable published prices on selected replay updates."""

        def __init__(self, data):
            self.count = 0

        def __call__(self, data):
            self.count += 1
            if 90 <= self.count < 98:
                data.high[0] = data.low[0] = data.close[0] = math.nan
            return False

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = cls(self.data, period=1)
            self.rows = []

        def next(self):
            if cls is I4DRFV2:
                required = [float(self.data.close[0]), float(self.data.close[-1])]
            else:
                required = [float(self.data.high[0]), float(self.data.high[-1]),
                            float(self.data.low[0]), float(self.data.low[-1])]
            self.rows.append((len(self.data), required,
                              float(self.indicator.value[0]), float(self.indicator.color[0])))

    frame = _frame(400)
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame)
    cerebro.replaydata(feed, timeframe=bt.TimeFrame.Minutes, compression=5)
    # Inject after the replay filter: its OHLC aggregation can otherwise turn
    # unavailable high/low prices into finite defaults before observation.
    feed.addfilter(InjectUnavailableAfterReplay)
    cerebro.addstrategy(Probe)
    rows = cerebro.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    assert any(not all(math.isfinite(v) for v in inputs) for _, inputs, _, _ in rows)
    assert any(all(math.isfinite(v) for v in inputs) for _, inputs, _, _ in rows)
    for _, inputs, value, color in rows:
        if not all(math.isfinite(v) for v in inputs):
            assert math.isnan(value)
            assert math.isnan(color)
        elif cls is I4DRFV2:
            expected = 100.0 if inputs[0] > inputs[1] else -100.0
            assert value == expected
            assert color == (1.0 if expected > 0 else 0.0)
        else:
            expected = (int(inputs[0] > inputs[1]) - int(inputs[2] < inputs[3])) * 100.0
            assert value == expected
            assert color == (1.0 if expected > 0 else 0.0)


@pytest.mark.parametrize("strategy", [ExpI4DRFV2Strategy, ExpI4DRFV3Strategy], ids=["v2", "v3"])
@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_public_strategy_skips_missing_and_first_recovered_color(strategy, runonce):
    class Trace(strategy):
        def __init__(self):
            super().__init__()
            self.rows = []

        def next(self):
            before = self.signal_count
            super().next()
            if len(self.signal_data) in (11, 12, 13):
                self.rows.append((len(self.signal_data), float(self.ind.color[-1]),
                                  float(self.ind.color[0]), self.signal_count - before))

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(30, trend=True)))
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(30, trend=True, bad_index=10)))
    cerebro.addstrategy(Trace, period=1, stop_loss_points=100000, take_profit_points=100000)
    rows = cerebro.run()[0].rows
    assert [row[0] for row in rows] == [11, 12, 13]
    assert math.isnan(rows[0][2]) and math.isnan(rows[1][2])
    assert math.isnan(rows[2][1]) and rows[2][2] == 1.0
    assert all(row[3] == 0 for row in rows)
