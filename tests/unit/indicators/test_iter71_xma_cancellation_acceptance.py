"""Compare the rolling XMA against its original ordered window sum."""

import builtins
import math
from itertools import islice

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators.contrib.xma_ichimoku as xma_module
from backtrader.indicators.contrib.xma_ichimoku import XmaIchimoku


class OrderedXma(XmaIchimoku):
    """Use the pre-optimization SMA operation on the same retained window."""

    def _smooth_value(self, raw_value):
        method = str(self.p.xma_method).upper()
        if method not in ("SMA", "MODE_SMA_"):
            return super()._smooth_value(raw_value)
        period = max(1, int(self.p.x_length))
        if period > self._raw_buf.maxlen:
            raise ValueError("window exceeds retained capacity")
        if len(self._raw_buf) < period:
            return raw_value
        start = len(self._raw_buf) - period
        window = self._raw_buf if start == 0 else islice(self._raw_buf, start, None)
        return sum(window) / float(period)


class LegacySmoothXma(XmaIchimoku):
    """A subclass using the one-argument hook supported by the original."""

    def _smooth_value(self, raw_value):
        return super()._smooth_value(raw_value)


def _frame(values):
    return pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values), "openinterest": [0.0] * len(values)},
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )


def _run(values, *, exactbars=0, replay=False, dynamic=False, grow=False, reverse=False,
         legacy=False, runonce=False):
    class Probe(bt.Strategy):
        def __init__(self):
            candidate = LegacySmoothXma if legacy else XmaIchimoku
            classes = (candidate, OrderedXma) if reverse else (OrderedXma, candidate)
            first, second = (cls(self.data, up_period=1, dn_period=1, x_length=128)
                             for cls in classes)
            self.original, self.current = (second, first) if reverse else (first, second)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.original[0]), float(self.current[0])))
            count = len(self.rows)
            if dynamic and count in (170, 210, 250, 290):
                for indicator in (self.original, self.current):
                    if count == 170:
                        indicator.p.x_length = 64
                    elif count == 210:
                        indicator.p.x_length = 128
                    elif count == 250:
                        indicator.p.xma_method = "EMA"
                    else:
                        indicator.p.xma_method = "SMA"
            if grow and count == 170:
                for indicator in (self.original, self.current):
                    indicator.p.x_length = 160

    cerebro = bt.Cerebro(stdstats=False, exactbars=exactbars, runonce=runonce,
                         preload=not exactbars)
    data = bt.feeds.PandasData(dataname=_frame(values))
    if replay:
        cerebro.replaydata(data, timeframe=bt.TimeFrame.Minutes, compression=5)
    else:
        cerebro.adddata(data)
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].rows


def _assert_exact(rows):
    assert rows
    for bar, expected, actual in rows:
        if math.isnan(expected):
            assert math.isnan(actual), (bar, expected, actual)
        else:
            assert actual == expected, (bar, expected, actual)


@pytest.mark.parametrize("exactbars", [0, 1])
def test_cancellation_reproduces_ordered_sum(exactbars):
    values = [8.0] * 300 + [1.0, 1e16, -1e16] + [8.0] * 125 + [1.0] + [8.0] * 20
    rows = _run(values, exactbars=exactbars)
    _assert_exact(rows)
    assert next(expected for bar, expected, _ in rows if bar == 429) == 7.8203125


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_long_window_original_hook_and_runonce(runonce, legacy):
    values = ([0.1] * 300 + [1.0, 1e16, -1e16] + [8.0] * 125
              + [1.0] + [0.2] * 300)
    _assert_exact(_run(values, legacy=legacy, runonce=runonce))


@pytest.mark.parametrize("exactbars", [0, 1])
def test_nonfinite_fractional_and_dynamic_period(exactbars):
    values = [float((i * 17) % 43) + 0.1 for i in range(850)]
    values[300:306] = [-5e307] * 5 + [1e308]
    values[550:553] = [float("nan"), float("inf"), -float("inf")]
    _assert_exact(_run(values, exactbars=exactbars, dynamic=True))


def test_uniform_fractional_windows_reuse_ordered_sum(monkeypatch):
    calls = []

    def measured_sum(values):
        calls.append(len(values))
        return builtins.sum(values)

    monkeypatch.setattr(xma_module, "sum", measured_sum, raising=False)
    rows = _run([0.1] * 500 + [0.2] * 500 + [0.1] * 500)
    _assert_exact(rows)
    # Transition windows still use the original ordered summation. Once a
    # window is uniform, repeating its value leaves every ordered input equal.
    assert 200 < len(calls) < 400


@pytest.mark.parametrize("exactbars", [0, 1])
def test_replay_same_bar_and_dynamic_period(exactbars):
    values = [float((i * 19) % 101) for i in range(2400)]
    values[1200:1203] = [1.0, 1e16, -1e16]
    rows = _run(values, exactbars=exactbars, replay=True, dynamic=True)
    _assert_exact(rows)
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))


@pytest.mark.parametrize("reverse", [False, True])
def test_growing_after_discard_remains_an_error(reverse):
    with pytest.raises(ValueError, match="older raw values were discarded"):
        _run([8.0] * 500, grow=True, reverse=reverse)
