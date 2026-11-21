"""Williams %R requires a complete finite high/low window."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.iwpr_sign_indicator import IWPRSignIndicator


def _frame(count=160, *, bad_index=None, fields=(), every="min", flat=False):
    values = [100.0 if flat else 100.0 + 0.2 * i + 3 * math.sin(0.4 * i) for i in range(count)]
    frame = pd.DataFrame(
        {"open": values, "high": [v if flat else v + 1 for v in values],
         "low": [v if flat else v - 1 for v in values], "close": values,
         "volume": [100.0] * count},
        index=pd.date_range("2024-01-01", periods=count, freq=every),
    )
    if bad_index is not None:
        for field in fields:
            frame.iloc[bad_index, frame.columns.get_loc(field)] = math.nan
    return frame


def _expected(frame, index, period):
    if index < 15:  # Current default minperiod=16, which this round preserves.
        return math.nan
    window = frame.iloc[index - period + 1:index + 1]
    highs = [float(v) for v in window.high]
    lows = [float(v) for v in window.low]
    close = float(frame.iloc[index].close)
    if not all(math.isfinite(v) for v in highs + lows + [close]):
        return math.nan
    high, low = max(highs), min(lows)
    return -50.0 if high == low else -100.0 * (high - close) / (high - low)


def _run(frame, *, runonce, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = IWPRSignIndicator(self.datas[-1])

    c = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Probe)
    return c.run()[0].indicator


def _assert_wpr(indicator, frame):
    assert indicator._minperiod == 16
    assert len(indicator.wpr.array) == len(frame)
    for i, actual in enumerate(indicator.wpr.array):
        expected = _expected(frame, i, 14)
        if math.isnan(expected):
            assert math.isnan(actual), i
        else:
            assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12), i


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("field", ["high", "low", "close"])
def test_missing_required_price_and_full_window_recovery(runonce, field):
    frame = _frame(bad_index=80, fields=(field,))
    indicator = _run(frame, runonce=runonce)
    _assert_wpr(indicator, frame)
    assert math.isnan(indicator.wpr.array[80])
    if field in ("high", "low"):
        assert all(math.isnan(v) for v in indicator.wpr.array[80:94])
        assert math.isfinite(indicator.wpr.array[94])
        assert all(math.isnan(v) for v in indicator.buy.array[80:94])
        assert all(math.isnan(v) for v in indicator.sell.array[80:94])
    else:
        # Historical close is not part of the next WPR high/low window.
        assert math.isfinite(indicator.wpr.array[81])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_finite_flat_range_preserves_minus_fifty(runonce):
    frame = _frame(flat=True)
    indicator = _run(frame, runonce=runonce)
    _assert_wpr(indicator, frame)
    assert all(v == -50.0 for v in indicator.wpr.array[15:])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_feed_missing_window_and_recovery(runonce):
    signal = _frame(bad_index=80, fields=("high",), every="3min")
    indicator = _run(signal, runonce=runonce, primary=_frame(480))
    _assert_wpr(indicator, signal)
    assert all(math.isnan(v) for v in indicator.wpr.array[80:94])
    assert math.isfinite(indicator.wpr.array[94])


@pytest.mark.parametrize("field", ["high", "low", "close"])
@pytest.mark.parametrize("bad", [math.inf, -math.inf], ids=["positive_inf", "negative_inf"])
def test_nonfinite_values_visible_to_indicator_are_not_classified(field, bad):
    # The normal Feed LineBuffer can substitute finite defaults for infinity;
    # use a direct hook test for nonfinite values actually visible here.
    high = {0: 102.0, -1: 101.0, -2: 100.0}
    low = {0: 98.0, -1: 97.0, -2: 96.0}
    close = {0: 100.0}
    {"high": high, "low": low, "close": close}[field][0 if field == "close" else -1] = bad
    owner = SimpleNamespace(data=SimpleNamespace(high=high, low=low, close=close),
                            p=SimpleNamespace(wpr_period=3))
    assert math.isnan(IWPRSignIndicator._calc_wpr(owner))


def test_replay_recomputes_full_visible_window_on_each_revision():
    class InjectUnavailableAfterReplay:
        def __init__(self, data):
            self.count = 0

        def __call__(self, data):
            self.count += 1
            if 100 <= self.count < 108:
                data.high[0] = data.low[0] = data.close[0] = math.nan
            return False

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = IWPRSignIndicator(self.data)
            self.rows = []

        def next(self):
            highs = [float(self.data.high[-i]) for i in range(14)]
            lows = [float(self.data.low[-i]) for i in range(14)]
            self.rows.append((len(self.data), highs, lows, float(self.data.close[0]),
                              float(self.indicator.wpr[0])))

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=_frame(500))
    c.replaydata(feed, timeframe=bt.TimeFrame.Minutes, compression=5)
    # Inject after replay aggregation so the actual indicator sees NaN.
    feed.addfilter(InjectUnavailableAfterReplay)
    c.addstrategy(Probe)
    rows = c.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    assert any(not all(math.isfinite(v) for v in highs + lows + [close])
               for _, highs, lows, close, _ in rows)
    assert any(all(math.isfinite(v) for v in highs + lows + [close])
               for _, highs, lows, close, _ in rows)
    for _, highs, lows, close, actual in rows:
        if not all(math.isfinite(v) for v in highs + lows + [close]):
            assert math.isnan(actual)
        elif max(highs) == min(lows):
            assert actual == -50.0
        else:
            assert actual == pytest.approx(-100.0 * (max(highs) - close) /
                                           (max(highs) - min(lows)))
