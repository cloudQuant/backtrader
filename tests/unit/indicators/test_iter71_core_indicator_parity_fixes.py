"""Regression tests for core indicator runonce/runnext parity and warmup bounds:
- Average / ArithmeticMean, ExponentialSmoothing / ExpSmoothing, and
  ExponentialSmoothingDynamic / ExpSmoothingDynamic when attached to a multi-line
  DataSeries (PandasData or BacktraderCSVData) rather than a single LineBuffer.
- MFI previous-window lookback boundary on bar period + 1 (avoiding -period - 1
  out-of-bounds read while preserving minperiod = period + 1).
- HaDelta smoothed warmup alignment between once() and prenext()/nextstart().
- NewDiff minperiod accumulation over delayed close(-1) expression.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt


def _build_frame(bars: int = 80) -> pd.DataFrame:
    closes = [100.0 + i * 0.25 + math.sin(i * 0.37) * 2.5 for i in range(bars)]
    opens = [c - math.cos(i * 0.29) * 0.6 for i, c in enumerate(closes)]
    highs = [max(o, c) + 0.8 + (i % 3) * 0.15 for i, (o, c) in enumerate(zip(opens, closes))]
    lows = [min(o, c) - 0.7 - (i % 4) * 0.12 for i, (o, c) in enumerate(zip(opens, closes))]
    vols = [1000.0 + (i % 11) * 100.0 for i in range(bars)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
            "openinterest": [0.0] * bars,
        },
        index=pd.date_range("2024-01-01", periods=bars, freq="h"),
    )


def _assert_sequences_close(actual, expected, *, rel=1e-12, abs_tol=1e-12):
    assert len(actual) == len(expected)
    for idx, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), f"index {idx}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=rel, abs=abs_tol), (
                f"index {idx}: expected {want!r}, got {got!r}"
            )


@pytest.mark.parametrize(
    "ind_name,period",
    [
        ("ArithmeticMean", 1),
        ("ArithmeticMean", 5),
        ("ExpSmoothing", 1),
        ("ExpSmoothing", 5),
        ("ExpSmoothingDynamic", 1),
        ("ExpSmoothingDynamic", 5),
    ],
)
def test_average_and_exp_smoothing_on_pandas_dataseries_parity(ind_name: str, period: int):
    frame = _build_frame(60)
    ind_cls = getattr(bt.indicators, ind_name)

    def _run(runonce: bool):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = ind_cls(self.data, period=period)

        cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Probe)
        strat = cerebro.run()[0]
        return list(strat.ind.lines[0].array)

    arr_once = _run(True)
    arr_next = _run(False)
    _assert_sequences_close(arr_once, arr_next)
    assert all(math.isnan(v) for v in arr_once[: period - 1])
    assert all(math.isfinite(v) for v in arr_once[period - 1 :])


def test_average_on_csv_dataseries_runonce_and_runnext_parity():
    csv_path = (
        Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    )

    def _run(runonce: bool):
        class Probe(bt.Strategy):
            def __init__(self):
                self.avg = bt.indicators.Average(self.data, period=5)

        cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(csv_path)))
        cerebro.addstrategy(Probe)
        strat = cerebro.run()[0]
        return list(strat.avg.lines[0].array)

    arr_once = _run(True)
    arr_next = _run(False)
    _assert_sequences_close(arr_once, arr_next)
    assert all(math.isfinite(v) for v in arr_once[4:])


def test_mfi_previous_window_no_out_of_bounds_and_parity():
    frame = _build_frame(60)

    def _run(runonce: bool):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = bt.indicators.MFI(self.data, period=14)

        cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Probe)
        strat = cerebro.run()[0]
        assert strat.ind._minperiod == 15
        return list(strat.ind.lines.mfi.array)

    arr_once = _run(True)
    arr_next = _run(False)
    _assert_sequences_close(arr_once, arr_next)
    assert all(math.isnan(v) for v in arr_once[:15])
    assert all(math.isfinite(v) for v in arr_once[15:])


def test_hadelta_full_sequence_warmup_and_mature_parity():
    frame = _build_frame(50)

    def _run(runonce: bool):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = bt.indicators.HaDelta(self.data, period=3)

        cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Probe)
        strat = cerebro.run()[0]
        assert strat.ind._minperiod == 4
        return (
            list(strat.ind.lines.haDelta.array),
            list(strat.ind.lines.smoothed.array),
        )

    hd_once, sm_once = _run(True)
    hd_next, sm_next = _run(False)
    _assert_sequences_close(hd_once, hd_next)
    _assert_sequences_close(sm_once, sm_next)
    assert all(math.isnan(v) for v in sm_once[:3])
    assert all(math.isfinite(v) for v in sm_once[3:])


def test_newdiff_minperiod_and_runonce_runnext_parity():
    frame = _build_frame(50)

    def _run(runonce: bool):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = bt.indicators.NewDiff(self.data, period=5)

        cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Probe)
        strat = cerebro.run()[0]
        assert strat.ind._minperiod == 6
        return list(strat.ind.lines.factor.array)

    arr_once = _run(True)
    arr_next = _run(False)
    _assert_sequences_close(arr_once, arr_next)
    assert all(math.isnan(v) for v in arr_once[:5])
    assert all(math.isfinite(v) for v in arr_once[5:])
